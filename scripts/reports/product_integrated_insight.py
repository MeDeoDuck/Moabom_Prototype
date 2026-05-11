"""
제품 단위 통합 인사이트 보고서 (Azure OpenAI / GPT-4.1-mini)

입력: 동일 제품에 대한 N개 영상의 자막 기반 보고서(video_reports.transcript_report).
출력: 영상별 보고서들만을 근거로 합성한 9섹션 통합 인사이트 보고서.
환각 방지: 입력 보고서에 등장하지 않은 사실은 절대 만들어 내지 않는다.
"""
import json
from datetime import date
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


# ── 1) 입력 수집 ─────────────────────────────────────────────────

def _fetch_and_save_transcript(video_id: str) -> Optional[str]:
    """video_transcripts에 자막이 없을 때 youtube에서 가져와 저장하고 본문을 반환한다.
    실패 시 None.
    """
    fetched = fetch_video_transcript(video_id)
    if not fetched or not fetched.get("transcript_text"):
        return None
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
    return fetched["transcript_text"]


def collect_transcript_reports_for_product(
    product_id: int,
    video_ids: List[str],
) -> List[Dict]:
    """
    선택된 영상들에 대해 video_reports.transcript_report를 조회한다.

    종합 인사이트는 영상 상세 페이지 방문 여부와 무관하게 self-contained 동작해야 하므로,
    각 영상에 대해 다음 순서로 자체 보완한다:
      1) video_reports.transcript_report 가 있으면 사용
      2) 없으면 video_transcripts.transcript_text 로 build_transcript_report 호출
      3) 자막 본문도 없으면 fetch_video_transcript 로 YouTube에서 직접 받아 저장 후 위 2)
      4) 모든 단계 실패한 영상만 결과에서 제외

    반환: [{"video_id": ..., "title": ..., "transcript_report": ...}, ...]
    """
    results: List[Dict] = []

    for vid in video_ids:
        video_row = query_one(
            "SELECT video_id, title FROM videos WHERE video_id = %s AND product_id = %s",
            (vid, product_id),
        )
        if not video_row:
            print(f"[WARN] product_integrated_insight: video {vid} not found for product {product_id}")
            continue

        # 1) transcript_report 캐시 확인
        report_row = query_one(
            "SELECT transcript_report FROM video_reports WHERE video_id = %s",
            (vid,),
        )
        transcript_report = report_row.get("transcript_report") if report_row else None

        if not transcript_report:
            # 2) transcript_text 캐시 확인
            transcript_row = query_one(
                "SELECT transcript_text FROM video_transcripts WHERE video_id = %s",
                (vid,),
            )
            transcript_text = transcript_row.get("transcript_text") if transcript_row else None

            # 3) 자막조차 없으면 YouTube에서 즉시 받아 저장
            if not transcript_text:
                print(f"[DEBUG] product_integrated_insight: fetching missing transcript for {vid}")
                transcript_text = _fetch_and_save_transcript(vid)
                if not transcript_text:
                    print(f"[WARN] product_integrated_insight: transcript fetch failed for {vid}, skipping")
                    continue

            # 자막 → 자막 기반 보고서 생성 + 저장
            print(f"[DEBUG] product_integrated_insight: generating missing transcript_report for {vid}")
            generated = build_transcript_report(transcript_text)
            if not generated or generated.startswith("[ERROR]"):
                print(f"[WARN] product_integrated_insight: failed to generate transcript_report for {vid}")
                continue
            upsert_video_report(vid, transcript_report=generated)
            transcript_report = generated

        results.append({
            "video_id": video_row["video_id"],
            "title": video_row.get("title") or "",
            "transcript_report": transcript_report,
        })

    return results


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
    Azure OpenAI 우선 사용, 미설정/실패 시 heuristic fallback.

    반환: (report_text, model_used)
    """
    if not per_video_reports:
        return ("[ERROR] 입력 보고서가 없습니다.", HEURISTIC_MODEL_LABEL)

    truncated = _truncate_per_video(per_video_reports)
    today_str = date.today().isoformat()
    prompt = build_product_integrated_insight_prompt(product_name, truncated, today_str=today_str)

    if not RUNYOURAI_API_KEY:
        print("[WARN] RUNYOURAI_API_KEY not configured — using heuristic fallback")
        return (_heuristic_fallback_report(product_name, truncated), HEURISTIC_MODEL_LABEL)

    try:
        client = get_report_llm_client()
    except ValueError as e:
        print(f"[WARN] RunYourAI client unavailable: {e} — using heuristic fallback")
        return (_heuristic_fallback_report(product_name, truncated), HEURISTIC_MODEL_LABEL)

    try:
        print(f"[DEBUG] product_integrated_insight: calling {REPORT_LLM_DEPLOYMENT} for {product_name} (n={len(truncated)})")
        response = client.chat.completions.create(
            model=REPORT_LLM_DEPLOYMENT,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.2,
            max_tokens=2200,
        )
        if not response.choices:
            print("[WARN] product_integrated_insight: empty response — using heuristic fallback")
            return (_heuristic_fallback_report(product_name, truncated), HEURISTIC_MODEL_LABEL)
        text = response.choices[0].message.content or ""
        text = fix_encoding(text.strip())
        if not text:
            print("[WARN] product_integrated_insight: empty text — using heuristic fallback")
            return (_heuristic_fallback_report(product_name, truncated), HEURISTIC_MODEL_LABEL)
        print(f"[DEBUG] product_integrated_insight: report length={len(text)}")
        return (text, REPORT_LLM_DEPLOYMENT)
    except Exception as e:
        print(f"[ERROR] product_integrated_insight LLM call failed: {type(e).__name__}: {e}")
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
