"""
Database schema initialization
"""
from scripts.database.connection import get_connection


def init_db():
    """Initialize database schema on startup."""
    conn = get_connection()
    cursor = conn.cursor()
    
    # Create tables
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS tech_products (
            product_id   SERIAL PRIMARY KEY,
            name         VARCHAR(255) NOT NULL,
            brand        VARCHAR(255),
            category     VARCHAR(255),
            created_at   TIMESTAMP DEFAULT NOW()
        );
    """)
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS videos (
            video_id     VARCHAR(64) PRIMARY KEY,
            product_id   INT NOT NULL REFERENCES tech_products(product_id) ON DELETE CASCADE,
            title        VARCHAR(255) NOT NULL,
            description  TEXT,
            published_at TIMESTAMP,
            thumbnail_url TEXT,
            view_count   BIGINT,
            like_count   BIGINT,
            comment_count BIGINT,
            created_at   TIMESTAMP DEFAULT NOW()
        );
    """)
    
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_videos_product ON videos(product_id);
    """)
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS comments (
            comment_id        VARCHAR(64) PRIMARY KEY,
            video_id          VARCHAR(64) NOT NULL REFERENCES videos(video_id) ON DELETE CASCADE,
            parent_id         VARCHAR(64),
            text_raw          TEXT NOT NULL,
            is_product_related BOOLEAN,
            created_at        TIMESTAMP DEFAULT NOW()
        );
    """)
    
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_comments_video ON comments(video_id);
    """)
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS comment_sentiments (
            id               SERIAL PRIMARY KEY,
            comment_id       VARCHAR(64) NOT NULL REFERENCES comments(comment_id) ON DELETE CASCADE,
            sentiment_label  VARCHAR(16) NOT NULL,
            sentiment_score  NUMERIC(4,3),
            created_at       TIMESTAMP DEFAULT NOW()
        );
    """)
    
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_sentiments_comment ON comment_sentiments(comment_id);
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS video_transcripts (
            video_id        VARCHAR(64) PRIMARY KEY REFERENCES videos(video_id) ON DELETE CASCADE,
            transcript_text TEXT NOT NULL,
            language_code   VARCHAR(16),
            segment_count   INT,
            source          VARCHAR(32) DEFAULT 'youtube_transcript_api',
            updated_at      TIMESTAMP DEFAULT NOW()
        );
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS video_reports (
            video_id            VARCHAR(64) PRIMARY KEY REFERENCES videos(video_id) ON DELETE CASCADE,
            transcript_report   TEXT,
            comment_report      TEXT,
            integrated_report   TEXT,
            updated_at          TIMESTAMP DEFAULT NOW()
        );
    """)
    
    # Migration: Add integrated_report column if it doesn't exist
    cursor.execute("""
        SELECT EXISTS (
            SELECT 1 FROM information_schema.columns 
            WHERE table_name = 'video_reports' AND column_name = 'integrated_report'
        )
    """)
    if not cursor.fetchone()[0]:
        cursor.execute("""
            ALTER TABLE video_reports 
            ADD COLUMN integrated_report TEXT
        """)
        print("✓ Added integrated_report column")
    
    conn.commit()
    cursor.close()
    conn.close()
    print("✓ Database initialized")
