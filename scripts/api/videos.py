"""
Video-related API routes (video detail, PDF downloads)
"""
import json
from datetime import datetime
from typing import Any, Optional

from fastapi import HTTPException, Request
from fastapi.responses import HTMLResponse, Response
from fastapi.templating import Jinja2Templates
from scripts.database.queries import query_one, query_all, execute_update
from scripts.youtube.transcript_service import fetch_video_transcript
from scripts.reports.integrated_report import generate_and_save_all_reports
from scripts.reports.pdf_generator import render_report_pdf
from scripts.utils.markdown_renderer import markdown_to_html

templates = Jinja2Templates(directory="templates")


# ─────────────────────────────────────────────────────────────────────────────
# v2 (보고서 ②③) JSON ↔ PDF/Plain-text 변환 헬퍼
# - DB 에 저장된 video_reports.comment_report / integrated_report 는 v2 부터 JSON.
# - PDF 다운로드 라우트가 ReportLab(render_report_pdf) 에 넘기려면 markdown-like
#   plain text 로 평탄화 필요. 본 함수가 그 변환을 담당.
# - v1 (마크다운) 캐시 row 가 남아 있을 수 있으므로 호출부에서 isinstance 분기.
# ─────────────────────────────────────────────────────────────────────────────

def _parse_report_json(raw: Any) -> Optional[dict]:
    """v2 JSON 문자열을 dict 로 안전 파싱. v1 마크다운/기타 입력은 None."""
    if not isinstance(raw, str):
        return None
    s = raw.strip()
    if not s or not s.startswith("{"):
        return None
    try:
        v = json.loads(s)
        return v if isinstance(v, dict) else None
    except (json.JSONDecodeError, TypeError):
        return None


def _fmt_quote_line(c: dict) -> list:
    """대표 댓글 1건 → PDF용 markdown 라인 (인용 + 좋아요/저자 메타)."""
    text = (c.get("text_raw") or "").strip()
    likes = c.get("like_count", 0)
    author = c.get("author_name") or ""
    meta = f"좋아요 {likes}"
    if author:
        meta += f", {author}"
    meta += " (원문 그대로)"
    return [f"> {text}", f"  - {meta}"]


def _comment_report_to_text(data: dict, product_name: str = "제품") -> str:
    """보고서 ② dict → PDF 용 markdown 텍스트."""
    out: list = [f"# {product_name} 댓글 기반 소비자 여론 보고서", ""]

    # S1
    s = data.get("sentiment_summary") or {}
    meta = data.get("_meta") or {}
    total = meta.get("total_analyzed_comments", 0)
    out.append("## 1. 소비자 민심 한눈에")
    if s.get("one_line_mood"):
        out.append(f"전반: {s['one_line_mood']}")
    out.append(f"- 긍정: {s.get('positive_pct', 0)}%")
    out.append(f"- 중립: {s.get('neutral_pct', 0)}%")
    out.append(f"- 부정: {s.get('negative_pct', 0)}%")
    out.append(f"(분석 대상 댓글 {total}건, 가중 비율)")
    out.append("")

    # S2/S3
    for title, key in (
        ("## 2. 긍정 핵심 인사이트", "positive_points"),
        ("## 3. 부정 핵심 인사이트", "negative_points"),
    ):
        out.append(title)
        pts = data.get(key) or []
        if not pts:
            out.append("- 도출된 포인트가 없습니다.")
        else:
            for p in pts:
                aspect = p.get("aspect_name") or ""
                cnt = p.get("comment_count", 0)
                summary = p.get("summary_line") or ""
                out.append(f"### {aspect} (관련 댓글 {cnt}건)")
                if summary:
                    out.append(summary)
                for c in (p.get("representative_comments") or []):
                    out.extend(_fmt_quote_line(c))
                out.append("")
        out.append("")

    # S4
    out.append("## 4. 주요 언급 이슈")
    issues = data.get("top_issues") or []
    if not issues:
        out.append("- 언급 이슈 데이터가 없습니다.")
    else:
        for it in issues:
            out.append(f"- {it.get('keyword', '')}: {it.get('count', 0)}회")
    return "\n".join(out)


# 보고서 ③ v2.2 메타 배지 라벨 (PDF 가독성용)
_PDF_TIER_LABEL = {"strict": "정확 매칭", "semantic": "의미 매칭", "text": "텍스트 비교"}
_PDF_STRENGTH_LABEL = {"strong": "근거 강함", "medium": "근거 보통", "weak": "근거 약함"}
_PDF_GAP_LABEL = {"opposite": "정반대", "temperature_gap": "온도차"}

# Option A: S2 가 빈 경우 LLM 이 안 채워도 항상 노출되는 FE/PDF default 메시지
_PDF_DEFAULT_DISAGREE_EMPTY = (
    "리뷰어와 소비자 의견이 대체로 일치합니다. 큰 갈등 지점이 발견되지 않았습니다."
)


def _comparison_report_to_text(data: dict, product_name: str = "제품") -> str:
    """보고서 ③ v2.2 dict → PDF 용 markdown 텍스트 (Option A: 빈 섹션 숨김).

    Option A:
      - S2 가 빈 경우: 항상 긍정 backup 메시지 (LLM 미준수 시 FE/PDF default 사용)
      - S4 spec_changes 가 빈 경우: 섹션 자체를 생성하지 않음 → footer 에 사유 노출
      - S5 consumer_questions 가 빈 경우: 동일
      - footer 에 "표시되지 않은 섹션" row 추가

    v2.1 dict (구버전 캐시) 도 누락 키 graceful — S4/S5 키가 없으면 빈 배열로 간주.
    """
    out: list = [f"# {product_name} 리뷰어 vs 소비자 비교 보고서", ""]

    # Option A: 빈 섹션을 footer 에 압축 노출하기 위한 트래킹
    hidden_sections: list = []

    # ── S1 / S2 일치·불일치 ──────────────────────────────────
    for title, key, is_disagree in (
        ("## 1. 의견 일치 포인트", "agreement_points", False),
        ("## 2. 의견 불일치 포인트", "disagreement_points", True),
    ):
        out.append(title)
        items = data.get(key) or []
        if not items:
            if is_disagree:
                # Option A: 항상 긍정 backup (LLM 미준수 시 default)
                fn = data.get("fallback_notes") or {}
                llm_msg = (fn.get("disagreement_empty_message") or "").strip()
                msg = llm_msg if llm_msg else _PDF_DEFAULT_DISAGREE_EMPTY
                out.append("> ✓ 리뷰어와 소비자 의견이 대체로 일치합니다")
                out.append(f"> {msg}")
            else:
                out.append("- 도출된 항목이 없습니다.")
        else:
            for p in items:
                topic = (p.get("topic") or "").strip()
                quote = (p.get("reviewer_quote") or "").strip()

                # 메타 배지: match_tier + evidence_strength (+ gap_type for disagree)
                meta_parts: list = []
                tier = p.get("match_tier")
                if tier:
                    meta_parts.append(_PDF_TIER_LABEL.get(tier, tier))
                strength = p.get("evidence_strength")
                if strength:
                    meta_parts.append(_PDF_STRENGTH_LABEL.get(strength, strength))
                if is_disagree:
                    gap = p.get("gap_type")
                    if gap:
                        meta_parts.append(_PDF_GAP_LABEL.get(gap, gap))
                meta_suffix = f"  [{' · '.join(meta_parts)}]" if meta_parts else ""

                out.append(f"### {topic}{meta_suffix}")
                out.append(f'- 리뷰어 자막: "{quote}"')
                out.append("- 소비자 댓글:")
                for c in (p.get("consumer_comments") or []):
                    out.extend(_fmt_quote_line(c))
                out.append("")
        out.append("")

    # ── S3 reviewer_only / consumer_only ─────────────────────
    out.append("## 3. 리뷰어만 언급 / 소비자만 언급")
    out.append("[리뷰어만 언급]")
    rev_only = data.get("reviewer_only") or []
    if rev_only:
        for t in rev_only:
            out.append(f"- {t}")
    else:
        out.append("- 없음")
    out.append("")
    out.append("[소비자만 언급]")
    cons_only = data.get("consumer_only") or []
    if cons_only:
        for t in cons_only:
            out.append(f"- {t}")
    else:
        out.append("- 없음")
    out.append("")

    # ── S4 핵심 스펙 변화 (Option A: 빈 시 섹션 숨김) ─────────
    specs = data.get("spec_changes") or []
    if specs:
        out.append("## 4. 핵심 스펙 변화")
        for s in specs:
            name = (s.get("spec_name") or "").strip()
            before = (s.get("before") or "").strip()
            after = (s.get("after") or "").strip()
            delta = (s.get("delta") or "").strip()
            line = f"- {name}: {before} → {after}"
            if delta:
                line += f" ({delta})"
            out.append(line)
        out.append("")
    else:
        hidden_sections.append(("S4", "핵심 스펙 변화", "자막에 전작 비교 표가 없음"))

    # ── S5 소비자 질문 (Option A: 빈 시 섹션 숨김) ───────────
    questions = data.get("consumer_questions") or []
    rendered_questions = 0
    if questions:
        out.append("## 5. 소비자가 가장 궁금해하는 질문")
        for q in questions:
            qc = q.get("question_comment") or {}
            q_text = (qc.get("text_raw") or "").strip()
            similar = q.get("similar_count", 1) or 1
            short = q.get("short_answer")
            short_str = (short or "").strip() if isinstance(short, str) else ""
            if not q_text:
                continue
            out.append(f"### Q. {q_text}  (유사 질문 {similar}건)")
            if short_str:
                out.append(f"> {short_str}")
            else:
                out.append("> 리뷰에서 다뤄지지 않음")
            out.append("")
            rendered_questions += 1
        if rendered_questions == 0:
            # question_comment.text_raw 가 모두 비어있던 edge case → 섹션 헤더만 노출됐으니
            # 빈 통지로 보완하고 footer 트래킹에도 추가
            out.append("- 댓글에서 추출된 질문 없음")
            out.append("")
            hidden_sections.append(("S5", "소비자 질문", "QUESTION 라벨 댓글 없음"))
    else:
        hidden_sections.append(("S5", "소비자 질문", "QUESTION 라벨 댓글 없음"))

    # ── S6 종합 판단 (기존 S4 이동 + 메타 확장) ──────────────
    out.append("## 6. 종합 판단")
    verdict = data.get("verdict") or {}
    meta = data.get("_meta") or {}
    out.append(f"리뷰 신뢰도: {verdict.get('trust_score', 0)}%")
    out.append("")
    summary = (verdict.get("summary") or "").strip()
    if summary:
        out.append(summary)
        out.append("")
    agree = meta.get("agreement_count", 0)
    dis = meta.get("disagreement_count", 0)
    spec_n = meta.get("spec_change_count", len(specs))
    q_n = meta.get("consumer_question_count", len(questions))
    out.append(
        f"(계산 근거: 일치 {agree}건 / 불일치 {dis}건 / "
        f"스펙 변화 {spec_n}건 / 소비자 질문 {q_n}건)"
    )

    # ── footer: data_scope + 표시되지 않은 섹션 (Option A) ────
    fn = data.get("fallback_notes") or {}
    data_scope = (fn.get("data_scope") or "").strip()
    if data_scope or hidden_sections:
        out.append("")
        out.append("---")
        if data_scope:
            out.append(f"데이터 범위: {data_scope}")
        if hidden_sections:
            items = " · ".join(
                f"{tag} {label} — {reason}" for tag, label, reason in hidden_sections
            )
            out.append(f"표시되지 않은 섹션: {items}")

    return "\n".join(out)


def register_video_routes(app):
    """Register all video-related routes"""
    
    @app.get("/products/{product_id}/videos/{video_id}", response_class=HTMLResponse)
    async def video_detail(request: Request, product_id: int, video_id: str, page: int = 1, sentiment: str = None):
        """Show video detail page with sentiment analysis and pagination."""
        print(f"[VIDEO_DETAIL] page={page}, sentiment={sentiment}")
        
        product = query_one("SELECT * FROM tech_products WHERE product_id = %s", (product_id,))
        
        if not product:
            raise HTTPException(status_code=404, detail="Product not found")
        
        video = query_one(
            "SELECT * FROM videos WHERE video_id = %s AND product_id = %s",
            (video_id, product_id)
        )
        
        if not video:
            raise HTTPException(status_code=404, detail="Video not found")
        
        # Pagination params
        page = max(1, page)
        per_page = 10
        offset = (page - 1) * per_page
        
        # Build WHERE clause for final analyzed comments
        # (LLM+Agent final_action=ANALYZE and sentiment already computed)
        where_clause = "c.video_id = %s AND ad.final_action = 'ANALYZE'"
        query_params = [video_id]
        
        if sentiment in ['positive', 'neutral', 'negative']:
            where_clause += " AND cs.sentiment_label = %s"
            query_params.append(sentiment)
            print(f"[FILTER] Applying sentiment filter: {sentiment}")
        else:
            print(f"[FILTER] No sentiment filter (sentiment={sentiment})")
        
        # Get final analyzed comments with sentiment (paginated, optionally filtered)
        comments = query_all(
            f"""SELECT c.comment_id, c.text_raw, cs.sentiment_label, cs.sentiment_score
                FROM comments c
               INNER JOIN agent_decisions ad ON c.comment_id = ad.comment_id
               INNER JOIN comment_sentiments cs ON c.comment_id = cs.comment_id
               WHERE {where_clause}
                ORDER BY c.created_at DESC LIMIT %s OFFSET %s""",
            tuple(query_params + [per_page, offset])
        )
        
        # Count total final analyzed comments (filtered)
        analyzed_count_row = query_one(
            f"""SELECT COUNT(*) as count
                FROM comments c
                INNER JOIN agent_decisions ad ON c.comment_id = ad.comment_id
                INNER JOIN comment_sentiments cs ON c.comment_id = cs.comment_id
                WHERE {where_clause}""",
            tuple(query_params)
        )
        total_comments = analyzed_count_row["count"] if analyzed_count_row else 0
        total_pages = (total_comments + per_page - 1) // per_page
        
        # Count sentiment distribution
        sentiment_counts = query_all(
            """SELECT cs.sentiment_label, COUNT(*) as count
               FROM comments c
               INNER JOIN agent_decisions ad ON c.comment_id = ad.comment_id
               INNER JOIN comment_sentiments cs ON c.comment_id = cs.comment_id
               WHERE c.video_id = %s AND ad.final_action = 'ANALYZE'
               GROUP BY cs.sentiment_label""",
            (video_id,)
        )
        
        sentiment_map = {row["sentiment_label"]: row["count"] for row in sentiment_counts}

        transcript_row = query_one(
            "SELECT transcript_text, language_code, segment_count, updated_at FROM video_transcripts WHERE video_id = %s",
            (video_id,),
        )

        # Auto-recover missing transcript once at page load
        if not transcript_row:
            fetched_transcript = fetch_video_transcript(video_id)
            if fetched_transcript:
                execute_update(
                    """INSERT INTO video_transcripts (video_id, transcript_text, language_code, segment_count, source)
                       VALUES (%s, %s, %s, %s, %s)
                       ON CONFLICT (video_id)
                       DO UPDATE SET
                         transcript_text = EXCLUDED.transcript_text,
                         language_code = EXCLUDED.language_code,
                         segment_count = EXCLUDED.segment_count,
                         source = EXCLUDED.source,
                         updated_at = NOW()""",
                    (
                        video_id,
                        fetched_transcript["transcript_text"],
                        fetched_transcript["language_code"],
                        fetched_transcript["segment_count"],
                        "youtube_transcript_api",
                    ),
                )
                transcript_row = query_one(
                    "SELECT transcript_text, language_code, segment_count, updated_at FROM video_transcripts WHERE video_id = %s",
                    (video_id,),
                )

        # Load cached reports if available
        print(f"[VIDEO_DETAIL] Loading video page: product_id={product_id}, video_id={video_id}")
        transcript_report, comment_sentiment_report, integrated_analysis = await generate_and_save_all_reports(
            video_id, product["name"], force_rewrite=False
        )
        
        # 보고서 ① (자막) → 마크다운 HTML 변환 (기존 .tr-* enhancer 가 DOM 위에서 동작)
        # 보고서 ②③ (댓글/비교) → dict 그대로 템플릿에 전달.
        #   템플릿이 {{ var|tojson }} 으로 <script type="application/json"> 에 직렬화하면
        #   JS enhancer (.cm-* / .cmp-*) 가 안전하게 JSON.parse 후 렌더한다.
        transcript_report_html = markdown_to_html(transcript_report) if isinstance(transcript_report, str) else None
        comment_report_json = comment_sentiment_report if isinstance(comment_sentiment_report, dict) else None
        integrated_report_json = integrated_analysis if isinstance(integrated_analysis, dict) else None

        # Get report metadata
        report_metadata = query_one(
            "SELECT updated_at FROM video_reports WHERE video_id = %s",
            (video_id,)
        )
        report_updated_at = report_metadata.get("updated_at") if report_metadata else None

        print(
            f"[VIDEO_DETAIL] Reports loaded: transcript={bool(transcript_report)}, "
            f"comment={bool(comment_report_json)}, integrated={bool(integrated_report_json)}, "
            f"updated_at={report_updated_at}"
        )

        return templates.TemplateResponse("video_detail.html", {
            "request": request,
            "product_id": product_id,
            "product": product,
            "video": video,
            "comments": comments,
            "product_related_count": total_comments,
            "analyzed_comment_count": total_comments,
            "current_page": page,
            "total_pages": total_pages,
            "per_page": per_page,
            "sentiment_positive": sentiment_map.get("positive", 0),
            "sentiment_neutral": sentiment_map.get("neutral", 0),
            "sentiment_negative": sentiment_map.get("negative", 0),
            "current_sentiment": sentiment,
            "transcript_row": transcript_row,
            "transcript_report": transcript_report_html,
            "comment_report_json": comment_report_json,
            "integrated_report_json": integrated_report_json,
            "report_updated_at": report_updated_at,
        })
    
    @app.get("/products/{product_id}/videos/{video_id}/transcript-report.pdf")
    async def download_transcript_report(product_id: int, video_id: str):
        """Download transcript report as PDF."""
        video = query_one(
            "SELECT * FROM videos WHERE video_id = %s AND product_id = %s",
            (video_id, product_id),
        )
        if not video:
            raise HTTPException(status_code=404, detail="Video not found")

        report_row = query_one(
            "SELECT transcript_report FROM video_reports WHERE video_id = %s",
            (video_id,),
        )
        
        if not report_row or not report_row.get("transcript_report"):
            raise HTTPException(status_code=404, detail="Transcript report not available")
        
        report_text = report_row["transcript_report"]
        pdf_bytes = render_report_pdf(f"[자막 기반 분석] {video.get('title', 'Unknown')}", report_text)

        filename = f"transcript_report_{video_id}.pdf"
        return Response(
            content=pdf_bytes,
            media_type="application/pdf",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )
    
    @app.get("/products/{product_id}/videos/{video_id}/comment-report.pdf")
    async def download_comment_report(product_id: int, video_id: str):
        """Download comment sentiment report as PDF."""
        product = query_one("SELECT * FROM tech_products WHERE product_id = %s", (product_id,))
        if not product:
            raise HTTPException(status_code=404, detail="Product not found")
        
        video = query_one(
            "SELECT * FROM videos WHERE video_id = %s AND product_id = %s",
            (video_id, product_id),
        )
        if not video:
            raise HTTPException(status_code=404, detail="Video not found")

        report_row = query_one(
            "SELECT comment_report FROM video_reports WHERE video_id = %s",
            (video_id,),
        )

        if not report_row or not report_row.get("comment_report"):
            raise HTTPException(status_code=404, detail="Comment report not available")

        raw = report_row["comment_report"]
        data = _parse_report_json(raw)
        if isinstance(data, dict):
            report_text = _comment_report_to_text(data, product["name"])
        else:
            # v1 (legacy markdown) 호환: 원문 그대로 PDF 화
            report_text = raw if isinstance(raw, str) else ""
        pdf_bytes = render_report_pdf(f"[댓글 분석] {video.get('title', 'Unknown')}", report_text)

        filename = f"comment_report_{video_id}.pdf"
        return Response(
            content=pdf_bytes,
            media_type="application/pdf",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )
    
    @app.get("/products/{product_id}/videos/{video_id}/integrated-analysis.pdf")
    async def download_integrated_analysis(product_id: int, video_id: str):
        """Download integrated analysis as PDF."""
        product = query_one("SELECT * FROM tech_products WHERE product_id = %s", (product_id,))
        if not product:
            raise HTTPException(status_code=404, detail="Product not found")
        
        video = query_one(
            "SELECT * FROM videos WHERE video_id = %s AND product_id = %s",
            (video_id, product_id),
        )
        if not video:
            raise HTTPException(status_code=404, detail="Video not found")

        report_row = query_one(
            "SELECT integrated_report FROM video_reports WHERE video_id = %s",
            (video_id,),
        )

        if not report_row or not report_row.get("integrated_report"):
            raise HTTPException(status_code=404, detail="Integrated analysis not available")

        raw = report_row["integrated_report"]
        data = _parse_report_json(raw)
        if isinstance(data, dict):
            report_text = _comparison_report_to_text(data, product["name"])
        else:
            report_text = raw if isinstance(raw, str) else ""
        pdf_bytes = render_report_pdf(f"[통합 분석] {video.get('title', 'Unknown')}", report_text)

        filename = f"integrated_analysis_{video_id}.pdf"
        return Response(
            content=pdf_bytes,
            media_type="application/pdf",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )
    
    @app.get("/api/ai-analysis-status")
    async def get_ai_analysis_status():
        """Get status of AI analysis tasks (Airflow integration placeholder)."""
        ai_tasks = {
            "comment_filter_batch": {
                "status": "active",
                "description": "Filter comments by product relevance",
            },
            "summarize_transcripts_batch": {
                "status": "active",
                "description": "Generate transcript summaries with AI",
            },
            "generate_product_report_batch": {
                "status": "active",
                "description": "Create comprehensive product analysis reports",
            },
        }
        
        return {
            "timestamp": datetime.utcnow().isoformat(),
            "ai_tasks": ai_tasks,
            "total_tasks": len(ai_tasks),
            "all_active": all(t["status"] == "active" for t in ai_tasks.values()),
        }
