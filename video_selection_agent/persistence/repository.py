"""SelectionDecision 영속화.

- `video_selection_runs`: 실행 1회당 1row (audit trail).
- `video_selection_scores`: 후보 × run (선정/미선정 + 점수 + rationale).
- `videos`: 선정된 영상을 `selection_mode` 포함해 upsert.
"""
from __future__ import annotations

import json
from uuid import UUID

from scripts.database.connection import get_connection
from video_selection_agent.core.models import (
    DiversityReport,
    SelectedVideo,
    SelectionDecision,
)


def save_selection(
    decision: SelectionDecision,
    all_scores: dict[str, dict] | None = None,
    candidate_lookup: dict[str, dict] | None = None,
    reset_existing_videos: bool = False,
) -> None:
    """선정 결과를 3개 테이블에 기록.

    `all_scores`: video_id → {final_score, dimensions, tier, rank, rationale_short/full, selected}
      finalize 후 scores 전체를 담아 호출.
    `candidate_lookup`: video_id → {title, channel_id, channel_name, subs, duration, ...}
      선정된 영상만 videos 테이블에 upsert할 때 사용.
    `reset_existing_videos`: True면 같은 트랜잭션에서 해당 product의 기존 videos를 wipe.
      FK CASCADE로 comments/transcripts/reports 등 자식 데이터도 함께 정리됨.
      video_selection_runs/scores는 video_id FK가 없어 이력 보존.
    """
    conn = get_connection()
    try:
        cursor = conn.cursor()

        if reset_existing_videos:
            cursor.execute(
                "DELETE FROM videos WHERE product_id = %s",
                (decision.product_id,),
            )

        cursor.execute(
            """
            INSERT INTO video_selection_runs
                (run_id, product_id, mode, model_used, policy_version,
                 k_selected, candidate_count, trace_json)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                str(decision.run_id),
                decision.product_id,
                decision.mode,
                decision.model_used,
                decision.policy_version,
                len(decision.selected),
                decision.candidate_count,
                json.dumps(decision.trace, ensure_ascii=False),
            ),
        )

        if all_scores:
            rows = [
                (
                    str(decision.run_id),
                    vid,
                    bool(info.get("selected", False)),
                    info.get("rank"),
                    info.get("final_score"),
                    json.dumps(info.get("dimensions", {}), ensure_ascii=False),
                    info.get("tier"),
                    info.get("rationale_short", "")[:4000],
                    info.get("rationale_full", "")[:8000],
                )
                for vid, info in all_scores.items()
            ]
            cursor.executemany(
                """
                INSERT INTO video_selection_scores
                    (run_id, video_id, selected, rank, final_score,
                     dimensions_json, tier, rationale_short, rationale_full)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                rows,
            )

        if candidate_lookup:
            for selected in decision.selected:
                c = candidate_lookup.get(selected.video_id)
                if not c:
                    continue
                cursor.execute(
                    """
                    INSERT INTO videos
                        (video_id, product_id, title, description, published_at,
                         thumbnail_url, view_count, like_count, comment_count,
                         channel_id, channel_name, channel_subscriber_count,
                         duration_seconds, selection_mode)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (video_id) DO UPDATE SET
                        title = EXCLUDED.title,
                        description = EXCLUDED.description,
                        published_at = EXCLUDED.published_at,
                        thumbnail_url = EXCLUDED.thumbnail_url,
                        view_count = EXCLUDED.view_count,
                        like_count = EXCLUDED.like_count,
                        comment_count = EXCLUDED.comment_count,
                        channel_id = EXCLUDED.channel_id,
                        channel_name = EXCLUDED.channel_name,
                        channel_subscriber_count = EXCLUDED.channel_subscriber_count,
                        duration_seconds = EXCLUDED.duration_seconds,
                        selection_mode = EXCLUDED.selection_mode
                    """,
                    (
                        selected.video_id,
                        decision.product_id,
                        c["title"],
                        c.get("description", ""),
                        c.get("published_at"),
                        c.get("thumbnail_url", ""),
                        c.get("view_count", 0),
                        c.get("like_count", 0),
                        c.get("comment_count", 0),
                        c.get("channel_id", ""),
                        c.get("channel_name", ""),
                        c.get("channel_subscriber_count", 0),
                        c.get("duration_seconds", 0),
                        decision.mode,
                    ),
                )

        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def load_selection(run_id: UUID) -> SelectionDecision | None:
    """run_id로 재조회."""
    from psycopg2.extras import RealDictCursor

    conn = get_connection()
    try:
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute(
            "SELECT * FROM video_selection_runs WHERE run_id = %s",
            (str(run_id),),
        )
        run = cursor.fetchone()
        if not run:
            return None

        cursor.execute(
            """
            SELECT s.*, v.title, v.channel_name
            FROM video_selection_scores s
            LEFT JOIN videos v ON s.video_id = v.video_id
            WHERE s.run_id = %s
            ORDER BY s.selected DESC, s.rank ASC
            """,
            (str(run_id),),
        )
        rows = cursor.fetchall()

        selected: list[SelectedVideo] = []
        for row in rows:
            if not row["selected"]:
                continue
            dims = row["dimensions_json"] or {}
            selected.append(
                SelectedVideo(
                    video_id=row["video_id"],
                    title=row.get("title") or "",
                    channel_name=row.get("channel_name") or "",
                    tier=row.get("tier") or "mid",
                    rank=row["rank"] or 0,
                    final_score=float(row["final_score"] or 0.0),
                    dimensions=dims,
                    weighted_contributions={},
                    rationale_short=row.get("rationale_short") or "",
                    rationale_full=row.get("rationale_full") or "",
                    selection_reasons=[],
                )
            )

        trace = json.loads(run["trace_json"]) if run.get("trace_json") else []
        return SelectionDecision(
            run_id=run_id,
            product_id=run["product_id"],
            mode=run["mode"],
            selected=selected,
            candidates_preview=[],
            diversity_report=DiversityReport(0, {}, 0),
            candidate_count=run["candidate_count"] or 0,
            model_used=run.get("model_used") or "",
            policy_version=run.get("policy_version") or "",
            trace=trace,
        )
    finally:
        conn.close()
