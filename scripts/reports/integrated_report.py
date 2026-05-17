"""
보고서 ③ — 리뷰어(자막) vs 소비자(댓글) 비교 보고서.

⚠️ 저장 형식 변경:
  video_reports.integrated_report 는 v1 까지 마크다운 TEXT 였으나,
  이번 디벨롭(v2) 부터는 JSON 문자열로 저장한다.
  - 응답 dict 스키마: build_comparison_report_prompt docstring 참조
  - 환각 차단: LLM 은 consumer_comment_ids 만 지목, 원문은 백엔드가 첨부
  - reviewer_quote 는 입력 transcript_report_md 발췌만 허용

공개 함수:
  build_integrated_analysis_report(video_id, product_name, transcript_report, comment_report)
      → Optional[dict]
  generate_and_save_all_reports(video_id, product_name, force_rewrite)
      → (Optional[str transcript_md], Optional[dict comment], Optional[dict integrated])
  upsert_video_report(video_id, transcript_report=None, comment_report=None, integrated_report=None)
      dict 가 들어오면 JSON 문자열로 직렬화하여 저장.
"""
from __future__ import annotations

import asyncio
import json
from typing import Any, Dict, Optional, Tuple

from scripts.reports._comment_aggregator import (
    aggregate_comparison_inputs,
    attach_comment_texts,
    fetch_comment_texts,
    validate_report3_json,
)
from scripts.reports.transcript_report import (
    REPORT_LLM_DEPLOYMENT,
    fix_encoding,
    get_report_llm_client,
)
from scripts.utils.prompt_manager import build_comparison_report_prompt


SCHEMA_VERSION = "v2.integrated_report.2"
MAX_LLM_ATTEMPTS = 3


# ── 보고서 ③ 본체 ─────────────────────────────────────────────

def build_integrated_analysis_report(
    video_id: str,
    product_name: str,
    transcript_report: Optional[str],
    comment_report: Optional[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    """
    리뷰어 vs 소비자 비교 보고서 (영상 1개 단위).

    인자:
      transcript_report: 보고서 ①의 마크다운 본문. None 이면 ③ 생성 불가.
      comment_report:    보고서 ② 의 dict (v2 스키마). None 이면 ③ 생성 불가.
                         하위호환: 문자열(이전 마크다운 형식)이 들어오면 ③ 생성 불가.

    반환: dict (스키마: build_comparison_report_prompt docstring + _meta) 또는 None.
    """
    if not transcript_report or not comment_report:
        print(
            f"[integrated_report] missing inputs "
            f"(transcript={bool(transcript_report)}, comment={bool(comment_report)})"
        )
        return None
    if not isinstance(comment_report, dict):
        print(
            "[integrated_report] comment_report must be dict (v2). "
            "Legacy markdown comment_report is not supported in v2 → skip."
        )
        return None

    aspect_summary = aggregate_comparison_inputs(video_id, product_name, transcript_report)
    if not aspect_summary or not aspect_summary.get("all_consumer_aspects"):
        # v2.2: ABSA aspect 자체가 0 개면 비교 가치가 없음 → ③ 생성 보류
        # (strict 매칭이 0 이어도 semantic/text fallback 으로 ③ 생성 가능. 단 ABSA 0 이면 빈손)
        print(
            f"[integrated_report] no ABSA aspects for video_id={video_id} "
            "→ comparison report skipped"
        )
        return None

    try:
        client = get_report_llm_client()
    except ValueError as e:
        print(f"[ERROR] integrated_report: LLM client unavailable: {e}")
        return None

    prompt = build_comparison_report_prompt(
        transcript_report_md=transcript_report,
        comment_report_json=_strip_meta(comment_report),
        aspect_summary=aspect_summary,
    )

    for attempt in range(1, MAX_LLM_ATTEMPTS + 1):
        try:
            response = client.chat.completions.create(
                model=REPORT_LLM_DEPLOYMENT,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.2,
                max_tokens=2200,
                response_format={"type": "json_object"},
            )
        except Exception as e:
            print(
                f"[ERROR] integrated_report: LLM call failed "
                f"(attempt {attempt}/{MAX_LLM_ATTEMPTS}): {type(e).__name__}: {e}"
            )
            continue

        raw = (response.choices[0].message.content if response.choices else "") or ""
        raw = fix_encoding(raw.strip())

        try:
            data = json.loads(raw)
        except json.JSONDecodeError as e:
            print(
                f"[WARN] integrated_report: JSON parse failed "
                f"(attempt {attempt}/{MAX_LLM_ATTEMPTS}): {e}"
            )
            continue

        if not validate_report3_json(data):
            print(
                f"[WARN] integrated_report: JSON schema invalid "
                f"(attempt {attempt}/{MAX_LLM_ATTEMPTS})"
            )
            continue

        # 환각 차단 (v2.2): consumer_comment_ids / reviewer_only / consumer_only /
        # spec_changes / consumer_questions 모두 화이트리스트
        data = _filter_ids_and_lists(data, aspect_summary)

        # 원문 첨부 #1: consumer_comment_ids → consumer_comments
        data = attach_comment_texts(
            data,
            id_paths=[
                ("agreement_points",    "consumer_comment_ids", "consumer_comments"),
                ("disagreement_points", "consumer_comment_ids", "consumer_comments"),
            ],
        )

        # 원문 첨부 #2: consumer_questions[i].question_text_id → question_comment (단일 dict)
        _attach_question_texts(data)

        agree = len(data.get("agreement_points", []))
        disagree = len(data.get("disagreement_points", []))
        data["_meta"] = {
            "video_id": video_id,
            "product_name": product_name,
            "agreement_count": agree,
            "disagreement_count": disagree,
            "spec_change_count": len(data.get("spec_changes", [])),
            "consumer_question_count": len(data.get("consumer_questions", [])),
            "model_used": REPORT_LLM_DEPLOYMENT,
            "schema_version": SCHEMA_VERSION,
        }
        return data

    print(f"[ERROR] integrated_report: failed after {MAX_LLM_ATTEMPTS} attempts (video_id={video_id})")
    return None


def _strip_meta(data: Dict[str, Any]) -> Dict[str, Any]:
    """프롬프트에 넘기기 전 _meta 키 제거 (LLM 에 메타가 echo 되는 것 방지)."""
    return {k: v for k, v in (data or {}).items() if k != "_meta"}


def _filter_ids_and_lists(
    data: Dict[str, Any],
    aspect_summary: Dict[str, Any],
) -> Dict[str, Any]:
    """
    v2.2 화이트리스트 강제 (LLM 출력 후처리):

      - agreement / disagreement.consumer_comment_ids
          → 해당 topic 의 candidate_comments 에 등장한 ID 만 허용 (각 2 개 상한)
          → match_tier="text" 면 topic 이 aspect_name 이 아닐 수 있으므로
             모든 candidate_comments 의 합집합으로 fallback
      - reviewer_only → reviewer_only_aspect_hints 안에서만 (6 개 상한)
      - consumer_only → all_consumer_aspects.aspect_name 중 agree/disagree 양쪽에서
                        채택되지 않은 항목만 (6 개 상한)
      - spec_changes  → spec_change_candidates 의 spec_name 화이트리스트.
                        매칭되는 항목은 입력값 그대로 (before/after/change_text→delta)
                        로 재구성해 LLM 수치 변조 차단 (5 개 상한)
      - consumer_questions.question_text_id
                      → question_candidates 의 comment_id 만 허용 (8 개 상한)
    """
    # aspect_name → candidate_id 집합
    aspect_to_white: Dict[str, set] = {}
    for grp in aspect_summary.get("all_consumer_aspects", []):
        aspect_to_white[grp["aspect_name"]] = {
            c["comment_id"] for c in grp.get("candidate_comments", [])
        }
    all_ids_union: set = set().union(*aspect_to_white.values()) if aspect_to_white else set()

    used_topics: set = set()
    for grp_key in ("agreement_points", "disagreement_points"):
        for item in data.get(grp_key, []):
            topic = (item.get("topic") or "").strip()
            used_topics.add(topic)
            white = aspect_to_white.get(topic, set())
            if not white and item.get("match_tier") == "text":
                # tier 3: topic 이 ABSA aspect 외 자유 문구 → 모든 ID 허용
                white = all_ids_union
            ids = item.get("consumer_comment_ids") or []
            item["consumer_comment_ids"] = [i for i in ids if i in white][:2]

    # reviewer_only
    rev_white = set(aspect_summary.get("reviewer_only_aspect_hints", []))
    data["reviewer_only"] = [
        s for s in (data.get("reviewer_only") or []) if s in rev_white
    ][:6]

    # consumer_only — all_consumer_aspects 중 S1/S2 미사용 항목
    all_aspect_names = {a["aspect_name"] for a in aspect_summary.get("all_consumer_aspects", [])}
    data["consumer_only"] = [
        s for s in (data.get("consumer_only") or [])
        if s in all_aspect_names and s not in used_topics
    ][:6]

    # spec_changes — spec_name 기준 화이트리스트 + 입력값으로 강제 재구성
    spec_input = aspect_summary.get("spec_change_candidates", [])
    spec_dict = {s.get("spec_name", ""): s for s in spec_input}
    filtered_specs: List[Dict[str, str]] = []
    for s in (data.get("spec_changes") or []):
        name = (s.get("spec_name") or "").strip()
        if name in spec_dict:
            original = spec_dict[name]
            filtered_specs.append({
                "spec_name": original.get("spec_name", ""),
                "before":    original.get("before", ""),
                "after":     original.get("after", ""),
                "delta":     original.get("change_text", ""),
            })
    data["spec_changes"] = filtered_specs[:5]

    # consumer_questions — question_text_id 화이트리스트
    question_white = {q["comment_id"] for q in aspect_summary.get("question_candidates", [])}
    filtered_questions: List[Dict[str, Any]] = []
    for q in (data.get("consumer_questions") or []):
        qid = q.get("question_text_id")
        if qid and qid in question_white:
            filtered_questions.append(q)
    data["consumer_questions"] = filtered_questions[:8]

    # fallback_notes 누락/문자열 정합화
    fn = data.get("fallback_notes")
    if not isinstance(fn, dict):
        data["fallback_notes"] = {"disagreement_empty_message": None, "data_scope": ""}
    else:
        if "disagreement_empty_message" not in fn:
            fn["disagreement_empty_message"] = None
        if "data_scope" not in fn:
            fn["data_scope"] = ""

    return data


def _attach_question_texts(data: Dict[str, Any]) -> None:
    """consumer_questions 의 question_text_id 마다 comments.text_raw 원문을 매핑.

    fetch_comment_texts 는 list 기반 → 단일 ID 케이스를 위해 별도 inline 처리.
    각 question 에 question_comment={comment_id, text_raw, like_count, author_name}
    필드를 in-place 추가. 매핑 실패하면 None.
    """
    questions = data.get("consumer_questions") or []
    qids = [q["question_text_id"] for q in questions if q.get("question_text_id")]
    if not qids:
        return
    text_map = fetch_comment_texts(qids)
    for q in questions:
        qid = q.get("question_text_id")
        if qid in text_map:
            q["question_comment"] = {"comment_id": qid, **text_map[qid]}
        else:
            q["question_comment"] = None


# ── 통합 오케스트레이션 (videos.py 가 호출) ───────────────────

async def generate_and_save_all_reports(
    video_id: str,
    product_name: str,
    force_rewrite: bool = False,
) -> Tuple[Optional[str], Optional[Dict[str, Any]], Optional[Dict[str, Any]]]:
    """
    영상 1개에 대해 ①(transcript md), ②(dict), ③(dict) 을 모두 생성·저장.

    ⚠️ 시그니처는 v1 과 동일하나 반환 타입이 (str, dict, dict) 로 변경됨 (v2).
    Stage 4 에서 videos.py 라우트가 새 dict 타입을 템플릿에 전달하도록 적응.
    """
    from scripts.database.queries import query_one
    from scripts.reports.comment_report import build_comment_sentiment_report
    from scripts.reports.transcript_report import build_transcript_report

    print(
        f"[REPORT] START: video_id={video_id}, product={product_name}, "
        f"force_rewrite={force_rewrite}"
    )

    # 1) 캐시 hit 체크 (3종 모두 있고 ②③ 가 v2 JSON 형식일 때만 사용)
    if not force_rewrite:
        cached = query_one(
            """SELECT transcript_report, comment_report, integrated_report, updated_at
               FROM video_reports WHERE video_id = %s""",
            (video_id,),
        )
        if (
            cached
            and cached.get("transcript_report")
            and cached.get("comment_report")
            and cached.get("integrated_report")
        ):
            cm = _safe_json_loads(cached.get("comment_report"))
            it = _safe_json_loads(cached.get("integrated_report"))
            if cm and it:
                print(f"[REPORT] cache hit (v2 JSON, updated_at={cached.get('updated_at')})")
                return cached.get("transcript_report"), cm, it
            print("[REPORT] cached comment/integrated are legacy markdown → regenerate v2")

    # 2) transcript 조회
    transcript_row = query_one(
        "SELECT transcript_text FROM video_transcripts WHERE video_id = %s",
        (video_id,),
    )
    if not transcript_row:
        print(f"[REPORT] no transcript row for {video_id} → all reports None")
        return None, None, None

    video_meta = query_one("SELECT title FROM videos WHERE video_id = %s", (video_id,))
    video_title = (video_meta or {}).get("title", "") or ""

    # 3) ① + ② 병렬 생성 (각각 to_thread)
    print("[REPORT] generating transcript + comment reports in parallel...")
    transcript_task = asyncio.to_thread(
        build_transcript_report, transcript_row["transcript_text"]
    )
    comment_task = asyncio.to_thread(
        build_comment_sentiment_report, video_id, product_name, video_title
    )
    transcript_result, comment_result = await asyncio.gather(
        transcript_task, comment_task, return_exceptions=True
    )

    if isinstance(transcript_result, Exception):
        print(
            f"[REPORT] transcript task failed: "
            f"{type(transcript_result).__name__}: {transcript_result}"
        )
        transcript_report: Optional[str] = None
    else:
        transcript_report = transcript_result
        if isinstance(transcript_report, str) and transcript_report.startswith("[ERROR]"):
            transcript_report = None

    if isinstance(comment_result, Exception):
        print(
            f"[REPORT] comment task failed: "
            f"{type(comment_result).__name__}: {comment_result}"
        )
        comment_report: Optional[Dict[str, Any]] = None
    else:
        comment_report = comment_result if isinstance(comment_result, dict) else None

    # 4) ③ 생성 (① + ② 둘 다 있을 때만)
    integrated_report: Optional[Dict[str, Any]] = None
    if transcript_report and comment_report:
        print("[REPORT] generating integrated (comparison) report...")
        integrated_report = await asyncio.to_thread(
            build_integrated_analysis_report,
            video_id,
            product_name,
            transcript_report,
            comment_report,
        )
    else:
        print(
            "[REPORT] skip integrated "
            f"(transcript={bool(transcript_report)}, comment={bool(comment_report)})"
        )

    # 5) DB 저장
    await asyncio.to_thread(
        upsert_video_report,
        video_id,
        transcript_report,
        comment_report,
        integrated_report,
    )
    print(
        "[REPORT] COMPLETE: "
        f"transcript={bool(transcript_report)}, "
        f"comment={bool(comment_report)}, "
        f"integrated={bool(integrated_report)}"
    )
    return transcript_report, comment_report, integrated_report


def upsert_video_report(
    video_id: str,
    transcript_report: Optional[str] = None,
    comment_report: Optional[Any] = None,
    integrated_report: Optional[Any] = None,
) -> None:
    """video_reports UPSERT. comment / integrated 가 dict 면 JSON 직렬화.

    ⚠️ v1 호환:
      - product_integrated_insight.py 는 transcript_report 만 지정해서 호출한다.
        이때 comment_report/integrated_report 가 None 이면 기존 컬럼이 NULL 로
        덮어쓰여진다 — 이는 v1 부터의 기존 거동이며 본 디벨롭에서 변경하지 않는다.
    """
    from scripts.database.queries import execute_update

    cm_text = (
        json.dumps(comment_report, ensure_ascii=False)
        if isinstance(comment_report, dict)
        else comment_report
    )
    it_text = (
        json.dumps(integrated_report, ensure_ascii=False)
        if isinstance(integrated_report, dict)
        else integrated_report
    )
    execute_update(
        """INSERT INTO video_reports
              (video_id, transcript_report, comment_report, integrated_report, updated_at)
           VALUES (%s, %s, %s, %s, NOW())
           ON CONFLICT (video_id)
           DO UPDATE SET
             transcript_report = EXCLUDED.transcript_report,
             comment_report    = EXCLUDED.comment_report,
             integrated_report = EXCLUDED.integrated_report,
             updated_at        = NOW()""",
        (video_id, transcript_report, cm_text, it_text),
    )


def _safe_json_loads(s: Any) -> Optional[Dict[str, Any]]:
    """JSON 문자열을 dict 로 안전 파싱. v1 마크다운 캐시는 None 반환."""
    if not isinstance(s, str):
        return None
    s = s.strip()
    if not s or not s.startswith("{"):
        return None
    try:
        v = json.loads(s)
        return v if isinstance(v, dict) else None
    except (json.JSONDecodeError, TypeError):
        return None
