"""영상 선정 평가 리포트 CLI.

사용:
    python -m video_selection_agent.evaluation.cli --run-id <uuid>
    python -m video_selection_agent.evaluation.cli --product-id 123
    python -m video_selection_agent.evaluation.cli --recent 50

운영 DB(`DATABASE_URL`) 의 `video_selection_runs/scores` 를 읽어 지표 산출.
"""
from __future__ import annotations

import argparse
import json
import sys
from typing import Any
from uuid import UUID

from psycopg2.extras import RealDictCursor

from scripts.database.connection import get_connection
from video_selection_agent.evaluation.metrics import (
    aggregate_metrics,
    compute_selection_metrics,
)


def _fetch_run_scores(run_id: UUID) -> list[dict[str, Any]]:
    conn = get_connection()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(
            """
            SELECT s.video_id, s.selected, s.rank, s.final_score, s.dimensions_json,
                   s.tier, v.channel_id
            FROM video_selection_scores s
            LEFT JOIN videos v ON s.video_id = v.video_id
            WHERE s.run_id = %s
            ORDER BY s.selected DESC, s.rank ASC
            """,
            (str(run_id),),
        )
        return [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()


def _list_recent_runs(limit: int, product_id: int | None) -> list[UUID]:
    conn = get_connection()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        if product_id is not None:
            cur.execute(
                """
                SELECT run_id FROM video_selection_runs
                WHERE product_id = %s
                ORDER BY created_at DESC NULLS LAST
                LIMIT %s
                """,
                (product_id, limit),
            )
        else:
            cur.execute(
                """
                SELECT run_id FROM video_selection_runs
                ORDER BY created_at DESC NULLS LAST
                LIMIT %s
                """,
                (limit,),
            )
        return [UUID(str(r["run_id"])) for r in cur.fetchall()]
    finally:
        conn.close()


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="영상 선정 평가 리포트")
    grp = p.add_mutually_exclusive_group(required=True)
    grp.add_argument("--run-id", help="단일 run UUID")
    grp.add_argument("--product-id", type=int, help="해당 제품의 최근 run 들")
    grp.add_argument("--recent", type=int, help="최근 N 개 run 전체 평균")
    p.add_argument(
        "--limit", type=int, default=10, help="--product-id 와 함께 쓸 때 최근 N 개"
    )
    args = p.parse_args(argv)

    try:
        if args.run_id:
            rows = _fetch_run_scores(UUID(args.run_id))
            report: dict[str, Any] = {
                "run_id": args.run_id,
                "metrics": compute_selection_metrics(rows),
            }
        elif args.product_id is not None:
            run_ids = _list_recent_runs(args.limit, args.product_id)
            runs = [_fetch_run_scores(rid) for rid in run_ids]
            report = {
                "product_id": args.product_id,
                "run_count": len(run_ids),
                "aggregate": aggregate_metrics(runs),
                "per_run": [
                    {"run_id": str(rid), "metrics": compute_selection_metrics(r)}
                    for rid, r in zip(run_ids, runs)
                ],
            }
        else:
            run_ids = _list_recent_runs(args.recent, None)
            runs = [_fetch_run_scores(rid) for rid in run_ids]
            report = {
                "run_count": len(run_ids),
                "aggregate": aggregate_metrics(runs),
            }
    except Exception as e:
        print(f"[ERROR] {type(e).__name__}: {e}", file=sys.stderr)
        return 1

    json.dump(report, sys.stdout, ensure_ascii=False, indent=2, default=str)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
