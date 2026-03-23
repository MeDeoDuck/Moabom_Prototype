from dataclasses import dataclass
from datetime import datetime


@dataclass
class Product:
    product_id: int
    name: str
    brand: str | None
    created_at: datetime


@dataclass
class Video:
    video_id: str
    product_id: int
    title: str
    description: str | None
    published_at: datetime | None
    thumbnail_url: str | None
    view_count: int
    like_count: int
    comment_count: int
    created_at: datetime | None = None
