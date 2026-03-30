#!/usr/bin/env python
"""Debug script to check comment data and sentiment labels."""

import psycopg2
from psycopg2.extras import RealDictCursor
from dotenv import load_dotenv
import os

load_dotenv()
DATABASE_URL = os.getenv('DATABASE_URL')

try:
    conn = psycopg2.connect(DATABASE_URL)
    cur = conn.cursor(cursor_factory=RealDictCursor)
    
    # Find a video WITH comments
    cur.execute('''
        SELECT v.video_id, v.title, COUNT(c.comment_id) as comment_count
        FROM videos v
        LEFT JOIN comments c ON v.video_id = c.video_id
        GROUP BY v.video_id, v.title
        HAVING COUNT(c.comment_id) > 0
        ORDER BY COUNT(c.comment_id) DESC
        LIMIT 1
    ''')
    video = cur.fetchone()
    if video:
        print(f'Found video with comments: {video["video_id"]}')
        print(f'Title: {video["title"][:60]}')
        print(f'Total comments: {video["comment_count"]}')
        video_id = video['video_id']
        
        # Check product-related comments
        cur.execute('SELECT COUNT(*) as cnt FROM comments WHERE video_id = %s AND is_product_related = TRUE', (video_id,))
        result = cur.fetchone()
        print(f'Product-related: {result["cnt"]}')
        
        # Check if sentiment analysis has been done
        cur.execute('''
            SELECT COUNT(*) as cnt 
            FROM comments c 
            LEFT JOIN comment_sentiments cs ON c.comment_id = cs.comment_id
            WHERE c.video_id = %s AND cs.comment_id IS NOT NULL
        ''', (video_id,))
        result = cur.fetchone()
        print(f'Comments with sentiment analysis: {result["cnt"]}')
        
        # Sample actual data
        cur.execute('''
            SELECT c.comment_id, c.text_raw, c.is_product_related, cs.sentiment_label, cs.sentiment_score
            FROM comments c
            LEFT JOIN comment_sentiments cs ON c.comment_id = cs.comment_id
            WHERE c.video_id = %s
            LIMIT 5
        ''', (video_id,))
        samples = cur.fetchall()
        print(f'\nFirst 5 comments:')
        for i, s in enumerate(samples):
            label = s["sentiment_label"] or "None"
            text = s["text_raw"][:50] if s["text_raw"] else "No text"
            related = s["is_product_related"]
            print(f'  {i+1}. [{label}] [product_related={related}] {text}...')
        
        # Test the actual query from build_comment_sentiment_report
        print('\n=== Testing build_comment_sentiment_report Query ===')
        cur.execute('''
            SELECT cs.sentiment_label, c.text_raw
            FROM comments c
            LEFT JOIN comment_sentiments cs ON c.comment_id = cs.comment_id
            WHERE c.video_id = %s AND c.is_product_related = TRUE
            ORDER BY cs.sentiment_label, c.created_at DESC
        ''', (video_id,))
        
        comments = cur.fetchall()
        print(f'Query returned {len(comments)} rows')
        
        # Map by sentiment
        sentiment_map = {"positive": [], "neutral": [], "negative": []}
        for comment in comments:
            label = comment.get("sentiment_label", "neutral") or "neutral"
            text = comment.get("text_raw", "")
            if text and label in sentiment_map:
                sentiment_map[label].append(text)
        
        print(f'Positive: {len(sentiment_map["positive"])} comments')
        print(f'Neutral: {len(sentiment_map["neutral"])} comments')
        print(f'Negative: {len(sentiment_map["negative"])} comments')
    else:
        print('No videos with comments found!')
    
    cur.close()
    conn.close()
except Exception as e:
    import traceback
    print(f'Error: {e}')
    traceback.print_exc()
