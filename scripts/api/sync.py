"""
Sync API route - synchronize YouTube data for products
"""
from fastapi import HTTPException
from scripts.database.queries import query_one, query_all, execute_update, execute_insert
from scripts.database.connection import get_connection
from scripts.youtube.video_service import fetch_product_videos
from scripts.youtube.comment_service import fetch_video_comments


def register_sync_routes(app):
    """Register sync-related routes"""
    
    @app.post("/products/{product_id}/sync")
    async def sync_product_videos(product_id: int, data: dict = None):
        """Sync videos and comments from YouTube for a product."""
        print(f"[SYNC] START: product_id={product_id}")
        
        try:
            product = query_one("SELECT * FROM tech_products WHERE product_id = %s", (product_id,))
            print(f"[SYNC] Product query OK: {product}")
            
            if not product:
                raise HTTPException(status_code=404, detail="Product not found")
            
            max_results = (data or {}).get("max_results", 5)
            print(f"[SYNC] max_results={max_results}")
            
            # DELETE all existing data for this product (clean slate approach)
            execute_update(
                """DELETE FROM comment_sentiments
                   WHERE comment_id IN (
                     SELECT c.comment_id FROM comments c
                     INNER JOIN videos v ON c.video_id = v.video_id
                     WHERE v.product_id = %s
                   )""",
                (product_id,)
            )
            print(f"[SYNC] Deleted comment_sentiments")
            
            execute_update(
                """DELETE FROM comments
                   WHERE video_id IN (
                     SELECT video_id FROM videos WHERE product_id = %s
                   )""",
                (product_id,)
            )
            print(f"[SYNC] Deleted comments")
            
            execute_update(
                """DELETE FROM video_transcripts
                   WHERE video_id IN (
                     SELECT video_id FROM videos WHERE product_id = %s
                   )""",
                (product_id,)
            )
            print(f"[SYNC] Deleted video_transcripts")
            
            execute_update(
                """DELETE FROM video_reports
                   WHERE video_id IN (
                     SELECT video_id FROM videos WHERE product_id = %s
                   )""",
                (product_id,)
            )
            print(f"[SYNC] Deleted video_reports")
            
            execute_update(
                "DELETE FROM videos WHERE product_id = %s",
                (product_id,)
            )
            print(f"[SYNC] Deleted videos")
            
            # Fetch videos from YouTube
            print(f"[SYNC] Fetching videos for '{product['name']}'...")
            videos = fetch_product_videos(product["name"], max_results=5)
            print(f"[SYNC] Got {len(videos)} videos from YouTube")
            
            videos_count = 0
            comments_count = 0
            transcripts_count = 0
            
            for video in videos:
                print(f"[SYNC] Processing video: {video['video_id']}")
                
                # INSERT new video
                execute_update(
                    """INSERT INTO videos (video_id, product_id, title, description, published_at,
                       thumbnail_url, view_count, like_count, comment_count)
                       VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                    (video["video_id"], product_id, video["title"], video["description"],
                     video["published_at"], video["thumbnail_url"], video["view_count"],
                     video["like_count"], video["comment_count"])
                )
                videos_count += 1
                print(f"[SYNC]   Video inserted")
                
                # Fetch and process comments
                print(f"[SYNC]   Fetching comments...")
                comments = fetch_video_comments(video["video_id"], max_pages=2)
                print(f"[SYNC]   Got {len(comments)} comments")
                
                for comment in comments:
                    # Insert raw comment
                    execute_update(
                        """INSERT INTO comments (comment_id, video_id, text_raw, is_product_related)
                           VALUES (%s, %s, %s, %s)""",
                        (comment["comment_id"], video["video_id"], comment["text_raw"], True)
                    )
                    comments_count += 1
                    
                    # Analyze sentiment immediately during sync
                    comment_text = comment["text_raw"].lower()
                    positive_keywords = {
                        "좋다", "훌륭", "추천", "완벽", "최고", "멋진", "빠르다", "빠른", "강력", "강력한",
                        "좋은", "좋습니다", "훌륭합니다", "amazing", "great", "excellent", "awesome",
                        "best", "love", "perfect", "worth", "impressed", "beautiful", "fast", "powerful"
                    }
                    
                    negative_keywords = {
                        "나쁘다", "문제", "느리다", "느린", "비싸다", "비싼", "약하다", "약한", "못쓸",
                        "망했", "실망", "후회", "환불", "bad", "terrible", "poor", "awful", "slow",
                        "expensive", "waste", "regret", "disappointing", "broken", "fragile"
                    }
                    
                    pos_count = sum(1 for kw in positive_keywords if kw in comment_text)
                    neg_count = sum(1 for kw in negative_keywords if kw in comment_text)
                    
                    if pos_count > neg_count:
                        sentiment_label = "positive"
                        sentiment_score = 0.7
                    elif neg_count > pos_count:
                        sentiment_label = "negative"
                        sentiment_score = 0.3
                    else:
                        sentiment_label = "neutral"
                        sentiment_score = 0.5
                    
                    # Save sentiment to DB
                    try:
                        conn = get_connection()
                        cur = conn.cursor()
                        cur.execute("DELETE FROM comment_sentiments WHERE comment_id = %s", (comment["comment_id"],))
                        cur.execute("""
                            INSERT INTO comment_sentiments (comment_id, sentiment_label, sentiment_score, created_at)
                            VALUES (%s, %s, %s, NOW())
                        """, (comment["comment_id"], sentiment_label, sentiment_score))
                        conn.commit()
                        cur.close()
                        conn.close()
                    except Exception as e:
                        print(f"[SYNC] Warning: Could not save sentiment for {comment['comment_id']}: {e}")

                # Transcripts will be fetched on-demand when user views the video page
                print(f"[SYNC]   Skipping transcript (will fetch on-demand when viewing video)")
            
            print(f"[SYNC] COMPLETE: videos={videos_count}, comments={comments_count}, transcripts={transcripts_count}")
            return {
                "status": "success",
                "videos_count": videos_count,
                "comments_count": comments_count,
                "transcripts_count": transcripts_count,
            }
        except Exception as e:
            print(f"[SYNC] ERROR: {type(e).__name__}: {e}")
            import traceback
            traceback.print_exc()
            raise
