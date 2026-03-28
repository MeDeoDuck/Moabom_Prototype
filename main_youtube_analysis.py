"""
Product-centric YouTube Analysis Service
FastAPI + PostgreSQL + YouTube Data API v3
"""

import os
import json
import random
from typing import Optional, List, Dict, Any
from datetime import datetime
from pathlib import Path

import psycopg2
from psycopg2.extras import RealDictCursor
from dotenv import load_dotenv

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
import httpx
import uvicorn

# Load environment variables
load_dotenv()
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/techdb")
YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY", "")

# ============================================================================
# DATABASE LAYER
# ============================================================================

def get_connection():
    """Get a raw PostgreSQL connection."""
    return psycopg2.connect(DATABASE_URL)


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
    
    conn.commit()
    cursor.close()
    conn.close()
    print("✓ Database initialized")


def query_one(sql: str, params: tuple = ()) -> Optional[Dict]:
    """Execute query and return single row as dict."""
    conn = get_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)
    cursor.execute(sql, params)
    result = cursor.fetchone()
    cursor.close()
    conn.close()
    return result


def query_all(sql: str, params: tuple = ()) -> List[Dict]:
    """Execute query and return all rows as dicts."""
    conn = get_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)
    cursor.execute(sql, params)
    results = cursor.fetchall()
    cursor.close()
    conn.close()
    return results


def execute_insert(sql: str, params: tuple = ()) -> int:
    """Execute INSERT and return inserted ID (for SERIAL columns)."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(sql, params)
    result_id = cursor.fetchone()[0] if cursor.description else None
    conn.commit()
    cursor.close()
    conn.close()
    return result_id


def execute_update(sql: str, params: tuple = ()) -> int:
    """Execute UPDATE/DELETE and return row count."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(sql, params)
    row_count = cursor.rowcount
    conn.commit()
    cursor.close()
    conn.close()
    return row_count


# ============================================================================
# YOUTUBE API LAYER
# ============================================================================

def fetch_product_videos(product_name: str, max_results: int = 5) -> List[Dict[str, Any]]:
    """
    Search YouTube for videos about a product and fetch their statistics.
    Returns list of dicts: {video_id, title, description, published_at, thumbnail_url, view_count, like_count, comment_count}
    """
    if not YOUTUBE_API_KEY:
        return []
    
    try:
        client = httpx.Client()
        
        # Step 1: Search for videos
        search_url = "https://www.googleapis.com/youtube/v3/search"
        search_params = {
            "part": "snippet",
            "q": product_name,
            "type": "video",
            "maxResults": max_results,
            "key": YOUTUBE_API_KEY,
        }
        search_resp = client.get(search_url, params=search_params, timeout=30.0)
        search_resp.raise_for_status()
        search_data = search_resp.json()
        
        video_ids = [item["id"]["videoId"] for item in search_data.get("items", [])]
        if not video_ids:
            return []
        
        # Step 2: Get video statistics
        videos_url = "https://www.googleapis.com/youtube/v3/videos"
        videos_params = {
            "part": "snippet,statistics",
            "id": ",".join(video_ids),
            "key": YOUTUBE_API_KEY,
        }
        videos_resp = client.get(videos_url, params=videos_params, timeout=30.0)
        videos_resp.raise_for_status()
        videos_data = videos_resp.json()
        
        results = []
        for item in videos_data.get("items", []):
            video_id = item["id"]
            snippet = item.get("snippet", {})
            stats = item.get("statistics", {})
            
            results.append({
                "video_id": video_id,
                "title": snippet.get("title", ""),
                "description": snippet.get("description", ""),
                "published_at": snippet.get("publishedAt"),
                "thumbnail_url": snippet.get("thumbnails", {}).get("medium", {}).get("url"),
                "view_count": int(stats.get("viewCount", 0)),
                "like_count": int(stats.get("likeCount", 0)),
                "comment_count": int(stats.get("commentCount", 0)),
            })
        
        client.close()
        return results
    except Exception as e:
        print(f"Error fetching videos: {e}")
        return []


def fetch_video_comments(video_id: str, max_pages: int = 2) -> List[Dict[str, str]]:
    """
    Fetch top-level comments for a YouTube video.
    Returns list of dicts: {comment_id, text_raw}
    """
    if not YOUTUBE_API_KEY:
        return []
    
    try:
        client = httpx.Client()
        results = []
        next_page_token = None
        pages = 0
        
        while pages < max_pages:
            url = "https://www.googleapis.com/youtube/v3/commentThreads"
            params = {
                "part": "snippet",
                "videoId": video_id,
                "maxResults": 100,
                "textFormat": "plainText",
                "key": YOUTUBE_API_KEY,
            }
            if next_page_token:
                params["pageToken"] = next_page_token
            
            resp = client.get(url, params=params, timeout=30.0)
            resp.raise_for_status()
            data = resp.json()
            
            for item in data.get("items", []):
                top_comment = item["snippet"]["topLevelComment"]["snippet"]
                comment_id = item["snippet"]["topLevelComment"]["id"]
                
                results.append({
                    "comment_id": comment_id,
                    "text_raw": top_comment.get("textDisplay", ""),
                })
            
            next_page_token = data.get("nextPageToken")
            if not next_page_token:
                break
            
            pages += 1
        
        client.close()
        return results
    except Exception as e:
        print(f"Error fetching comments: {e}")
        return []


# ============================================================================
# SENTIMENT & PRODUCT ANALYSIS
# ============================================================================

def is_product_related(text: str, product_name: str = "") -> bool:
    """
    Simple heuristic to determine if a comment is product-related.
    Checks for product name and common tech keywords.
    """
    text_lower = text.lower()
    
    # Check for product name
    if product_name and product_name.lower() in text_lower:
        return True
    
    # Check for common tech keywords
    keywords = ["price", "spec", "battery", "performance", "quality", "feature", 
                "design", "review", "recommend", "issue", "problem", "bug", "error",
                "upgrade", "worth", "value", "camera", "screen", "cpu", "gpu",
                "ram", "storage", "display", "build", "material"]
    
    for keyword in keywords:
        if keyword in text_lower:
            return True
    
    return False


def analyze_sentiment(text: str) -> tuple[str, float]:
    """
    Simple rule-based sentiment analysis.
    Returns (sentiment_label, sentiment_score)
    """
    text_lower = text.lower()
    
    positive_words = ["good", "love", "great", "excellent", "amazing", "awesome", 
                      "best", "perfect", "fantastic", "wonderful", "brilliant",
                      "recommend", "worth", "impressive", "beautiful", "smooth"]
    
    negative_words = ["bad", "hate", "poor", "terrible", "awful", "horrible",
                      "worst", "useless", "broken", "issue", "problem", "bug",
                      "disappointing", "waste", "regret", "return"]
    
    positive_count = sum(1 for word in positive_words if word in text_lower)
    negative_count = sum(1 for word in negative_words if word in text_lower)
    
    if positive_count > negative_count:
        return ("positive", 0.85)
    elif negative_count > positive_count:
        return ("negative", 0.85)
    else:
        return ("neutral", 0.5)


# ============================================================================
# FASTAPI APP & ROUTES
# ============================================================================

app = FastAPI(title="YouTube Product Analysis Service")

# Ensure templates directory exists
TEMPLATES_DIR = Path("templates")
TEMPLATES_DIR.mkdir(exist_ok=True)

# Templates as strings
TEMPLATE_PRODUCTS = """
<!DOCTYPE html>
<html>
<head>
    <title>Tech Products</title>
    <style>
        body { font-family: Arial, sans-serif; margin: 20px; }
        .container { max-width: 900px; margin: 0 auto; }
        h1 { color: #333; }
        .form-group { margin-bottom: 15px; }
        label { display: block; margin-bottom: 5px; font-weight: bold; }
        input, select { padding: 8px; width: 200px; }
        button { padding: 10px 20px; background: #007bff; color: white; border: none; cursor: pointer; border-radius: 4px; }
        button:hover { background: #0056b3; }
        .product-list { margin-top: 30px; }
        .product-item { padding: 12px; border: 1px solid #ddd; margin-bottom: 10px; border-radius: 4px; }
        .product-item a { color: #007bff; text-decoration: none; }
        .product-item a:hover { text-decoration: underline; }
        .product-meta { font-size: 0.9em; color: #666; margin-top: 5px; }
    </style>
</head>
<body>
    <div class="container">
        <h1>📱 Tech Products Dashboard</h1>
        
        <div>
            <h2>Add New Product</h2>
            <form id="productForm">
                <div class="form-group">
                    <label for="name">Product Name *</label>
                    <input type="text" id="name" name="name" required>
                </div>
                <div class="form-group">
                    <label for="brand">Brand</label>
                    <input type="text" id="brand" name="brand">
                </div>
                <div class="form-group">
                    <label for="category">Category</label>
                    <input type="text" id="category" name="category" placeholder="e.g., Smartphone, Laptop">
                </div>
                <button type="submit">Create Product</button>
            </form>
        </div>
        
        <div class="product-list">
            <h2>Products ({{ products|length }})</h2>
            {% if products %}
                {% for product in products %}
                    <div class="product-item">
                        <strong><a href="/products/{{ product.product_id }}">{{ product.name }}</a></strong>
                        <div class="product-meta">
                            Brand: {{ product.brand or 'N/A' }} | Category: {{ product.category or 'N/A' }}
                        </div>
                    </div>
                {% endfor %}
            {% else %}
                <p>No products yet. Create one above!</p>
            {% endif %}
        </div>
    </div>

    <script>
        document.getElementById('productForm').addEventListener('submit', async (e) => {
            e.preventDefault();
            const data = {
                name: document.getElementById('name').value,
                brand: document.getElementById('brand').value,
                category: document.getElementById('category').value,
            };
            
            try {
                const response = await fetch('/products', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(data),
                });
                
                if (response.ok) {
                    location.reload();
                } else {
                    alert('Error creating product');
                }
            } catch (error) {
                alert('Error: ' + error);
            }
        });
    </script>
</body>
</html>
"""

TEMPLATE_PRODUCT_DETAIL = """
<!DOCTYPE html>
<html>
<head>
    <title>{{ product.name }} - Product Details</title>
    <style>
        body { font-family: Arial, sans-serif; margin: 20px; }
        .container { max-width: 1000px; margin: 0 auto; }
        h1 { color: #333; }
        .product-info { background: #f5f5f5; padding: 15px; border-radius: 4px; margin-bottom: 20px; }
        .product-info p { margin: 5px 0; }
        .sync-btn { padding: 12px 24px; background: #28a745; color: white; border: none; cursor: pointer; border-radius: 4px; font-size: 16px; }
        .sync-btn:hover { background: #218838; }
        .sync-btn:disabled { background: #ccc; cursor: not-allowed; }
        .videos-section { margin-top: 30px; }
        table { width: 100%; border-collapse: collapse; margin-top: 15px; }
        th, td { padding: 12px; text-align: left; border-bottom: 1px solid #ddd; }
        th { background: #007bff; color: white; }
        tr:hover { background: #f5f5f5; }
        .video-title a { color: #007bff; text-decoration: none; }
        .video-title a:hover { text-decoration: underline; }
        .video-thumb { width: 80px; height: 45px; object-fit: cover; border-radius: 3px; }
        .back-link { margin-bottom: 20px; }
        .back-link a { color: #007bff; }
    </style>
</head>
<body>
    <div class="container">
        <div class="back-link">
            <a href="/products">← Back to Products</a>
        </div>
        
        <h1>{{ product.name }}</h1>
        
        <div class="product-info">
            <p><strong>Brand:</strong> {{ product.brand or 'N/A' }}</p>
            <p><strong>Category:</strong> {{ product.category or 'N/A' }}</p>
            <p><strong>Created:</strong> {{ product.created_at }}</p>
        </div>
        
        <div>
            <button class="sync-btn" onclick="syncVideos()" id="syncBtn">🔄 Sync Videos from YouTube</button>
            <span id="syncStatus"></span>
        </div>
        
        <div class="videos-section">
            <h2>Videos ({{ videos|length }})</h2>
            {% if videos %}
                <table>
                    <thead>
                        <tr>
                            <th>Thumbnail</th>
                            <th>Title</th>
                            <th>Views</th>
                            <th>Likes</th>
                            <th>Comments</th>
                        </tr>
                    </thead>
                    <tbody>
                        {% for video in videos %}
                            <tr>
                                <td>
                                    {% if video.thumbnail_url %}
                                        <img src="{{ video.thumbnail_url }}" alt="thumbnail" class="video-thumb">
                                    {% endif %}
                                </td>
                                <td class="video-title">
                                    <a href="/products/{{ product.product_id }}/videos/{{ video.video_id }}">
                                        {{ video.title[:50] }}...
                                    </a>
                                </td>
                                <td>{{ video.view_count }}</td>
                                <td>{{ video.like_count }}</td>
                                <td>{{ video.comment_count }}</td>
                            </tr>
                        {% endfor %}
                    </tbody>
                </table>
            {% else %}
                <p>No videos yet. Click "Sync Videos from YouTube" to fetch them.</p>
            {% endif %}
        </div>
    </div>

    <script>
        async function syncVideos() {
            const btn = document.getElementById('syncBtn');
            const status = document.getElementById('syncStatus');
            
            btn.disabled = true;
            status.textContent = ' Syncing...';
            
            try {
                const response = await fetch('/products/{{ product.product_id }}/sync', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                });
                
                if (response.ok) {
                    const result = await response.json();
                    status.textContent = ' ✓ Synced! Videos: ' + result.videos_count + ', Comments: ' + result.comments_count;
                    setTimeout(() => location.reload(), 1000);
                } else {
                    status.textContent = ' Error during sync';
                }
            } catch (error) {
                status.textContent = ' Error: ' + error;
            } finally {
                btn.disabled = false;
            }
        }
    </script>
</body>
</html>
"""

TEMPLATE_VIDEO_DETAIL = """
<!DOCTYPE html>
<html>
<head>
    <title>{{ video.title }} - Video Analysis</title>
    <style>
        body { font-family: Arial, sans-serif; margin: 20px; }
        .container { max-width: 1000px; margin: 0 auto; }
        h1 { color: #333; }
        .video-info { background: #f5f5f5; padding: 15px; border-radius: 4px; margin-bottom: 20px; }
        .video-info p { margin: 8px 0; }
        .youtube-link { color: #ff0000; text-decoration: none; font-weight: bold; }
        .youtube-link:hover { text-decoration: underline; }
        .stats { display: grid; grid-template-columns: repeat(4, 1fr); gap: 15px; margin-bottom: 20px; }
        .stat-box { background: #007bff; color: white; padding: 15px; border-radius: 4px; text-align: center; }
        .stat-box .label { font-size: 0.9em; opacity: 0.9; }
        .stat-box .value { font-size: 1.8em; font-weight: bold; }
        .sentiment-section { margin-top: 30px; }
        .sentiment-summary { display: grid; grid-template-columns: repeat(3, 1fr); gap: 15px; margin-bottom: 20px; }
        .sentiment-box { padding: 15px; border-radius: 4px; text-align: center; }
        .sentiment-box.positive { background: #28a745; color: white; }
        .sentiment-box.neutral { background: #ffc107; color: black; }
        .sentiment-box.negative { background: #dc3545; color: white; }
        .sentiment-box .label { font-size: 0.9em; opacity: 0.9; }
        .sentiment-box .value { font-size: 1.5em; font-weight: bold; }
        .comments-section { margin-top: 30px; }
        .comment-item { background: #f9f9f9; padding: 12px; margin-bottom: 10px; border-radius: 4px; border-left: 4px solid #ddd; }
        .comment-item.positive { border-left-color: #28a745; }
        .comment-item.negative { border-left-color: #dc3545; }
        .comment-item.neutral { border-left-color: #ffc107; }
        .comment-text { margin-bottom: 5px; }
        .comment-meta { font-size: 0.85em; color: #666; }
        .back-link { margin-bottom: 20px; }
        .back-link a { color: #007bff; }
    </style>
</head>
<body>
    <div class="container">
        <div class="back-link">
            <a href="/products/{{ product_id }}">← Back to Product</a>
        </div>
        
        <h1>{{ video.title }}</h1>
        
        <div class="video-info">
            <p><strong>YouTube:</strong> <a href="https://www.youtube.com/watch?v={{ video.video_id }}" target="_blank" class="youtube-link">Watch Video</a></p>
            <p><strong>Published:</strong> {{ video.published_at }}</p>
        </div>
        
        <div class="stats">
            <div class="stat-box">
                <div class="label">Views</div>
                <div class="value">{{ video.view_count }}</div>
            </div>
            <div class="stat-box">
                <div class="label">Likes</div>
                <div class="value">{{ video.like_count }}</div>
            </div>
            <div class="stat-box">
                <div class="label">Comments</div>
                <div class="value">{{ video.comment_count }}</div>
            </div>
            <div class="stat-box">
                <div class="label">Product-Related</div>
                <div class="value">{{ product_related_count }}</div>
            </div>
        </div>
        
        <div class="sentiment-section">
            <h2>Sentiment Analysis</h2>
            <div class="sentiment-summary">
                <div class="sentiment-box positive">
                    <div class="label">Positive</div>
                    <div class="value">{{ sentiment_positive }}</div>
                </div>
                <div class="sentiment-box neutral">
                    <div class="label">Neutral</div>
                    <div class="value">{{ sentiment_neutral }}</div>
                </div>
                <div class="sentiment-box negative">
                    <div class="label">Negative</div>
                    <div class="value">{{ sentiment_negative }}</div>
                </div>
            </div>
        </div>
        
        <div class="comments-section">
            <h2>Product-Related Comments</h2>
            {% if comments %}
                {% for comment in comments %}
                    <div class="comment-item {{ comment.sentiment_label }}">
                        <div class="comment-text">{{ comment.text_raw }}</div>
                        <div class="comment-meta">
                            Sentiment: <strong>{{ comment.sentiment_label|upper }}</strong> ({{ comment.sentiment_score }})
                        </div>
                    </div>
                {% endfor %}
            {% else %}
                <p>No product-related comments found.</p>
            {% endif %}
        </div>
    </div>
</body>
</html>
"""

# Write templates to files on startup
def write_templates():
    """Write template strings to files."""
    templates = {
        "templates/products.html": TEMPLATE_PRODUCTS,
        "templates/product_detail.html": TEMPLATE_PRODUCT_DETAIL,
        "templates/video_detail.html": TEMPLATE_VIDEO_DETAIL,
    }
    
    for path, content in templates.items():
        Path(path).write_text(content, encoding="utf-8")
    
    print("✓ Templates written")


templates = Jinja2Templates(directory="templates")


@app.on_event("startup")
async def startup_event():
    """Initialize database and templates on startup."""
    init_db()
    write_templates()


@app.get("/", response_class=HTMLResponse)
async def root():
    """Redirect to products page."""
    return "<script>window.location.href='/products'</script>"


@app.get("/products", response_class=HTMLResponse)
async def list_products(request: Request):
    """List all products."""
    products = query_all("SELECT * FROM tech_products ORDER BY created_at DESC")
    return templates.TemplateResponse("products.html", {
        "request": request,
        "products": products,
    })


@app.post("/products")
async def create_product(data: dict):
    """Create a new product."""
    name = data.get("name", "").strip()
    brand = data.get("brand", "").strip() or None
    category = data.get("category", "").strip() or None
    
    if not name:
        raise HTTPException(status_code=400, detail="Product name is required")
    
    product_id = execute_insert(
        "INSERT INTO tech_products (name, brand, category) VALUES (%s, %s, %s) RETURNING product_id",
        (name, brand, category)
    )
    
    product = query_one("SELECT * FROM tech_products WHERE product_id = %s", (product_id,))
    return product


@app.get("/products/{product_id}", response_class=HTMLResponse)
async def product_detail(request: Request, product_id: int):
    """Show product detail page with videos."""
    product = query_one("SELECT * FROM tech_products WHERE product_id = %s", (product_id,))
    
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    
    videos = query_all(
        "SELECT * FROM videos WHERE product_id = %s ORDER BY view_count DESC",
        (product_id,)
    )
    
    return templates.TemplateResponse("product_detail.html", {
        "request": request,
        "product": product,
        "videos": videos,
    })


@app.post("/products/{product_id}/sync")
async def sync_product_videos(product_id: int, data: dict = None):
    """Sync videos and comments from YouTube for a product."""
    product = query_one("SELECT * FROM tech_products WHERE product_id = %s", (product_id,))
    
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    
    max_results = (data or {}).get("max_results", 5)
    
    # Fetch videos from YouTube
    videos = fetch_product_videos(product["name"], max_results=max_results)
    videos_count = 0
    comments_count = 0
    
    for video in videos:
        # UPSERT video
        existing = query_one(
            "SELECT video_id FROM videos WHERE video_id = %s",
            (video["video_id"],)
        )
        
        if existing:
            # Update
            execute_update(
                """UPDATE videos SET title = %s, description = %s, published_at = %s,
                   thumbnail_url = %s, view_count = %s, like_count = %s, comment_count = %s
                   WHERE video_id = %s""",
                (video["title"], video["description"], video["published_at"],
                 video["thumbnail_url"], video["view_count"], video["like_count"],
                 video["comment_count"], video["video_id"])
            )
        else:
            # Insert
            execute_update(
                """INSERT INTO videos (video_id, product_id, title, description, published_at,
                   thumbnail_url, view_count, like_count, comment_count)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                (video["video_id"], product_id, video["title"], video["description"],
                 video["published_at"], video["thumbnail_url"], video["view_count"],
                 video["like_count"], video["comment_count"])
            )
            videos_count += 1
        
        # Fetch and process comments
        comments = fetch_video_comments(video["video_id"], max_pages=2)
        
        for comment in comments:
            # Check if comment already exists
            existing_comment = query_one(
                "SELECT comment_id FROM comments WHERE comment_id = %s",
                (comment["comment_id"],)
            )
            
            if existing_comment:
                continue
            
            # Determine if product-related
            is_related = is_product_related(comment["text_raw"], product["name"])
            
            # Insert comment
            execute_update(
                """INSERT INTO comments (comment_id, video_id, text_raw, is_product_related)
                   VALUES (%s, %s, %s, %s)""",
                (comment["comment_id"], video["video_id"], comment["text_raw"], is_related)
            )
            comments_count += 1
            
            # Analyze sentiment if product-related
            if is_related:
                sentiment_label, sentiment_score = analyze_sentiment(comment["text_raw"])
                
                execute_update(
                    """INSERT INTO comment_sentiments (comment_id, sentiment_label, sentiment_score)
                       VALUES (%s, %s, %s)""",
                    (comment["comment_id"], sentiment_label, sentiment_score)
                )
    
    return {
        "status": "success",
        "videos_count": videos_count,
        "comments_count": comments_count,
    }


@app.get("/products/{product_id}/videos/{video_id}", response_class=HTMLResponse)
async def video_detail(request: Request, product_id: int, video_id: str, page: int = 1):
    """Show video detail page with sentiment analysis and pagination."""
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
    
    # Get product-related comments with sentiment (paginated)
    comments = query_all(
        """SELECT c.comment_id, c.text_raw, cs.sentiment_label, cs.sentiment_score
           FROM comments c
           LEFT JOIN comment_sentiments cs ON c.comment_id = cs.comment_id
           WHERE c.video_id = %s AND c.is_product_related = true
           ORDER BY c.created_at DESC LIMIT %s OFFSET %s""",
        (video_id, per_page, offset)
    )
    
    # Count total product-related comments
    product_related_count = query_one(
        "SELECT COUNT(*) as count FROM comments WHERE video_id = %s AND is_product_related = true",
        (video_id,)
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
    })


# ============================================================================
# APP ENTRY POINT
# ============================================================================

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
