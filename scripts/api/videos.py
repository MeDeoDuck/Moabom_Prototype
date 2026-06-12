"""
Video-related API routes (video detail)
"""
import json
from datetime import datetime
from typing import Any, Optional

from fastapi import HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from scripts.database.queries import query_one, query_all, execute_update
from scripts.youtube.transcript_service import fetch_video_transcript
from scripts.reports.integrated_report import generate_and_save_all_reports
from scripts.utils.markdown_renderer import markdown_to_html

templates = Jinja2Templates(directory="templates")



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
