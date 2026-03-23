from contextlib import closing

import psycopg2

from app.config import Settings


CREATE_PRODUCTS_SQL = """
CREATE TABLE IF NOT EXISTS tech_products (
    product_id   SERIAL PRIMARY KEY,
    name         VARCHAR(255) NOT NULL,
    brand        VARCHAR(255),
    created_at   TIMESTAMP DEFAULT NOW()
);
"""

CREATE_VIDEOS_SQL = """
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

CREATE_INDEX_SQL = """
CREATE INDEX IF NOT EXISTS idx_videos_product ON videos(product_id);
"""


class Database:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def connect(self):
        return psycopg2.connect(self.settings.database_url)

    def initialize(self) -> None:
        with closing(self.connect()) as conn:
            with conn, conn.cursor() as cur:
                cur.execute(CREATE_PRODUCTS_SQL)
                cur.execute(CREATE_VIDEOS_SQL)
                cur.execute(CREATE_INDEX_SQL)