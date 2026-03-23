import json
from datetime import datetime
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import urlopen

from fastapi import HTTPException

from app.config import Settings
from app.models import Product, Video
from app.repositories import ProductRepository, VideoRepository

SEARCH_URL = "https://www.googleapis.com/youtube/v3/search"
VIDEOS_URL = "https://www.googleapis.com/youtube/v3/videos"


class YouTubeClient:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    @staticmethod
    def _parse_published_at(value: str | None) -> datetime | None:
        if not value:
            return None
        return datetime.fromisoformat(value.replace("Z", "+00:00"))

    @staticmethod
    def _get_json(base_url: str, params: dict[str, Any]) -> dict[str, Any]:
        url = f"{base_url}?{urlencode(params)}"
        try:
            with urlopen(url) as response:
                return json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            details = exc.read().decode("utf-8", errors="ignore")
            raise HTTPException(status_code=502, detail=f"YouTube API HTTP error: {details or exc.reason}") from exc
        except URLError as exc:
            raise HTTPException(status_code=502, detail=f"YouTube API connection error: {exc.reason}") from exc

    def fetch_product_videos(self, product_name: str, max_results: int = 5) -> list[Video]:
        if not self.settings.youtube_api_key:
            raise HTTPException(status_code=500, detail="YOUTUBE_API_KEY is not configured")

        search_payload = self._get_json(
            SEARCH_URL,
            {
                "part": "snippet",
                "q": product_name,
                "type": "video",
                "maxResults": max_results,
                "key": self.settings.youtube_api_key,
            },
        )
        video_ids = [
            item.get("id", {}).get("videoId")
            for item in search_payload.get("items", [])
            if item.get("id", {}).get("videoId")
        ]
        if not video_ids:
            return []

        details_payload = self._get_json(
            VIDEOS_URL,
            {
                "part": "snippet,statistics",
                "id": ",".join(video_ids),
                "key": self.settings.youtube_api_key,
            },
        )

        videos: list[Video] = []
        for item in details_payload.get("items", []):
            snippet = item.get("snippet", {})
            statistics = item.get("statistics", {})
            thumbnails = snippet.get("thumbnails", {})
            best_thumbnail = thumbnails.get("high") or thumbnails.get("medium") or thumbnails.get("default") or {}
            videos.append(
                Video(
                    video_id=item.get("id"),
                    product_id=0,
                    title=snippet.get("title", "Untitled video"),
                    description=snippet.get("description"),
                    published_at=self._parse_published_at(snippet.get("publishedAt")),
                    thumbnail_url=best_thumbnail.get("url"),
                    view_count=int(statistics.get("viewCount", 0) or 0),
                    like_count=int(statistics.get("likeCount", 0) or 0),
                    comment_count=int(statistics.get("commentCount", 0) or 0),
                )
            )
        return videos


class ProductVideoService:
    def __init__(
        self,
        product_repository: ProductRepository,
        video_repository: VideoRepository,
        youtube_client: YouTubeClient,
    ) -> None:
        self.product_repository = product_repository
        self.video_repository = video_repository
        self.youtube_client = youtube_client

    def create_product(self, name: str, brand: str | None) -> Product:
        return self.product_repository.create(name=name, brand=brand)

    def list_products(self) -> list[Product]:
        return self.product_repository.list_all()

    def get_product(self, product_id: int) -> Product:
        return self.product_repository.get_or_404(product_id)

    def list_product_videos(self, product_id: int) -> list[Video]:
        return self.video_repository.list_by_product(product_id)

    def sync_product_videos(self, product_id: int, max_results: int) -> list[Video]:
        product = self.product_repository.get_or_404(product_id)
        videos = self.youtube_client.fetch_product_videos(product.name, max_results=max_results)
        normalized_videos = [
            Video(
                video_id=video.video_id,
                product_id=product.product_id,
                title=video.title,
                description=video.description,
                published_at=video.published_at,
                thumbnail_url=video.thumbnail_url,
                view_count=video.view_count,
                like_count=video.like_count,
                comment_count=video.comment_count,
            )
            for video in videos
        ]
        self.video_repository.upsert_many(product.product_id, normalized_videos)
        return normalized_videos