from __future__ import annotations

import os
from datetime import datetime, timedelta
from typing import Any

import psycopg2
from psycopg2.extras import DictCursor, execute_values
import httpx

from airflow.decorators import dag, task

DAG_ID = "youtube_product_sync_pipeline"
SEARCH_URL = "https://www.googleapis.com/youtube/v3/search"
VIDEOS_URL = "https://www.googleapis.com/youtube/v3/videos"
COMMENTS_URL = "https://www.googleapis.com/youtube/v3/commentThreads"

DEFAULT_DATABASE_URL = "postgresql://postgres:postgres@localhost:5432/techdb"


def _get_database_url() -> str:
    return os.getenv("DATABASE_URL", DEFAULT_DATABASE_URL)


def _get_youtube_api_key() -> str:
    return os.getenv("YOUTUBE_API_KEY", "")


def _connect():
    return psycopg2.connect(_get_database_url())


def _is_product_related(text: str, product_name: str = "") -> bool:
    text_lower = (text or "").lower()
    if product_name and product_name.lower() in text_lower:
        return True

    keywords = [
        "price", "spec", "battery", "performance", "quality", "feature",
        "design", "review", "recommend", "issue", "problem", "bug", "error",
        "upgrade", "worth", "value", "camera", "screen", "cpu", "gpu",
        "ram", "storage", "display", "build", "material",
    ]
    return any(keyword in text_lower for keyword in keywords)


def _analyze_sentiment(text: str) -> tuple[str, float]:
    text_lower = (text or "").lower()

    positive_words = [
        "good", "love", "great", "excellent", "amazing", "awesome",
        "best", "perfect", "fantastic", "wonderful", "brilliant",
        "recommend", "worth", "impressive", "beautiful", "smooth",
    ]
    negative_words = [
        "bad", "hate", "poor", "terrible", "awful", "horrible",
        "worst", "useless", "broken", "issue", "problem", "bug",
        "disappointing", "waste", "regret", "return",
    ]

    positive_count = sum(1 for word in positive_words if word in text_lower)
    negative_count = sum(1 for word in negative_words if word in text_lower)

    if positive_count > negative_count:
        return ("positive", 0.85)
    if negative_count > positive_count:
        return ("negative", 0.85)
    return ("neutral", 0.5)


def _fetch_product_videos(product_name: str, max_results: int) -> list[dict[str, Any]]:
    api_key = _get_youtube_api_key()
    if not api_key:
        raise RuntimeError("YOUTUBE_API_KEY is not configured")

    with httpx.Client(timeout=30.0) as client:
        search_resp = client.get(
            SEARCH_URL,
            params={
                "part": "snippet",
                "q": product_name,
                "type": "video",
                "maxResults": max_results,
                "key": api_key,
            },
        )
        search_resp.raise_for_status()
        search_data = search_resp.json()
        video_ids = [item["id"]["videoId"] for item in search_data.get("items", []) if item.get("id", {}).get("videoId")]

        if not video_ids:
            return []

        details_resp = client.get(
            VIDEOS_URL,
            params={
                "part": "snippet,statistics",
                "id": ",".join(video_ids),
                "key": api_key,
            },
        )
        details_resp.raise_for_status()
        details_data = details_resp.json()

    videos: list[dict[str, Any]] = []
    for item in details_data.get("items", []):
        snippet = item.get("snippet", {})
        stats = item.get("statistics", {})
        videos.append(
            {
                "video_id": item.get("id"),
                "title": snippet.get("title", ""),
                "description": snippet.get("description", ""),
                "published_at": snippet.get("publishedAt"),
                "thumbnail_url": snippet.get("thumbnails", {}).get("medium", {}).get("url"),
                "view_count": int(stats.get("viewCount", 0) or 0),
                "like_count": int(stats.get("likeCount", 0) or 0),
                "comment_count": int(stats.get("commentCount", 0) or 0),
            }
        )
    return videos


def _fetch_video_comments(video_id: str, max_pages: int) -> list[dict[str, str]]:
    api_key = _get_youtube_api_key()
    if not api_key:
        raise RuntimeError("YOUTUBE_API_KEY is not configured")

    results: list[dict[str, str]] = []
    next_page_token = None
    pages = 0

    with httpx.Client(timeout=30.0) as client:
        while pages < max_pages:
            params: dict[str, Any] = {
                "part": "snippet",
                "videoId": video_id,
                "maxResults": 100,
                "textFormat": "plainText",
                "key": api_key,
            }
            if next_page_token:
                params["pageToken"] = next_page_token

            resp = client.get(COMMENTS_URL, params=params)
            resp.raise_for_status()
            data = resp.json()

            for item in data.get("items", []):
                top_comment = item["snippet"]["topLevelComment"]
                top_comment_snippet = top_comment.get("snippet", {})
                results.append(
                    {
                        "comment_id": top_comment.get("id", ""),
                        "text_raw": top_comment_snippet.get("textDisplay", ""),
                    }
                )

            next_page_token = data.get("nextPageToken")
            if not next_page_token:
                break
            pages += 1

    return [c for c in results if c.get("comment_id")]


@dag(
    dag_id=DAG_ID,
    schedule="*/30 * * * *",
    start_date=datetime(2026, 1, 1),
    catchup=False,
    max_active_runs=1,
    default_args={
        "owner": "youtube-service",
        "retries": 2,
        "retry_delay": timedelta(minutes=2),
    },
    tags=["youtube", "etl", "sync"],
)
def youtube_product_sync_pipeline():
    @task
    def ensure_schema() -> None:
        with _connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS tech_products (
                        product_id   SERIAL PRIMARY KEY,
                        name         VARCHAR(255) NOT NULL,
                        brand        VARCHAR(255),
                        category     VARCHAR(255),
                        created_at   TIMESTAMP DEFAULT NOW()
                    );
                    """
                )
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS videos (
                        video_id      VARCHAR(64) PRIMARY KEY,
                        product_id    INT NOT NULL REFERENCES tech_products(product_id) ON DELETE CASCADE,
                        title         VARCHAR(255) NOT NULL,
                        description   TEXT,
                        published_at  TIMESTAMP,
                        thumbnail_url TEXT,
                        view_count    BIGINT,
                        like_count    BIGINT,
                        comment_count BIGINT,
                        created_at    TIMESTAMP DEFAULT NOW()
                    );
                    """
                )
                cur.execute("CREATE INDEX IF NOT EXISTS idx_videos_product ON videos(product_id);")
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS comments (
                        comment_id         VARCHAR(64) PRIMARY KEY,
                        video_id           VARCHAR(64) NOT NULL REFERENCES videos(video_id) ON DELETE CASCADE,
                        parent_id          VARCHAR(64),
                        text_raw           TEXT NOT NULL,
                        is_product_related BOOLEAN,
                        created_at         TIMESTAMP DEFAULT NOW()
                    );
                    """
                )
                cur.execute("CREATE INDEX IF NOT EXISTS idx_comments_video ON comments(video_id);")
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS comment_sentiments (
                        id               SERIAL PRIMARY KEY,
                        comment_id       VARCHAR(64) NOT NULL REFERENCES comments(comment_id) ON DELETE CASCADE,
                        sentiment_label  VARCHAR(16) NOT NULL,
                        sentiment_score  NUMERIC(4,3),
                        created_at       TIMESTAMP DEFAULT NOW()
                    );
                    """
                )
                cur.execute("CREATE INDEX IF NOT EXISTS idx_sentiments_comment ON comment_sentiments(comment_id);")

    @task
    def extract_products_to_sync(limit: int = 25) -> list[dict[str, Any]]:
        with _connect() as conn:
            with conn.cursor(cursor_factory=DictCursor) as cur:
                cur.execute(
                    """
                    SELECT product_id, name
                    FROM tech_products
                    ORDER BY created_at DESC
                    LIMIT %s
                    """,
                    (limit,),
                )
                return [dict(row) for row in cur.fetchall()]

    @task(retries=2, retry_delay=timedelta(minutes=2))
    def fetch_and_upsert_videos_for_product(
        product: dict[str, Any],
        max_results: int = 5,
    ) -> list[dict[str, Any]]:
        videos = _fetch_product_videos(product_name=product["name"], max_results=max_results)

        if not videos:
            return []

        with _connect() as conn:
            with conn.cursor() as cur:
                payload = [
                    (
                        video["video_id"],
                        product["product_id"],
                        video["title"],
                        video["description"],
                        video["published_at"],
                        video["thumbnail_url"],
                        video["view_count"],
                        video["like_count"],
                        video["comment_count"],
                    )
                    for video in videos
                    if video.get("video_id")
                ]

                if payload:
                    execute_values(
                        cur,
                        """
                        INSERT INTO videos (
                            video_id, product_id, title, description, published_at,
                            thumbnail_url, view_count, like_count, comment_count
                        ) VALUES %s
                        ON CONFLICT (video_id)
                        DO UPDATE SET
                            product_id = EXCLUDED.product_id,
                            title = EXCLUDED.title,
                            description = EXCLUDED.description,
                            published_at = EXCLUDED.published_at,
                            thumbnail_url = EXCLUDED.thumbnail_url,
                            view_count = EXCLUDED.view_count,
                            like_count = EXCLUDED.like_count,
                            comment_count = EXCLUDED.comment_count
                        """,
                        payload,
                    )

        return [
            {
                "video_id": video["video_id"],
                "product_id": product["product_id"],
                "product_name": product["name"],
            }
            for video in videos
            if video.get("video_id")
        ]

    @task
    def flatten_video_units(video_units_per_product: list[list[dict[str, Any]]]) -> list[dict[str, Any]]:
        flattened: list[dict[str, Any]] = []
        for units in video_units_per_product:
            flattened.extend(units)
        return flattened

    @task(retries=2, retry_delay=timedelta(minutes=1))
    def fetch_process_and_store_comments(
        video_unit: dict[str, Any],
        max_comment_pages: int = 2,
    ) -> dict[str, Any]:
        video_id = video_unit["video_id"]
        product_name = video_unit["product_name"]

        comments = _fetch_video_comments(video_id=video_id, max_pages=max_comment_pages)
        if not comments:
            return {
                "video_id": video_id,
                "fetched_comments": 0,
                "new_comments": 0,
                "related_comments": 0,
                "sentiment_rows": 0,
            }

        incoming_comment_ids = [comment["comment_id"] for comment in comments]

        with _connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT comment_id FROM comments WHERE video_id = %s AND comment_id = ANY(%s)",
                    (video_id, incoming_comment_ids),
                )
                existing_ids = {row[0] for row in cur.fetchall()}

                new_comments = [comment for comment in comments if comment["comment_id"] not in existing_ids]

                comment_rows = []
                sentiment_rows = []
                related_count = 0
                for comment in new_comments:
                    is_related = _is_product_related(comment["text_raw"], product_name)
                    if is_related:
                        related_count += 1

                    comment_rows.append(
                        (
                            comment["comment_id"],
                            video_id,
                            None,
                            comment["text_raw"],
                            is_related,
                        )
                    )

                    if is_related:
                        sentiment_label, sentiment_score = _analyze_sentiment(comment["text_raw"])
                        sentiment_rows.append(
                            (
                                comment["comment_id"],
                                sentiment_label,
                                sentiment_score,
                            )
                        )

                if comment_rows:
                    execute_values(
                        cur,
                        """
                        INSERT INTO comments (
                            comment_id, video_id, parent_id, text_raw, is_product_related
                        ) VALUES %s
                        ON CONFLICT (comment_id) DO NOTHING
                        """,
                        comment_rows,
                    )

                if sentiment_rows:
                    execute_values(
                        cur,
                        """
                        INSERT INTO comment_sentiments (
                            comment_id, sentiment_label, sentiment_score
                        ) VALUES %s
                        """,
                        sentiment_rows,
                    )

        return {
            "video_id": video_id,
            "fetched_comments": len(comments),
            "new_comments": len(new_comments),
            "related_comments": related_count,
            "sentiment_rows": len(sentiment_rows),
        }

    @task
    def publish_sync_report(
        products: list[dict[str, Any]],
        video_units: list[dict[str, Any]],
        comment_metrics: list[dict[str, Any]],
    ) -> dict[str, Any]:
        total_fetched_comments = sum(item["fetched_comments"] for item in comment_metrics)
        total_new_comments = sum(item["new_comments"] for item in comment_metrics)
        total_related_comments = sum(item["related_comments"] for item in comment_metrics)
        total_sentiments = sum(item["sentiment_rows"] for item in comment_metrics)

        report = {
            "products_scanned": len(products),
            "videos_processed": len(video_units),
            "comments_fetched": total_fetched_comments,
            "comments_inserted": total_new_comments,
            "related_comments": total_related_comments,
            "sentiment_rows_inserted": total_sentiments,
            "generated_at_utc": datetime.utcnow().isoformat(),
        }
        print(f"[DAG REPORT] {report}")
        return report

    schema_ready = ensure_schema()
    products = extract_products_to_sync()

    per_product_videos = fetch_and_upsert_videos_for_product.expand(product=products)
    video_units = flatten_video_units(per_product_videos)
    per_video_metrics = fetch_process_and_store_comments.expand(video_unit=video_units)
    report = publish_sync_report(products, video_units, per_video_metrics)

    schema_ready >> products
    report


dag_instance = youtube_product_sync_pipeline()
