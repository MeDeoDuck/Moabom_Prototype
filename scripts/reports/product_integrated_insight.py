"""
제품 단위 통합 인사이트 보고서 (RunYourAI / openai/gpt-4.1-2025-04-14)

입력: 동일 제품에 대한 N개 영상의 자막 기반 보고서(video_reports.transcript_report).
출력: 영상별 보고서들만을 근거로 합성한 9섹션 통합 인사이트 보고서.
환각 방지: 입력 보고서에 등장하지 않은 사실은 절대 만들어 내지 않는다.
"""
import asyncio
import json
from datetime import date
from time import perf_counter
from typing import List, Dict, Optional, Tuple

from scripts.config import RUNYOURAI_API_KEY
from scripts.database.queries import query_one, query_all, execute_insert, execute_update
from scripts.reports.transcript_report import (
    build_transcript_report,
    fix_encoding,
    get_report_llm_client,
    REPORT_LLM_DEPLOYMENT,
)
from scripts.reports.integrated_report import upsert_video_report
from scripts.utils.prompt_manager import build_product_integrated_insight_prompt
from scripts.youtube.transcript_service import fetch_video_transcript


# 영상별 보고서 1건당 입력 시 잘라낼 최대 길이 (토큰 한도 보호)
PER_VIDEO_REPORT_MAX_CHARS = 1500
# 통합 입력 전체에 대한 안전 상한
TOTAL_INPUT_MAX_CHARS = 18000

HEURISTIC_MODEL_LABEL = "heuristic"

# Pass 2 동시성 상한 — feedback_llm_perf_lessons 측정 기준
COLLECT_MAX_CONCURRENCY = 5

# 라우트가 즉시 읽을 수 있도록 마지막 호출의 perf breakdown 저장
_LAST_COLLECT_PERF: Dict = {}
_LAST_LLM_PERF: Dict = {}


# ── 1) 입력 수집 ─────────────────────────────────────────────────

def _save_transcript_row(video_id: str, fetched: Dict) -> None:
    """fetch_video_transcript 결과를 video_transcripts에 UPSERT (메인 스레드 전용)."""
    execute_update(
        """INSERT INTO video_transcripts (video_id, transcript_text, language_code, segment_count, source)
           VALUES (%s, %s, %s, %s, %s)
           ON CONFLICT (video_id)
           DO UPDATE SET
             transcript_text = EXCLUDED.transcript_text,
             language_code   = EXCLUDED.language_code,
             segment_count   = EXCLUDED.segment_count,
             source          = EXCLUDED.source,
             updated_at      = NOW()""",
        (
            video_id,
            fetched["transcript_text"],
            fetched.get("language_code"),
            fetched.get("segment_count"),
            "youtube_transcript_api",
        ),
    )


def _worker_fetch_and_build(vid: str, transcript_text: Optional[str]) -> Dict:
    """병렬 워커: DB 접근 금지. fetch_video_transcript + build_transcript_report만 수행.
    반환: {"video_id", "transcript_text", "fetched_payload", "transcript_report", "fetch_ms", "build_ms", "error"}
    """
    result: Dict = {
        "video_id": vid,
        "transcript_text": transcript_text,
        "fetched_payload": None,  # video_transcripts UPSERT용 raw payload (Pass 3에서 사용)
        "transcript_report": None,
        "fetch_ms": 0.0,
        "build_ms": 0.0,
        "error": None,
    }

    # 자막 없으면 받기
    if not transcript_text:
        t0 = perf_counter()
        try:
            fetched = fetch_video_transcript(vid)
        except Exception as e:
            result["error"] = f"fetch_failed: {type(e).__name__}: {e}"
            result["fetch_ms"] = (perf_counter() - t0) * 1000
            return result
        result["fetch_ms"] = (perf_counter() - t0) * 1000
        if not fetched or not fetched.get("transcript_text"):
            result["error"] = "fetch_empty"
            return result
        result["fetched_payload"] = fetched
        result["transcript_text"] = fetched["transcript_text"]

    # 자막 → 보고서 생성
    t0 = perf_counter()
    try:
        generated = build_transcript_report(result["transcript_text"])
    except Exception as e:
        result["error"] = f"build_failed: {type(e).__name__}: {e}"
        result["build_ms"] = (perf_counter() - t0) * 1000
        return result
    result["build_ms"] = (perf_counter() - t0) * 1000
    if not generated or generated.startswith("[ERROR]"):
        result["error"] = "build_empty_or_error"
        return result
    result["transcript_report"] = generated
    return result


async def collect_transcript_reports_for_product(
    product_id: int,
    video_ids: List[str],
) -> List[Dict]:
    """
    선택된 영상들에 대해 video_reports.transcript_report를 조회하고, 누락분은 병렬로 보완한다.

    Self-healing 3-pass 구조:
      Pass 1: 직렬 DB 일괄 조회 — 캐시 hit/miss 분류
      Pass 2: 병렬 워커 (asyncio.gather + to_thread, Semaphore=COLLECT_MAX_CONCURRENCY)
              fetch_video_transcript + build_transcript_report만. DB 접근 금지.
      Pass 3: 직렬 DB 쓰기 — video_transcripts UPSERT + upsert_video_report

    반환: [{"video_id": ..., "title": ..., "transcript_report": ...}, ...] (입력 순서 보존)
    """
    global _LAST_COLLECT_PERF
    route_t0 = perf_counter()

    if not video_ids:
        _LAST_COLLECT_PERF = {
            "total_ms": 0.0, "cache_hits": 0, "self_heal_count": 0,
            "fetch_ms_sum": 0.0, "build_report_ms_sum": 0.0, "per_video": [],
        }
        return []

    # ── Pass 1: 직렬 DB 일괄 조회 ───────────────────────────
    # video_ids는 사용자가 보낸 임의 문자열이라 placeholder 동적 생성 (psycopg2가 escape 처리)
    placeholders = ",".join(["%s"] * len(video_ids))
    videos_params = tuple(video_ids) + (product_id,)
    video_rows = query_all(
        f"SELECT video_id, title FROM videos WHERE video_id IN ({placeholders}) AND product_id = %s",
        videos_params,
    )
    video_meta = {r["video_id"]: r for r in video_rows}

    report_rows = query_all(
        f"SELECT video_id, transcript_report FROM video_reports WHERE video_id IN ({placeholders})",
        tuple(video_ids),
    )
    cached_reports = {r["video_id"]: r.get("transcript_report") for r in report_rows if r.get("transcript_report")}

    # cached_reports에 없는 영상만 자막 캐시 조회
    need_after_report = [v for v in video_ids if v in video_meta and v not in cached_reports]
    cached_transcripts: Dict[str, str] = {}
    if need_after_report:
        placeholders2 = ",".join(["%s"] * len(need_after_report))
        transcript_rows = query_all(
            f"SELECT video_id, transcript_text FROM video_transcripts WHERE video_id IN ({placeholders2})",
            tuple(need_after_report),
        )
        cached_transcripts = {r["video_id"]: r.get("transcript_text") for r in transcript_rows if r.get("transcript_text")}

    # 영상별 상태 분류
    ready: Dict[str, str] = {}  # vid -> transcript_report
    pending: List[Tuple[str, Optional[str]]] = []  # (vid, transcript_text or None)
    not_found: List[str] = []
    for vid in video_ids:
        if vid not in video_meta:
            not_found.append(vid)
            continue
        if vid in cached_reports:
            ready[vid] = cached_reports[vid]
        else:
            pending.append((vid, cached_transcripts.get(vid)))

    for vid in not_found:
        print(f"[WARN] product_integrated_insight: video {vid} not found for product {product_id}")

    # ── Pass 2: 병렬 워커 ──────────────────────────────────
    worker_results: List[Dict] = []
    if pending:
        semaphore = asyncio.Semaphore(COLLECT_MAX_CONCURRENCY)

        async def _bounded(vid: str, ttext: Optional[str]) -> Dict:
            async with semaphore:
                return await asyncio.to_thread(_worker_fetch_and_build, vid, ttext)

        gathered = await asyncio.gather(
            *[_bounded(vid, ttext) for vid, ttext in pending],
            return_exceptions=True,
        )
        for vid_ttext, res in zip(pending, gathered):
            if isinstance(res, BaseException):
                print(f"[WARN] product_integrated_insight: worker exception for {vid_ttext[0]}: {type(res).__name__}: {res}")
                continue
            worker_results.append(res)

    # ── Pass 3: 직렬 DB 쓰기 ───────────────────────────────
    fetch_ms_sum = 0.0
    build_ms_sum = 0.0
    self_heal_success = 0
    per_video_perf: List[Dict] = []
    for res in worker_results:
        fetch_ms_sum += res["fetch_ms"]
        build_ms_sum += res["build_ms"]
        per_video_perf.append({
            "video_id": res["video_id"],
            "fetch_ms": round(res["fetch_ms"], 1),
            "build_ms": round(res["build_ms"], 1),
            "error": res["error"],
        })
        if res["error"]:
            print(f"[WARN] product_integrated_insight: skip {res['video_id']} — {res['error']}")
            continue
        if res["fetched_payload"]:
            _save_transcript_row(res["video_id"], res["fetched_payload"])
        upsert_video_report(res["video_id"], transcript_report=res["transcript_report"])
        ready[res["video_id"]] = res["transcript_report"]
        self_heal_success += 1

    # ── 결과 조립 (입력 순서 보존) ─────────────────────────
    results: List[Dict] = []
    for vid in video_ids:
        if vid not in ready:
            continue
        meta = video_meta.get(vid, {})
        results.append({
            "video_id": vid,
            "title": meta.get("title") or "",
            "transcript_report": ready[vid],
        })

    total_ms = (perf_counter() - route_t0) * 1000
    _LAST_COLLECT_PERF = {
        "total_ms": round(total_ms, 1),
        "cache_hits": len(cached_reports),
        "self_heal_count": self_heal_success,
        "fetch_ms_sum": round(fetch_ms_sum, 1),
        "build_report_ms_sum": round(build_ms_sum, 1),
        "per_video": per_video_perf,
    }
    print(
        f"[PERF][collect] product_id={product_id} total_ms={total_ms:.1f} "
        f"cache_hits={len(cached_reports)} self_heal={self_heal_success}/{len(pending)} "
        f"fetch_sum_ms={fetch_ms_sum:.1f} build_sum_ms={build_ms_sum:.1f}"
    )
    return results


def get_last_collect_perf() -> Dict:
    """라우트가 응답 JSON 조립용으로 마지막 collect perf breakdown을 읽는다."""
    return dict(_LAST_COLLECT_PERF)


def get_last_llm_perf() -> Dict:
    """라우트가 응답 JSON 조립용으로 마지막 build LLM perf breakdown을 읽는다."""
    return dict(_LAST_LLM_PERF)


# ── 2) 통합 보고서 생성 ──────────────────────────────────────────

def _truncate_per_video(per_video_reports: List[Dict]) -> List[Dict]:
    """각 영상 보고서를 안전 길이로 자르고, 전체 입력이 너무 길면 추가 축소."""
    truncated: List[Dict] = []
    for r in per_video_reports:
        body = (r.get("transcript_report") or "").strip()
        if len(body) > PER_VIDEO_REPORT_MAX_CHARS:
            body = body[:PER_VIDEO_REPORT_MAX_CHARS].rstrip() + "\n... (이하 생략)"
        truncated.append({
            "video_id": r.get("video_id", ""),
            "title": r.get("title", ""),
            "transcript_report": body,
        })

    total = sum(len(t["transcript_report"]) for t in truncated)
    if total <= TOTAL_INPUT_MAX_CHARS or not truncated:
        return truncated

    # 전체 길이가 한도를 넘으면 영상별 한도를 비례 축소
    per_video_cap = max(400, TOTAL_INPUT_MAX_CHARS // max(1, len(truncated)))
    shrunk: List[Dict] = []
    for t in truncated:
        body = t["transcript_report"]
        if len(body) > per_video_cap:
            body = body[:per_video_cap].rstrip() + "\n... (이하 생략)"
        shrunk.append({**t, "transcript_report": body})
    return shrunk


def _heuristic_fallback_report(product_name: str, per_video_reports: List[Dict]) -> str:
    """LLM 미사용 모드. 9개 섹션 헤더만 깔끔히 출력하고 본문은 '데이터 부족'으로 채운다.
    환각을 만들지 않는 것이 최우선.
    """
    n = len(per_video_reports)
    today_str = date.today().isoformat()
    sections = [
        f"# {product_name} 종합 인사이트 보고서 (LLM 미사용 모드)",
        "",
        "## ① 한줄 구매 판정 + 종합 점수",
        "- 데이터 부족 (LLM 미사용 모드)",
        "",
        "## ② 핵심 요약",
        "- 데이터 부족 (LLM 미사용 모드)",
        "",
        "## ③ 6차원 종합 평가",
        "- 데이터 부족 (LLM 미사용 모드)",
        "",
        "## ④ 장점 / 단점 (합의 기반)",
        "- 데이터 부족 (LLM 미사용 모드)",
        "",
        "## ⑤ 리뷰어 간 의견이 갈리는 지점 (Divergence)",
        "- 데이터 부족 (LLM 미사용 모드)",
        "",
        "## ⑥ 리뷰어 vs 실사용자 갭",
        "- 데이터 부족 (LLM 미사용 모드)",
        "",
        "## ⑦ 전작 대비 달라진 점",
        "- 데이터 부족 (LLM 미사용 모드)",
        "",
        "## ⑧ 이런 사람에게 추천 / 비추",
        "- 데이터 부족 (LLM 미사용 모드)",
        "",
        "## ⑨ 경쟁/대체 제품 비교",
        "- 데이터 부족 (LLM 미사용 모드)",
        "",
        "---",
        "📊 분석 기반",
        f"   분석 영상: {n}개",
        f"   보고서 생성일: {today_str}",
        "",
        "## 입력 영상별 보고서 (참고)",
    ]
    for i, r in enumerate(per_video_reports):
        sections.append("")
        sections.append(f"### 영상 {i+1} — {r.get('title','')} (video_id={r.get('video_id','')})")
        body = (r.get("transcript_report") or "").strip()
        if len(body) > PER_VIDEO_REPORT_MAX_CHARS:
            body = body[:PER_VIDEO_REPORT_MAX_CHARS].rstrip() + "\n... (이하 생략)"
        sections.append(body)
    return "\n".join(sections)


def build_product_integrated_insight_report(
    product_name: str,
    per_video_reports: List[Dict],
) -> Tuple[str, str]:
    """
    9섹션 통합 인사이트 보고서를 생성한다.
    RunYourAI 우선 사용, 미설정/실패 시 heuristic fallback.

    반환: (report_text, model_used)
    """
    global _LAST_LLM_PERF
    _LAST_LLM_PERF = {"llm_ms": None, "fallback": False}

    if not per_video_reports:
        _LAST_LLM_PERF["fallback"] = True
        return ("[ERROR] 입력 보고서가 없습니다.", HEURISTIC_MODEL_LABEL)

    truncated = _truncate_per_video(per_video_reports)
    today_str = date.today().isoformat()
    prompt = build_product_integrated_insight_prompt(product_name, truncated, today_str=today_str)

    if not RUNYOURAI_API_KEY:
        print("[WARN] RUNYOURAI_API_KEY not configured — using heuristic fallback")
        _LAST_LLM_PERF["fallback"] = True
        return (_heuristic_fallback_report(product_name, truncated), HEURISTIC_MODEL_LABEL)

    try:
        client = get_report_llm_client()
    except ValueError as e:
        print(f"[WARN] RunYourAI client unavailable: {e} — using heuristic fallback")
        _LAST_LLM_PERF["fallback"] = True
        return (_heuristic_fallback_report(product_name, truncated), HEURISTIC_MODEL_LABEL)

    try:
        print(f"[DEBUG] product_integrated_insight: calling {REPORT_LLM_DEPLOYMENT} for {product_name} (n={len(truncated)})")
        llm_t0 = perf_counter()
        response = client.chat.completions.create(
            model=REPORT_LLM_DEPLOYMENT,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.2,
            max_tokens=2200,
        )
        llm_ms = (perf_counter() - llm_t0) * 1000
        _LAST_LLM_PERF["llm_ms"] = round(llm_ms, 1)
        print(f"[PERF][insight_llm] product={product_name} n={len(truncated)} llm_ms={llm_ms:.1f}")
        if not response.choices:
            print("[WARN] product_integrated_insight: empty response — using heuristic fallback")
            _LAST_LLM_PERF["fallback"] = True
            return (_heuristic_fallback_report(product_name, truncated), HEURISTIC_MODEL_LABEL)
        text = response.choices[0].message.content or ""
        text = fix_encoding(text.strip())
        if not text:
            print("[WARN] product_integrated_insight: empty text — using heuristic fallback")
            _LAST_LLM_PERF["fallback"] = True
            return (_heuristic_fallback_report(product_name, truncated), HEURISTIC_MODEL_LABEL)
        print(f"[DEBUG] product_integrated_insight: report length={len(text)}")
        return (text, REPORT_LLM_DEPLOYMENT)
    except Exception as e:
        print(f"[ERROR] product_integrated_insight LLM call failed: {type(e).__name__}: {e}")
        _LAST_LLM_PERF["fallback"] = True
        return (_heuristic_fallback_report(product_name, truncated), HEURISTIC_MODEL_LABEL)


# ── 3) 저장 / 조회 ───────────────────────────────────────────────

def save_product_integrated_report(
    product_id: int,
    video_ids: List[str],
    report_text: str,
    model_used: str,
) -> int:
    """product_integrated_reports에 INSERT 후 id 반환 (이력 보존)."""
    video_ids_json = json.dumps(list(video_ids), ensure_ascii=False)
    new_id = execute_insert(
        """INSERT INTO product_integrated_reports
              (product_id, video_ids, source_video_count, report_text, model_used)
           VALUES (%s, %s, %s, %s, %s)
           RETURNING id""",
        (product_id, video_ids_json, len(video_ids), report_text, model_used),
    )
    return new_id


def get_latest_product_integrated_report(product_id: int) -> Optional[Dict]:
    """최신 통합 보고서 1건 조회 (없으면 None)."""
    row = query_one(
        """SELECT id, product_id, video_ids, source_video_count, report_text, model_used, created_at
           FROM product_integrated_reports
           WHERE product_id = %s
           ORDER BY created_at DESC
           LIMIT 1""",
        (product_id,),
    )
    if not row:
        return None
    parsed_video_ids: List[str] = []
    raw_ids = row.get("video_ids") or ""
    try:
        loaded = json.loads(raw_ids)
        if isinstance(loaded, list):
            parsed_video_ids = [str(x) for x in loaded]
    except (ValueError, TypeError):
        parsed_video_ids = [s.strip() for s in raw_ids.split(",") if s.strip()]
    return {
        "id": row["id"],
        "product_id": row["product_id"],
        "video_ids": parsed_video_ids,
        "source_video_count": row["source_video_count"],
        "report_text": row["report_text"],
        "model_used": row.get("model_used"),
        "created_at": row.get("created_at"),
    }


def get_product_integrated_report(product_id: int, report_id: int) -> Optional[Dict]:
    """특정 통합 보고서 조회 (PDF 다운로드용)."""
    row = query_one(
        """SELECT id, product_id, video_ids, source_video_count, report_text, model_used, created_at
           FROM product_integrated_reports
           WHERE product_id = %s AND id = %s""",
        (product_id, report_id),
    )
    if not row:
        return None
    return {
        "id": row["id"],
        "product_id": row["product_id"],
        "source_video_count": row["source_video_count"],
        "report_text": row["report_text"],
        "model_used": row.get("model_used"),
        "created_at": row.get("created_at"),
    }
