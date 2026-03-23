from contextlib import closing

from fastapi import HTTPException

from app.database import Database
from app.models import Product, Video


UPSERT_VIDEO_SQL = """
INSERT INTO videos (
    video_id,
    product_id,
    title,
    description,
    published_at,
    thumbnail_url,
    view_count,
    like_count,
    comment_count
)
VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
ON CONFLICT (video_id)
DO UPDATE SET
    product_id = EXCLUDED.product_id,
    title = EXCLUDED.title,
    description = EXCLUDED.description,
    published_at = EXCLUDED.published_at,
    thumbnail_url = EXCLUDED.thumbnail_url,
    view_count = EXCLUDED.view_count,
    like_count = EXCLUDED.like_count,
    comment_count = EXCLUDED.comment_count;
"""


class ProductRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    @staticmethod
    def _to_product(row: tuple) -> Product:
        return Product(
            product_id=row[0],
            name=row[1],
            brand=row[2],
            created_at=row[3],
        )

    def create(self, name: str, brand: str | None) -> Product:
        with closing(self.database.connect()) as conn:
            with conn, conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO tech_products (name, brand)
                    VALUES (%s, %s)
                    RETURNING product_id, name, brand, created_at
                    """,
                    (name, brand),
                )
                return self._to_product(cur.fetchone())

    def list_all(self) -> list[Product]:
        with closing(self.database.connect()) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT product_id, name, brand, created_at
                    FROM tech_products
                    ORDER BY product_id DESC
                    """
                )
                return [self._to_product(row) for row in cur.fetchall()]

    def get_or_404(self, product_id: int) -> Product:
        with closing(self.database.connect()) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT product_id, name, brand, created_at
                    FROM tech_products
                    WHERE product_id = %s
                    """,
                    (product_id,),
                )
                row = cur.fetchone()

        if not row:
            raise HTTPException(status_code=404, detail="Product not found")
        return self._to_product(row)


class VideoRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    @staticmethod
    def _to_video(row: tuple) -> Video:
        return Video(
            video_id=row[0],
            product_id=row[1],
            title=row[2],
            description=row[3],
            published_at=row[4],
            thumbnail_url=row[5],
            view_count=row[6],
            like_count=row[7],
            comment_count=row[8],
            created_at=row[9],
        )

    def upsert_many(self, product_id: int, videos: list[Video]) -> None:
        with closing(self.database.connect()) as conn:
            with conn, conn.cursor() as cur:
                for video in videos:
                    cur.execute(
                        UPSERT_VIDEO_SQL,
                        (
                            video.video_id,
                            product_id,
                            video.title,
                            video.description,
                            video.published_at,
                            video.thumbnail_url,
                            video.view_count,
                            video.like_count,
                            video.comment_count,
                        ),
                    )

    def list_by_product(self, product_id: int) -> list[Video]:
        with closing(self.database.connect()) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT video_id, product_id, title, description, published_at,
                    thumbnail_url, view_count, like_count, comment_count, created_at
                    FROM videos
                    WHERE product_id = %s
                    ORDER BY published_at DESC NULLS LAST, created_at DESC
                    """,
                    (product_id,),
                )
                return [self._to_video(row) for row in cur.fetchall()]
