from datetime import datetime

from pydantic import BaseModel, Field


class ProductCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    brand: str | None = Field(default=None, max_length=255)


class SyncVideosRequest(BaseModel):
    max_results: int = Field(default=5, ge=1, le=25)


class ProductResponse(BaseModel):
    product_id: int
    name: str
    brand: str | None
    created_at: datetime


class VideoResponse(BaseModel):
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
