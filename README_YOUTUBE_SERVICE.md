# YouTube Product Analysis Service

A minimal but fully functional FastAPI + PostgreSQL + YouTube Data API v3 service for analyzing product videos and comment sentiment.

## Features

✅ **Product Management**: Create and manage tech products  
✅ **YouTube Integration**: Auto-fetch videos and comments for any product  
✅ **Sentiment Analysis**: Rule-based sentiment detection (positive/neutral/negative)  
✅ **Product-Related Filtering**: Smart comment filtering by relevance  
✅ **Web Dashboard**: Beautiful UI for browsing products, videos, and insights  
✅ **PostgreSQL Backend**: Persistent storage with proper indexing  

## Tech Stack

- **Language**: Python 3.11
- **Framework**: FastAPI
- **Database**: PostgreSQL
- **Database Driver**: psycopg2-binary
- **Templates**: Jinja2
- **HTTP Client**: httpx
- **External API**: YouTube Data API v3

## Setup Instructions

### 1. Prerequisites

- Python 3.11+
- PostgreSQL (local or remote)
- YouTube Data API key (free tier available)

### 2. Install Dependencies

```bash
pip install -r requirements.txt
```

### 3. Configure Environment Variables

Update `.env` file with your credentials:

```env
DATABASE_URL=postgresql://user:password@localhost:5432/techdb
YOUTUBE_API_KEY=your_youtube_api_key_here
```

To get a YouTube API key:
1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Create a new project
3. Enable YouTube Data API v3
4. Create an API key (credentials)
5. Copy the key to `.env`

### 4. Create PostgreSQL Database

```bash
# Connect to PostgreSQL and create the database
createdb techdb
```

Or in psql:
```sql
CREATE DATABASE techdb;
```

### 5. Run the Application

```bash
python main_youtube_analysis.py
```

The app will start on `http://localhost:8000`

On first run:
- Tables are automatically created
- Templates are written to `templates/` directory

## Usage

### Web Dashboard

1. **Home Page** (`http://localhost:8000/`)
   - View all products
   - Create new products (name, brand, category)

2. **Product Detail** (`/products/{product_id}`)
   - View product information
   - Click "Sync Videos from YouTube" to fetch videos and comments
   - Browse synced videos with stats

3. **Video Analysis** (`/products/{product_id}/videos/{video_id}`)
   - Video statistics (views, likes, comments)
   - Sentiment breakdown chart
   - Sample product-related comments with sentiment labels

### API Endpoints

#### Create Product
```bash
curl -X POST http://localhost:8000/products \
  -H "Content-Type: application/json" \
  -d '{
    "name": "iPhone 15 Pro",
    "brand": "Apple",
    "category": "Smartphone"
  }'
```

#### Sync Videos for Product
```bash
curl -X POST http://localhost:8000/products/1/sync \
  -H "Content-Type: application/json" \
  -d '{"max_results": 5}'
```

## Database Schema

### tech_products
```sql
CREATE TABLE tech_products (
    product_id   SERIAL PRIMARY KEY,
    name         VARCHAR(255) NOT NULL,
    brand        VARCHAR(255),
    category     VARCHAR(255),
    created_at   TIMESTAMP DEFAULT NOW()
);
```

### videos
```sql
CREATE TABLE videos (
    video_id     VARCHAR(64) PRIMARY KEY,
    product_id   INT NOT NULL REFERENCES tech_products(product_id),
    title        VARCHAR(255) NOT NULL,
    description  TEXT,
    published_at TIMESTAMP,
    thumbnail_url TEXT,
    view_count   BIGINT,
    like_count   BIGINT,
    comment_count BIGINT,
    created_at   TIMESTAMP DEFAULT NOW()
);
```

### comments
```sql
CREATE TABLE comments (
    comment_id        VARCHAR(64) PRIMARY KEY,
    video_id          VARCHAR(64) NOT NULL REFERENCES videos(video_id),
    parent_id         VARCHAR(64),
    text_raw          TEXT NOT NULL,
    is_product_related BOOLEAN,
    created_at        TIMESTAMP DEFAULT NOW()
);
```

### comment_sentiments
```sql
CREATE TABLE comment_sentiments (
    id               SERIAL PRIMARY KEY,
    comment_id       VARCHAR(64) NOT NULL REFERENCES comments(comment_id),
    sentiment_label  VARCHAR(16) NOT NULL,
    sentiment_score  NUMERIC(4,3),
    created_at       TIMESTAMP DEFAULT NOW()
);
```

## Project Structure

```
.
├── main_youtube_analysis.py    # Main application (all code in one file)
├── requirements.txt             # Python dependencies
├── .env                         # Environment variables (DO NOT commit)
├── .gitignore                   # Git ignore rules
├── templates/                   # Auto-generated Jinja2 templates
│   ├── products.html
│   ├── product_detail.html
│   └── video_detail.html
└── README.md                    # This file
```

## Key Features Explained

### YouTube Integration

**`fetch_product_videos(product_name, max_results=5)`**
- Searches YouTube for videos matching product name
- Fetches video stats (views, likes, comment count)
- Returns structured data for storage

**`fetch_video_comments(video_id, max_pages=2)`**
- Retrieves top-level comments (ignores replies)
- Supports pagination (up to max_pages)
- Extracts comment ID and text

### Sentiment Analysis

**`analyze_sentiment(text)`**
- Naive rule-based implementation
- Detects positive words (good, love, great, etc.)
- Detects negative words (bad, hate, terrible, etc.)
- Returns (label, score) tuple

### Product Relevance

**`is_product_related(text, product_name)`**
- Checks for product name in comment
- Matches tech-related keywords (price, specs, battery, etc.)
- Returns boolean relevance score

## Limitations & Future Enhancements

### Current Limitations
- Sentiment analysis is rule-based (not ML-based)
- Only top-level comments (no replies)
- Limited to 2 pages of comments per video
- No authentication/authorization
- Single-threaded API calls

### Possible Enhancements
1. **ML Sentiment**: Integrate with transformers/BERT for better accuracy
2. **Async Processing**: Use Celery/Redis for background sync jobs
3. **Reply Comments**: Include nested comment threads
4. **User Auth**: Add JWT-based authentication
5. **Caching**: Redis cache for YouTube API calls
6. **Notifications**: Email alerts for high-sentiment trends
7. **Export**: CSV/PDF reports of sentiment analysis
8. **Advanced Filtering**: Date ranges, keyword filters

## Troubleshooting

### "Database connection failed"
- Ensure PostgreSQL is running
- Check DATABASE_URL in .env is correct
- Verify database exists: `psql -l | grep techdb`

### "YouTube API key invalid"
- Verify YOUTUBE_API_KEY in .env
- Check API is enabled in Google Cloud Console
- Ensure quota limits not exceeded

### "Templates not found"
- Templates auto-create on app startup
- Check `templates/` directory exists
- Run app with `python main_youtube_analysis.py`

### "No videos found after sync"
- Check YouTube API quota (typically 10,000 units/day)
- Verify product name is specific enough
- Try searching YouTube directly for the product

## Security Notes

⚠️ **Important**: Never commit `.env` file with real credentials to git!

The `.gitignore` file already excludes:
- `.env` - Environment variables
- `__pycache__/` - Python cache
- `*.pyc` - Compiled Python files

## License

This project is provided as-is for educational and demonstration purposes.

## Support

For issues or questions:
1. Check the Troubleshooting section
2. Review logs from app startup
3. Verify all dependencies installed: `pip list | grep -E "fastapi|psycopg2|httpx"`
4. Check PostgreSQL is running and accessible

---

**Last Updated**: March 2026  
**Status**: Ready for development
