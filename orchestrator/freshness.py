"""단일 신선도(Freshness) 판정 — READ ONLY DB 검사.

목적: ④ 통합보고서 파이프라인 곳곳(`product_integrated_insight.py`)에 흩어져 있던
"DB 에 이미 있나(캐시 hit) / 없나(fetch 필요)" 판단을 한 곳에 모은다. 이 모듈은
**SELECT 만** 수행하며 어떤 것도 생성/수정하지 않는다 — 라우팅과 관측(observability)
용 자문(advisory) 신호일 뿐, 실제 보강(executor)은 여전히 기존 idempotent 함수가
담당한다. YouTube API 는 일절 건드리지 않는다.

기존 비공개 헬퍼들과 동일한 SQL 을 재사용한다:
  - 댓글 분석 유무: product_integrated_insight._videos_with_existing_comment_analysis
  - 자막 유무:     product_integrated_insight._videos_missing_transcript
  - ①②③ 유무:    video_reports 컬럼 (transcript_report/comment_report/integrated_report)
  - 동일 조합 ④:   product_integrated_reports (get_latest_product_integrated_report 파싱 방식)
"""
from __future__ import annotations

import json
from typing import List, Optional, TypedDict

from scripts.database.queries import query_all


class FreshnessReport(TypedDict, total=False):
    video_ids: List[str]
    total: int
    # 댓글 분석(agent_decisions 행 존재)
    comment_analyzed_ids: List[str]
    comment_missing_ids: List[str]
    all_comment_analyzed: bool
    # 자막(video_transcripts 행 존재)
    transcript_present_ids: List[str]
    transcript_missing_ids: List[str]
    # 영상별 보고서 ①②③ 유무
    reports_status: dict  # video_id -> {"r1": bool, "r2": bool, "r3": bool}
    fully_reported_ids: List[str]  # r1 & r2 & r3 모두 True
    # 동일 video_ids 조합으로 이미 생성된 ④ 보고서 (정확 집합 일치)
    prior_report_id: Optional[int]
    prior_video_ids: List[str]
    prior_source_video_count: Optional[int]
    prior_exact_match: bool


def _placeholders(n: int) -> str:
    return ",".join(["%s"] * n)


def inspect_freshness(product_id: int, video_ids: List[str]) -> FreshnessReport:
    """주어진 video_ids 의 리소스 상태를 한 번에 분류한다 (SELECT 전용)."""
    report: FreshnessReport = {
        "video_ids": list(video_ids),
        "total": len(video_ids),
        "comment_analyzed_ids": [],
        "comment_missing_ids": list(video_ids),
        "all_comment_analyzed": False,
        "transcript_present_ids": [],
        "transcript_missing_ids": list(video_ids),
        "reports_status": {},
        "fully_reported_ids": [],
        "prior_report_id": None,
        "prior_video_ids": [],
        "prior_source_video_count": None,
        "prior_exact_match": False,
    }
    if not video_ids:
        report["all_comment_analyzed"] = True  # 빈 집합은 공허 참
        return report

    ph = _placeholders(len(video_ids))
    params = tuple(video_ids)

    # 1) 댓글 분석 유무 (comments ⋈ agent_decisions)
    comment_rows = query_all(
        f"""
        SELECT DISTINCT c.video_id
        FROM comments c
        INNER JOIN agent_decisions ad ON c.comment_id = ad.comment_id
        WHERE c.video_id IN ({ph})
        """,
        params,
    )
    analyzed = {r["video_id"] for r in comment_rows}
    report["comment_analyzed_ids"] = [v for v in video_ids if v in analyzed]
    report["comment_missing_ids"] = [v for v in video_ids if v not in analyzed]
    report["all_comment_analyzed"] = len(report["comment_missing_ids"]) == 0

    # 2) 자막 유무 (video_transcripts)
    tx_rows = query_all(
        f"SELECT video_id FROM video_transcripts WHERE video_id IN ({ph})",
        params,
    )
    have_tx = {r["video_id"] for r in tx_rows}
    report["transcript_present_ids"] = [v for v in video_ids if v in have_tx]
    report["transcript_missing_ids"] = [v for v in video_ids if v not in have_tx]

    # 3) 보고서 ①②③ 유무 (video_reports)
    rep_rows = query_all(
        f"""
        SELECT video_id, transcript_report, comment_report, integrated_report
        FROM video_reports WHERE video_id IN ({ph})
        """,
        params,
    )
    rep_by_id = {r["video_id"]: r for r in rep_rows}
    status = {}
    fully = []
    for vid in video_ids:
        row = rep_by_id.get(vid) or {}
        r1 = bool(row.get("transcript_report"))
        r2 = bool(row.get("comment_report"))
        r3 = bool(row.get("integrated_report"))
        status[vid] = {"r1": r1, "r2": r2, "r3": r3}
        if r1 and r2 and r3:
            fully.append(vid)
    report["reports_status"] = status
    report["fully_reported_ids"] = fully

    # 4) 동일 조합 ④ 보고서 (정확 집합 일치, 최신순 첫 매치)
    requested = set(video_ids)
    prior_rows = query_all(
        """
        SELECT id, video_ids, source_video_count
        FROM product_integrated_reports
        WHERE product_id = %s
        ORDER BY created_at DESC
        """,
        (product_id,),
    )
    for row in prior_rows:
        parsed = _parse_video_ids(row.get("video_ids") or "")
        if set(parsed) == requested:
            report["prior_report_id"] = row["id"]
            report["prior_video_ids"] = parsed
            report["prior_source_video_count"] = row.get("source_video_count")
            report["prior_exact_match"] = True
            break

    return report


def _parse_video_ids(raw: str) -> List[str]:
    """product_integrated_reports.video_ids (JSON 문자열 또는 콤마구분) 파싱.

    get_latest_product_integrated_report 의 파싱 로직과 동일.
    """
    try:
        loaded = json.loads(raw)
        if isinstance(loaded, list):
            return [str(x) for x in loaded]
    except (ValueError, TypeError):
        pass
    return [s.strip() for s in raw.split(",") if s.strip()]
