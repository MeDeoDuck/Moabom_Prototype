# 🧪 YouTube Analysis Service - Testing Guide

## Quick Test (5 minutes)

### 1. Start the Service
```bash
python main_youtube_analysis.py
```

Expected output:
```
✓ Database initialized
✓ Templates written
INFO:     Uvicorn running on http://0.0.0.0:8000
```

### 2. Open Dashboard
Navigate to: `http://localhost:8000`

**Expected**: Empty product list with "Add New Product" form

### 3. Create a Test Product
Fill the form with:
- **Name**: iPhone 15 Pro
- **Brand**: Apple
- **Category**: Smartphone

Click "Create Product" button

**Expected**: Product appears in list

### 4. Verify in Database
```bash
psql -U postgres -d techdb

SELECT * FROM tech_products;
```

**Expected**: One row with product data

---

## Manual Testing Guide

### Route Testing

#### Test 1: Homepage Redirect
```bash
curl -L http://localhost:8000/
```
**Expected**: Redirects to `/products` page

#### Test 2: List Products (HTML)
```bash
curl http://localhost:8000/products
```
**Expected**: HTML page with product list

#### Test 3: Create Product (API)
```bash
curl -X POST http://localhost:8000/products \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Samsung Galaxy S24",
    "brand": "Samsung",
    "category": "Smartphone"
  }'
```
**Expected**: JSON response with product data
```json
{
  "product_id": 2,
  "name": "Samsung Galaxy S24",
  "brand": "Samsung",
  "category": "Smartphone",
  "created_at": "2026-03-24T06:10:52.123456"
}
```

#### Test 4: Get Product Detail (HTML)
```bash
curl http://localhost:8000/products/1
```
**Expected**: HTML page with product info and sync button

#### Test 5: Sync Videos (API with YouTube API)
```bash
curl -X POST http://localhost:8000/products/1/sync \
  -H "Content-Type: application/json" \
  -d '{"max_results": 3}'
```
**Expected**: JSON response with counts
```json
{
  "status": "success",
  "videos_count": 3,
  "comments_count": 45
}
```

**Note**: Requires valid YOUTUBE_API_KEY in .env

#### Test 6: Get Video Detail (HTML)
```bash
# First, sync a video (Test 5)
# Then get the video_id from database

curl http://localhost:8000/products/1/videos/{video_id}
```
**Expected**: HTML page with video analysis and sentiment

---

## Database Testing

### Test Initial Schema
```sql
-- Connect to database
psql -U postgres -d techdb

-- Check tables exist
\dt

-- Verify indexes
\di
```

**Expected output**:
```
                    List of relations
 Schema |          Name           | Type  |  Owner
--------+-------------------------+-------+----------
 public | comment_sentiments      | table | postgres
 public | comments                | table | postgres
 public | tech_products           | table | postgres
 public | videos                  | table | postgres
 public | idx_comments_video      | index | postgres
 public | idx_sentiments_comment  | index | postgres
 public | idx_videos_product      | index | postgres
```

### Test Data Insertion
```sql
-- Insert test product
INSERT INTO tech_products (name, brand, category)
VALUES ('Test Product', 'Test Brand', 'Test Category')
RETURNING product_id;

-- Verify insertion
SELECT * FROM tech_products;
```

### Test Foreign Keys
```sql
-- This should fail (invalid product_id)
INSERT INTO videos (video_id, product_id, title)
VALUES ('test-vid-123', 999, 'Test Video');

-- Error expected:
-- ERROR:  insert or update on table "videos" violates foreign key constraint
```

### Test Cascading Delete
```sql
-- Get a product_id
SELECT product_id FROM tech_products LIMIT 1;

-- Delete product
DELETE FROM tech_products WHERE product_id = 1;

-- Verify cascade - videos should be deleted too
SELECT * FROM videos WHERE product_id = 1;
-- Should return 0 rows
```

---

## Sentiment Analysis Testing

### Test Positive Sentiment
```python
from main_youtube_analysis import analyze_sentiment

# Test positive keywords
tests = [
    "This is great, I love it!",
    "Best product ever, highly recommend",
    "Amazing quality and performance",
]

for text in tests:
    label, score = analyze_sentiment(text)
    print(f"'{text}' → {label} ({score})")
```

**Expected**: All positive with 0.85 score

### Test Negative Sentiment
```python
tests = [
    "This is terrible, hate it",
    "Worst phone ever, so broken",
    "Disappointing quality, want refund",
]

for text in tests:
    label, score = analyze_sentiment(text)
    print(f"'{text}' → {label} ({score})")
```

**Expected**: All negative with 0.85 score

### Test Neutral Sentiment
```python
tests = [
    "The phone is ok",
    "It's a phone",
    "Comes with screen and battery",
]

for text in tests:
    label, score = analyze_sentiment(text)
    print(f"'{text}' → {label} ({score})")
```

**Expected**: All neutral with 0.5 score

---

## Product Relatedness Testing

### Test Product Related Detection
```python
from main_youtube_analysis import is_product_related

# Should be True (contains product name)
assert is_product_related("iPhone is great", "iPhone") == True

# Should be True (contains keyword)
assert is_product_related("Great specs and battery life") == True
assert is_product_related("Price is reasonable") == True
assert is_product_related("Camera quality is excellent") == True

# Should be False (no match)
assert is_product_related("Just a random comment") == False
assert is_product_related("Hello world") == False

print("✓ All product relatedness tests passed")
```

**Expected**: All assertions pass

---

## YouTube API Testing

### Test Video Fetching
```python
from main_youtube_analysis import fetch_product_videos

# Requires valid YOUTUBE_API_KEY
videos = fetch_product_videos("iPhone 15 Pro", max_results=3)

print(f"Found {len(videos)} videos")
for video in videos:
    print(f"  - {video['title']}")
    print(f"    Views: {video['view_count']}")
    print(f"    Comments: {video['comment_count']}")
```

**Expected**: 
- Returns list of video dicts
- Each dict has required fields (video_id, title, view_count, etc.)
- Fields have correct data types

### Test Comment Fetching
```python
from main_youtube_analysis import fetch_video_comments

# Use a real video_id from previous test
video_id = "dQw4w9WgXcQ"  # Example
comments = fetch_video_comments(video_id, max_pages=1)

print(f"Found {len(comments)} comments")
for comment in comments[:3]:  # Show first 3
    print(f"  - {comment['text_raw'][:60]}...")
```

**Expected**:
- Returns list of comment dicts
- Each dict has comment_id and text_raw
- Comments contain actual text

---

## Web UI Testing

### Test Dashboard
1. Navigate to `http://localhost:8000`
2. Verify:
   - [ ] Title "Tech Products Dashboard" displays
   - [ ] "Add New Product" form visible
   - [ ] Product list area (empty initially)
   - [ ] CSS styling applied (colors, fonts)

### Test Product Creation Form
1. Fill form with:
   - Name: "Test Product"
   - Brand: "Test Brand"
   - Category: "Test"
2. Click "Create Product"
3. Verify:
   - [ ] Form clears
   - [ ] New product appears in list
   - [ ] Product is clickable

### Test Product Detail Page
1. Click product name to go to detail page
2. Verify:
   - [ ] Product info displays (name, brand, category)
   - [ ] "Sync Videos" button visible
   - [ ] No videos shown initially
   - [ ] Back link works

### Test Video Sync (with YouTube API)
1. Click "Sync Videos from YouTube" button
2. Verify:
   - [ ] Button becomes disabled
   - [ ] Status message shows "Syncing..."
   - [ ] After 30-60 seconds: Success message
   - [ ] Page reloads with videos
   - [ ] Thumbnail images load

### Test Video Table
1. After sync, verify:
   - [ ] Video thumbnails visible
   - [ ] Titles clickable
   - [ ] View/like/comment counts show
   - [ ] All videos have data

### Test Video Detail Page
1. Click video title
2. Verify:
   - [ ] Video title displays
   - [ ] YouTube link functional
   - [ ] Stats display (views, likes, comments)
   - [ ] Sentiment boxes show (positive, neutral, negative)
   - [ ] Comments display with sentiment labels
   - [ ] Back link works

---

## Performance Testing

### Database Query Performance
```sql
-- Time a large query
\timing on

SELECT * FROM videos WHERE product_id = 1;
SELECT * FROM comments WHERE video_id = 'test-id';
SELECT COUNT(*) FROM comment_sentiments;

\timing off
```

**Expected**: Queries return in <100ms (with indexes)

### API Response Time
```bash
# Time API request
time curl http://localhost:8000/products

# Time product creation
time curl -X POST http://localhost:8000/products \
  -H "Content-Type: application/json" \
  -d '{"name": "Test", "brand": "Test", "category": "Test"}'
```

**Expected**: <500ms response time

---

## Error Handling Testing

### Test Invalid Product ID
```bash
curl http://localhost:8000/products/9999
```
**Expected**: 404 error with "Product not found"

### Test Invalid Video ID
```bash
curl http://localhost:8000/products/1/videos/invalid-id
```
**Expected**: 404 error with "Video not found"

### Test Missing Required Fields
```bash
curl -X POST http://localhost:8000/products \
  -H "Content-Type: application/json" \
  -d '{"brand": "Test"}'
```
**Expected**: 400 error with "Product name is required"

### Test Database Connection Failure
1. Stop PostgreSQL
2. Try to create product
**Expected**: Connection error in logs

---

## Automated Test Suite

### Run All Tests
```bash
# Create test_youtube_analysis.py with pytest
pip install pytest

# Run tests
pytest test_youtube_analysis.py -v
```

### Example Test File
```python
import pytest
from main_youtube_analysis import (
    analyze_sentiment,
    is_product_related,
    get_connection,
    query_all,
)

def test_positive_sentiment():
    label, score = analyze_sentiment("This is great, love it")
    assert label == "positive"
    assert score > 0.8

def test_negative_sentiment():
    label, score = analyze_sentiment("This is terrible, hate it")
    assert label == "negative"
    assert score > 0.8

def test_neutral_sentiment():
    label, score = analyze_sentiment("This is a phone")
    assert label == "neutral"
    assert score <= 0.5

def test_product_related():
    assert is_product_related("iPhone is great", "iPhone") == True
    assert is_product_related("Great specs") == True
    assert is_product_related("Random text") == False

def test_database_connection():
    """Test database connection works"""
    conn = get_connection()
    assert conn is not None
    conn.close()

def test_tables_exist():
    """Test all required tables exist"""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT table_name FROM information_schema.tables 
        WHERE table_schema = 'public'
    """)
    tables = [row[0] for row in cursor.fetchall()]
    
    required = ['tech_products', 'videos', 'comments', 'comment_sentiments']
    for table in required:
        assert table in tables
    
    conn.close()
```

---

## Checklist for Complete Testing

### Pre-Deployment Checks
- [ ] All routes return expected responses (Tests 1-6)
- [ ] Database schema is correct (Schema tests)
- [ ] Sentiment analysis works for all types (Sentiment tests)
- [ ] Product relatedness detection works (Relatedness tests)
- [ ] YouTube API integration works (API tests)
- [ ] Web UI displays correctly (UI tests)
- [ ] Error handling works (Error tests)
- [ ] Performance is acceptable (Performance tests)

### Security Checks
- [ ] .env file not committed to git
- [ ] No API keys hardcoded
- [ ] SQL queries use parameterized inputs
- [ ] No sensitive data in logs

### Database Checks
- [ ] All tables created
- [ ] All indexes created
- [ ] Foreign keys work
- [ ] Cascading delete works

---

## Troubleshooting Test Failures

### API Returns 500 Error
```bash
# Check application logs
tail -f app.log

# Check database connection
psql -U postgres -d techdb -c "SELECT 1"
```

### YouTube API Returns 401
```bash
# Check API key
echo $YOUTUBE_API_KEY

# Verify in .env file
cat .env
```

### Database Tests Fail
```bash
# Check connection
psql -U postgres -d techdb

# Check tables
\dt

# Check indexes
\di
```

### Sentiment Tests Fail
- Review keyword lists in `analyze_sentiment()`
- Test with exact keyword matching
- Check case sensitivity

---

## Test Report Template

Use this to document your testing:

```
TEST EXECUTION REPORT
Date: 2026-03-24
Tester: [Your Name]

ROUTE TESTS: ✅ PASSED
  - Homepage redirect: ✓
  - List products: ✓
  - Create product: ✓
  - Product detail: ✓
  - Video sync: ✓ (requires YouTube API)
  - Video detail: ✓

DATABASE TESTS: ✅ PASSED
  - Schema valid: ✓
  - Indexes created: ✓
  - Foreign keys work: ✓
  - Cascading delete: ✓

SENTIMENT TESTS: ✅ PASSED
  - Positive detection: ✓
  - Negative detection: ✓
  - Neutral detection: ✓

PRODUCT RELATEDNESS: ✅ PASSED
  - Product name match: ✓
  - Keyword match: ✓
  - Non-match detection: ✓

WEB UI TESTS: ✅ PASSED
  - Dashboard displays: ✓
  - Form works: ✓
  - Product list: ✓
  - Video table: ✓
  - Sentiment display: ✓

ERROR HANDLING: ✅ PASSED
  - Invalid product ID: ✓
  - Invalid video ID: ✓
  - Missing fields: ✓
  - DB connection failure: ✓

OVERALL: ✅ READY FOR PRODUCTION

Issues Found: None
Performance: Acceptable
Security: Compliant
```

---

Last Updated: March 2026
