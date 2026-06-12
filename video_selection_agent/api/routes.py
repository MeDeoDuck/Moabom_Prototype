"""FR-005 엔드포인트.

POST /products/{product_id}/select-videos
GET  /products/{product_id}/selection-runs/{run_id}

선정된 영상에 대해 댓글 수집·필터링 파이프라인까지 동기 실행해서 댓글/통합
보고서가 빈 채로 표시되지 않도록 한다 (Custom UI의 첫 번째 미리보기 호출은
`process_comments=false`로 스킵 가능).
"""
from __future__ import annotations

import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout, as_completed
from typing import Any, Iterable
from uuid import UUID

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from scripts.database.queries import query_one
from video_selection_agent.activation import (
    apply_v3_selection,
    run_v3_sync,
    shadow_candidates,
)
from video_selection_agent.core.agent import VideoSelectionAgent
from video_selection_agent.core.models import ProductContext, SelectionDecision
from video_selection_agent.core.policy import SelectionPolicyConfig
from video_selection_agent.metrics import compute_selection_metrics
from video_selection_agent.persistence.repository import (
    cache_transcripts,
    load_latest_selected_ids,
    load_selection,
    save_selection,
    update_run_shadow_metrics,
)
from video_selection_agent.strategy import V1_WEIGHTED, V3_CLUSTER, resolve_strategy


class SelectVideosRequest(BaseModel):
    # 선정 정책은 auto 고정 (k=5, candidate_pool_size=30 — SelectionPolicyConfig 기본값).
    # Custom 직접 선택 모드와 k/pool 파라미터는 v1 피드백으로 제거됨.
    # 구 클라이언트가 보내는 잔여 필드(mode/k 등)는 Pydantic이 무시한다.
    process_comments: bool = True


_FALLBACK_POSITIVE_KEYWORDS = {
    "좋다", "훌륭", "추천", "완벽", "최고", "멋진", "빠르다", "빠른", "강력", "강력한",
    "좋은", "좋습니다", "훌륭합니다", "amazing", "great", "excellent", "awesome",
    "best", "love", "perfect", "worth", "impressed", "beautiful", "fast", "powerful",
}
_FALLBACK_NEGATIVE_KEYWORDS = {
    "나쁘다", "문제", "느리다", "느린", "비싸다", "비싼", "약하다", "약한", "못쓸",
    "망했", "실망", "후회", "환불", "bad", "terrible", "poor", "awful", "slow",
    "expensive", "waste", "regret", "disappointing", "broken", "fragile",
}


def _fallback_collect_comments(video_id: str) -> int:
    """Agent 불가 시 단순 YouTube API 수집 + 키워드 sentiment.

    `scripts/api/sync.py` 의 fallback 분기와 동일한 결과를 만들어 댓글/통합
    보고서가 빈 채로 남지 않도록 graceful degrade.
    """
    from scripts.database.connection import get_connection
    from scripts.database.queries import execute_update
    from scripts.youtube.comment_service import fetch_video_comments

    try:
        comments = fetch_video_comments(video_id, max_pages=2)
    except Exception as exc:  # noqa: BLE001
        print(f"[SELECT] [{video_id}] Fallback fetch failed: {exc}")
        return 0

    if not comments:
        return 0

    inserted = 0
    for c in comments:
        try:
            execute_update(
                """INSERT INTO comments (comment_id, video_id, text_raw, is_product_related)
                   VALUES (%s, %s, %s, %s)
                   ON CONFLICT (comment_id) DO UPDATE SET
                       video_id = EXCLUDED.video_id,
                       text_raw = EXCLUDED.text_raw,
                       is_product_related = EXCLUDED.is_product_related""",
                (c["comment_id"], video_id, c["text_raw"], True),
            )

            text = (c["text_raw"] or "").lower()
            pos = sum(1 for kw in _FALLBACK_POSITIVE_KEYWORDS if kw in text)
            neg = sum(1 for kw in _FALLBACK_NEGATIVE_KEYWORDS if kw in text)
            if pos > neg:
                label, score = "positive", 0.7
            elif neg > pos:
                label, score = "negative", 0.3
            else:
                label, score = "neutral", 0.5

            conn = get_connection()
            cur = conn.cursor()
            cur.execute(
                "DELETE FROM comment_sentiments WHERE comment_id = %s",
                (c["comment_id"],),
            )
            cur.execute(
                """INSERT INTO comment_sentiments (comment_id, sentiment_label, sentiment_score, analysis_weight, created_at)
                   VALUES (%s, %s, %s, %s, NOW())""",
                (c["comment_id"], label, score, 1.0),
            )
            conn.commit()
            cur.close()
            conn.close()
            inserted += 1
        except Exception as exc:  # noqa: BLE001
            print(
                f"[SELECT] [{video_id}] Fallback insert failed for comment "
                f"{c.get('comment_id')}: {exc}"
            )
            continue

    return inserted


def _process_comments_for_videos(product_name: str, video_ids: Iterable[str]) -> None:
    """선정된 영상들에 대해 댓글 수집·LLM 분류·감정 분석 파이프라인을 실행.

    Agent(`comment_filtering_agent`) 사용 가능 시 정확도 높은 LLM 경로로 병렬 처리,
    불가 시 단순 YouTube API 수집 + 키워드 sentiment 로 graceful degrade.
    """
    ids = [vid for vid in video_ids if vid]
    if not ids:
        return

    agent_available = False
    parallel_workers = 3
    process_comments_with_agent = None
    try:
        from scripts.api.sync import (
            AGENT_AVAILABLE,
            PARALLEL_WORKERS,
            process_comments_with_agent as _process_agent,
        )

        agent_available = AGENT_AVAILABLE
        parallel_workers = PARALLEL_WORKERS
        process_comments_with_agent = _process_agent
    except ImportError as exc:
        print(f"[SELECT] Comment agent module unavailable: {exc}")

    if agent_available and process_comments_with_agent is not None:
        print(
            f"[SELECT] Comment processing start (agent): "
            f"videos={len(ids)}, parallel={parallel_workers}"
        )
        with ThreadPoolExecutor(max_workers=parallel_workers) as executor:
            futures = {
                executor.submit(process_comments_with_agent, vid, product_name): vid
                for vid in ids
            }
            for future in as_completed(futures):
                vid = futures[future]
                try:
                    stats = future.result()
                    print(f"[SELECT] [{vid}] Agent comments processed: {stats}")
                except Exception as exc:  # noqa: BLE001
                    print(
                        f"[SELECT] [{vid}] Agent failed: {exc}; "
                        "falling back to simple collection"
                    )
                    n = _fallback_collect_comments(vid)
                    print(f"[SELECT] [{vid}] Fallback collected={n}")
    else:
        print(f"[SELECT] Comment processing start (fallback): videos={len(ids)}")
        for vid in ids:
            n = _fallback_collect_comments(vid)
            print(f"[SELECT] [{vid}] Fallback collected={n}")


def _decision_to_response(decision: Any) -> dict:
    score_lookup = getattr(decision, "all_scores", {}) or {}
    # SelectedVideo 에는 없지만 VideoCandidate 에는 이미 있는 메타데이터를
    # 응답에만 함께 실어 보내기 위한 룩업 (선정 로직/저장 구조는 불변).
    candidate_by_id = {c.video_id: c for c in decision.candidates_preview}

    return {
        "run_id": str(decision.run_id),
        "mode": decision.mode,
        "selected": [
            {
                "video_id": v.video_id,
                "title": v.title,
                "channel_name": v.channel_name,
                "tier": v.tier,
                "rank": v.rank,
                "final_score": v.final_score,
                "dimensions": v.dimensions,
                "weighted_contributions": v.weighted_contributions,
                "rationale_short": v.rationale_short,
                "rationale_full": v.rationale_full,
                "selection_reasons": v.selection_reasons,
                # VideoCandidate 에서 그대로 가져온 표시용 메타데이터 (없으면 None).
                "thumbnail_url": getattr(
                    candidate_by_id.get(v.video_id), "thumbnail_url", None
                ),
                "duration_seconds": getattr(
                    candidate_by_id.get(v.video_id), "duration_seconds", None
                ),
                "channel_subscriber_count": getattr(
                    candidate_by_id.get(v.video_id), "channel_subscriber_count", None
                ),
            }
            for v in decision.selected
        ],
        "diversity_report": {
            "channels_unique": decision.diversity_report.channels_unique,
            "tier_distribution": decision.diversity_report.tier_distribution,
            "max_channel_occurrence": decision.diversity_report.max_channel_occurrence,
        },
        "candidate_count": decision.candidate_count,
        "model_used": decision.model_used,
        "policy_version": decision.policy_version,
    }


def _shadow_enabled() -> bool:
    return os.environ.get("V3_SHADOW_ENABLED", "0") == "1"


def _maybe_launch_coarse_shadow(decision: SelectionDecision) -> None:
    """v3 coarse shadow 를 별도 스레드로 실행 (설계 §8, v1_weighted 경로 측정용).

    사용자 응답을 막지 않게 fire-and-forget. 결과는 metrics_json.shadow_v3 로 patch.
    gate: V3_SHADOW_ENABLED=1 + auto 모드만. (v3_cluster 활성화 시엔 inline 실행하므로
    이 비동기 shadow 는 안 쓴다.)
    """
    if not _shadow_enabled() or decision.mode != "auto":
        return

    cand_dicts = shadow_candidates(decision)
    v1_ids = [v.video_id for v in decision.selected]
    run_id = decision.run_id
    # fine(자막 fetch) 은 차단 위험 때문에 coarse 와 별도 게이트로 좁게 켠다(설계 §8/§10).
    do_fine = os.environ.get("V3_SHADOW_FETCH_TRANSCRIPTS", "0") == "1"

    def _worker() -> None:
        try:
            from video_selection_agent.clustering.shadow import run_shadow

            shadow = run_shadow(cand_dicts, v1_ids, do_fine=do_fine)
            update_run_shadow_metrics(run_id, shadow)
        except Exception as e:  # 스레드 내부 격리 — 본류 무영향
            print(f"[shadow] launch failed for {run_id}: {e}", flush=True)

    threading.Thread(target=_worker, name=f"shadow-{run_id}", daemon=True).start()


def register_selection_routes(app: FastAPI) -> None:
    """main.py에서 1회 호출."""

    @app.post("/products/{product_id}/select-videos")
    async def select_videos(product_id: int, request: SelectVideosRequest) -> dict:
        product = query_one(
            "SELECT * FROM tech_products WHERE product_id = %s", (product_id,)
        )
        if not product:
            raise HTTPException(status_code=404, detail="Product not found")

        context = ProductContext(
            product_id=product_id,
            name=product["name"],
            brand=product.get("brand"),
            category=product.get("category"),
            keywords=[],
        )

        policy = SelectionPolicyConfig()  # k=5, candidate_pool_size=30 고정
        agent = VideoSelectionAgent(policy=policy)
        # strategy feature flag (v3 설계 §8). v3_cluster 면 v1 위에서 재선택.
        strategy, downgrade_note = resolve_strategy()
        t0 = time.perf_counter()
        decision = agent.select(product=context, mode="auto", k=5)

        # v3 활성화 (PR4): v1 후보 위에 coarse+fine 재선택을 동기 실행. 깔끔한 선택이
        # 나오면 교체, 실패/fallback 이면 v1 유지(안전 복귀).
        strategy_effective = strategy
        shadow_result = None
        if strategy == V3_CLUSTER:
            try:
                # latency 상한 가드: 자막 fetch 가 막히면 v3 가 90s+ 걸릴 수 있음
                # (실측). 상한 초과 시 포기하고 v1 반환 — 속도(P0) 보호.
                timeout_s = float(os.environ.get("V3_SYNC_TIMEOUT", "60"))
                with ThreadPoolExecutor(max_workers=1) as ex:
                    fut = ex.submit(run_v3_sync, decision)
                    shadow_result = fut.result(timeout=timeout_s)
                if apply_v3_selection(decision, shadow_result):
                    strategy_effective = V3_CLUSTER
                else:
                    strategy_effective = V1_WEIGHTED  # v3 fallback → v1
            except FuturesTimeout:
                print("[select_videos] v3 sync timeout → v1 fallback", flush=True)
                shadow_result = {"ok": False, "error": "v3 sync timeout"}
                strategy_effective = V1_WEIGHTED
            except Exception as e:  # 어떤 실패도 v1 으로 복귀
                print(f"[select_videos] v3 sync failed, v1 fallback: {e}", flush=True)
                strategy_effective = V1_WEIGHTED
        latency_ms = int((time.perf_counter() - t0) * 1000)

        selected_ids = {v.video_id for v in decision.selected}
        all_scores = {
            vid: {
                "final_score": float(sb.final_score),
                # Merge ScoreBreakdown.extras (e.g. scope_label/scope_confidence
                # from scope_filter node) into dimensions_json. Keeps the JSONB
                # column the single source of per-video auxiliary signals
                # without a schema change.
                "dimensions": {**sb.dimensions, **sb.extras},
                "tier": sb.tier,
                "rank": sb.rank,
                "rationale_short": sb.llm_rationale_short,
                "rationale_full": sb.llm_rationale_full,
                "selected": vid in selected_ids,
            }
            for vid, sb in decision.all_scores.items()
        }
        candidate_lookup = {
            c.video_id: {
                "title": c.title,
                "description": c.description,
                "published_at": c.published_at,
                "thumbnail_url": c.thumbnail_url,
                "view_count": c.view_count,
                "like_count": c.like_count,
                "comment_count": c.comment_count,
                "channel_id": c.channel_id,
                "channel_name": c.channel_name,
                "channel_subscriber_count": c.channel_subscriber_count,
                "duration_seconds": c.duration_seconds,
            }
            for c in decision.candidates_preview
        }
        # 계측 (v3 설계 §7): 직전 run 과의 overlap 은 이번 run 저장 전에 조회.
        try:
            prev_selected_ids = load_latest_selected_ids(product_id)
        except Exception as e:  # 계측 실패가 선정 응답을 막지 않게 격리
            print(f"[select_videos] prev selected lookup failed: {e}")
            prev_selected_ids = None
        metrics = compute_selection_metrics(
            decision,
            strategy=strategy_effective,
            latency_ms=latency_ms,
            prev_selected_ids=prev_selected_ids,
            downgrade_note=downgrade_note,
        )
        # v3 가 fetch 한 선택 영상 자막을 분리(메트릭 비대화 방지) → 저장 후 캐시 적재.
        selected_transcripts: dict = {}
        if shadow_result is not None:
            fs = shadow_result.get("final_select")
            if isinstance(fs, dict):
                selected_transcripts = fs.pop("_selected_transcripts", {}) or {}
            metrics["shadow_v3"] = shadow_result
            metrics["v3_applied"] = strategy_effective == V3_CLUSTER
        save_selection(
            decision,
            all_scores=all_scores,
            candidate_lookup=candidate_lookup,
            reset_existing_videos=request.process_comments,
            strategy=strategy_effective,
            metrics=metrics,
        )

        # v3 가 fetch 한 선택 영상 자막을 video_transcripts 로 캐시 → 보고서가 재fetch
        # 없이 재사용(이중 fetch/429 제거). videos 적재(save_selection) 후라 FK 만족.
        if strategy_effective == V3_CLUSTER and selected_transcripts:
            try:
                n = cache_transcripts(selected_transcripts)
                print(f"[select_videos] cached {n} v3 transcripts for reuse", flush=True)
            except Exception as e:
                print(f"[select_videos] transcript cache failed: {e}", flush=True)

        # v1_weighted 경로일 때만 비동기 coarse shadow (측정용). v3_cluster 는 위에서
        # inline 으로 이미 실행했으므로 중복 실행하지 않는다.
        if strategy_effective != V3_CLUSTER:
            _maybe_launch_coarse_shadow(decision)

        if request.process_comments:
            _process_comments_for_videos(
                product_name=context.name,
                video_ids=[v.video_id for v in decision.selected],
            )

        return _decision_to_response(decision)

    @app.get("/products/{product_id}/selection-runs/{run_id}")
    async def get_selection_run(product_id: int, run_id: UUID) -> dict:
        decision = load_selection(run_id)
        if decision is None or decision.product_id != product_id:
            raise HTTPException(status_code=404, detail="Selection run not found")
        return _decision_to_response(decision)
