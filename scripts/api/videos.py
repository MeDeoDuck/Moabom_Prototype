"""
Video-related API routes (video detail, PDF downloads)
"""
from datetime import datetime
from fastapi import HTTPException, Request
from fastapi.responses import HTMLResponse, Response
from fastapi.templating import Jinja2Templates
from scripts.database.queries import query_one, query_all, execute_update
from scripts.youtube.transcript_service import fetch_video_transcript
from scripts.reports.integrated_report import generate_and_save_all_reports
from scripts.reports.pdf_generator import render_report_pdf

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
        
        # Build WHERE clause for sentiment filter
        where_clause = "c.video_id = %s AND c.is_product_related = true"
        query_params = [video_id]
        
        if sentiment in ['positive', 'neutral', 'negative']:
            where_clause += " AND cs.sentiment_label = %s"
            query_params.append(sentiment)
            print(f"[FILTER] Applying sentiment filter: {sentiment}")
        else:
            print(f"[FILTER] No sentiment filter (sentiment={sentiment})")
        
        # Get product-related comments with sentiment (paginated, optionally filtered)
        comments = query_all(
            f"""SELECT c.comment_id, c.text_raw, cs.sentiment_label, cs.sentiment_score
               FROM comments c
               LEFT JOIN comment_sentiments cs ON c.comment_id = cs.comment_id
               WHERE {where_clause}
               ORDER BY c.created_at DESC LIMIT %s OFFSET %s""",
            tuple(query_params + [per_page, offset])
        )
        
        # Count total product-related comments (filtered)
        product_related_count = query_one(
            f"SELECT COUNT(*) as count FROM comments c LEFT JOIN comment_sentiments cs ON c.comment_id = cs.comment_id WHERE {where_clause}",
            tuple(query_params)
        )
        total_comments = product_related_count["count"] if product_related_count else 0
        total_pages = (total_comments + per_page - 1) // per_page
        
        # Count sentiment distribution
        sentiment_counts = query_all(
            """SELECT cs.sentiment_label, COUNT(*) as count
               FROM comments c
               LEFT JOIN comment_sentiments cs ON c.comment_id = cs.comment_id
               WHERE c.video_id = %s AND c.is_product_related = true
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
        transcript_report, comment_sentiment_report, integrated_analysis = generate_and_save_all_reports(
            video_id, product["name"], force_rewrite=False
        )
        
        # Get report metadata
        report_metadata = query_one(
            "SELECT updated_at FROM video_reports WHERE video_id = %s",
            (video_id,)
        )
        report_updated_at = report_metadata.get("updated_at") if report_metadata else None
        
        print(f"[VIDEO_DETAIL] Reports loaded: transcript={bool(transcript_report)}, comment={bool(comment_sentiment_report)}, integrated={bool(integrated_analysis)}, updated_at={report_updated_at}")
        
        return templates.TemplateResponse("video_detail.html", {
            "request": request,
            "product_id": product_id,
            "product": product,
            "video": video,
            "comments": comments,
            "product_related_count": total_comments,
            "current_page": page,
            "total_pages": total_pages,
            "per_page": per_page,
            "sentiment_positive": sentiment_map.get("positive", 0),
            "sentiment_neutral": sentiment_map.get("neutral", 0),
            "sentiment_negative": sentiment_map.get("negative", 0),
            "current_sentiment": sentiment,
            "transcript_row": transcript_row,
            "transcript_report": transcript_report,
            "comment_sentiment_report": comment_sentiment_report,
            "integrated_analysis": integrated_analysis,
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
        
        report_text = report_row["comment_report"]
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
        
        report_text = report_row["integrated_report"]
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
