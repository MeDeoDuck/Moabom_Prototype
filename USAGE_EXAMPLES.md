# YouTube Analysis Service - Usage Examples

## Quick Start

### 1. Install & Setup

```bash
# Install dependencies
pip install -r requirements.txt

# Run setup script (Windows)
setup.bat

# Or setup script (Linux/macOS)
bash setup.sh
```

### 2. Start the Service

```bash
python main_youtube_analysis.py
```

Expected output:
```
✓ Database initialized
✓ Templates written
INFO:     Uvicorn running on http://0.0.0.0:8000
```

### 3. Open in Browser

Navigate to: `http://localhost:8000`

You'll see the Product Dashboard with a form to create products.

---

## Step-by-Step Workflow

### Step 1: Create a Product

On the dashboard, fill the form:
- **Product Name**: iPhone 15 Pro (required)
- **Brand**: Apple
- **Category**: Smartphone

Click "Create Product"

### Step 2: Sync Videos from YouTube

1. Click on the product name to view its detail page
2. Click the blue "🔄 Sync Videos from YouTube" button
3. Wait for the sync to complete (may take 30 seconds to 2 minutes)
4. You'll see a success message with count of videos and comments

Example response:
```json
{
  "status": "success",
  "videos_count": 5,
  "comments_count": 287
}
```

### Step 3: Browse Videos

After syncing, you'll see a table of videos with:
- Video thumbnail
- Title (clickable to view details)
- View count
- Like count  
- Comment count

### Step 4: View Video Analysis

Click on any video title to see:
- Full video title and YouTube link
- Video statistics (views, likes, comments)
- Sentiment breakdown (positive, neutral, negative counts)
- Sample comments with sentiment labels

---

## API Usage Examples

### Example 1: Create Multiple Products

```bash
curl -X POST http://localhost:8000/products \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Samsung Galaxy S24",
    "brand": "Samsung",
    "category": "Smartphone"
  }'

curl -X POST http://localhost:8000/products \
  -H "Content-Type: application/json" \
  -d '{
    "name": "MacBook Pro M3",
    "brand": "Apple",
    "category": "Laptop"
  }'

curl -X POST http://localhost:8000/products \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Sony WH-1000XM5",
    "brand": "Sony",
    "category": "Headphones"
  }'
```

### Example 2: Sync Videos with Custom Max Results

```bash
# Sync up to 10 videos for product ID 1
curl -X POST http://localhost:8000/products/1/sync \
  -H "Content-Type: application/json" \
  -d '{"max_results": 10}'
```

Response:
```json
{
  "status": "success",
  "videos_count": 10,
  "comments_count": 512
}
```

### Example 3: View Product via API

```bash
# Get all products (HTML page)
curl http://localhost:8000/products

# Get product detail (HTML page)
curl http://localhost:8000/products/1

# Get video detail (HTML page)
curl http://localhost:8000/products/1/videos/dQw4w9WgXcQ
```

---

## Understanding the Data

### Product-Related Comment Detection

A comment is marked as "product-related" if it contains:
1. The product name (case-insensitive), OR
2. At least one tech keyword:
   - Price, specs, battery, performance, quality, feature
   - Design, review, recommend, issue, problem, bug
   - Upgrade, worth, value, camera, screen, CPU, GPU
   - RAM, storage, display, build, material

### Sentiment Analysis

Sentiment is determined by keyword matching:

**Positive** (0.85 score):
- Contains: good, love, great, excellent, amazing, awesome
- Contains: best, perfect, fantastic, wonderful, brilliant
- Contains: recommend, worth, impressive, beautiful, smooth

**Negative** (0.85 score):
- Contains: bad, hate, poor, terrible, awful, horrible
- Contains: worst, useless, broken, issue, problem, bug
- Contains: disappointing, waste, regret, return

**Neutral** (0.5 score):
- No strong positive or negative keywords

---

## Database Queries

### View Raw Data

```sql
-- All products
SELECT * FROM tech_products;

-- Videos for a product
SELECT * FROM videos WHERE product_id = 1 ORDER BY view_count DESC;

-- Comments for a video
SELECT * FROM comments WHERE video_id = 'dQw4w9WgXcQ' AND is_product_related = true;

-- Sentiment breakdown for a video
SELECT sentiment_label, COUNT(*) as count
FROM comment_sentiments cs
JOIN comments c ON cs.comment_id = c.comment_id
WHERE c.video_id = 'dQw4w9WgXcQ'
GROUP BY sentiment_label;
```

### Analytics Queries

```sql
-- Most viewed video per product
SELECT DISTINCT ON (product_id) 
  product_id, video_id, title, view_count 
FROM videos 
ORDER BY product_id, view_count DESC;

-- Sentiment distribution across all products
SELECT p.name, cs.sentiment_label, COUNT(*) as count
FROM comment_sentiments cs
JOIN comments c ON cs.comment_id = c.comment_id
JOIN videos v ON c.video_id = v.video_id
JOIN tech_products p ON v.product_id = p.product_id
GROUP BY p.name, cs.sentiment_label
ORDER BY p.name, count DESC;

-- Average comment count per video
SELECT p.name, AVG(v.comment_count) as avg_comments
FROM videos v
JOIN tech_products p ON v.product_id = p.product_id
GROUP BY p.name
ORDER BY avg_comments DESC;
```

---

## Common Issues & Solutions

### Issue: No videos found after sync

**Possible causes:**
1. YouTube API quota exceeded (10,000 units/day limit)
2. Product name is too generic or doesn't match YouTube content
3. Invalid API key

**Solution:**
- Wait 24 hours for quota to reset, OR
- Try a more specific product name, OR
- Verify API key in `.env`

### Issue: Connection refused (PostgreSQL)

**Solution:**
```bash
# Check if PostgreSQL is running
psql -U postgres -h localhost

# If not running, start it:
# Windows: net start postgresql-x64-15
# macOS: brew services start postgresql
# Linux: sudo systemctl start postgresql
```

### Issue: Templates not found

**Solution:**
- Templates auto-generate on app startup
- Run the app once: `python main_youtube_analysis.py`
- Check `templates/` directory exists
- If missing, manually run: `mkdir templates`

---

## Performance Tips

1. **Sync Time**: Syncing 5 videos with 100 comments each = ~30-60 seconds
2. **Database Indexing**: Queries are indexed by product_id, video_id for fast lookup
3. **API Quota**: Each video sync uses ~100 API units (YouTube allows 10,000/day)
4. **Batch Operations**: Sync multiple products on a schedule (e.g., cron job)

---

## Next Steps

### For Development
- Add authentication/authorization
- Implement async video syncing with Celery
- Add real ML sentiment analysis (transformers)
- Create export to CSV/PDF reports
- Add email notifications

### For Production
- Use connection pooling (psycopg2.pool)
- Add rate limiting to prevent abuse
- Implement caching with Redis
- Set up monitoring/logging
- Run behind a reverse proxy (nginx)
- Use environment-specific configuration

---

## Troubleshooting Checklist

- [ ] Python 3.11+ installed
- [ ] PostgreSQL running and accessible
- [ ] `.env` file created with DATABASE_URL and YOUTUBE_API_KEY
- [ ] Dependencies installed: `pip install -r requirements.txt`
- [ ] Database database created: `createdb techdb`
- [ ] App starts without errors: `python main_youtube_analysis.py`
- [ ] Dashboard loads: `http://localhost:8000`
- [ ] Can create products via web form
- [ ] YouTube API key is valid and enabled
- [ ] API quota not exceeded

---

Last Updated: March 2026
