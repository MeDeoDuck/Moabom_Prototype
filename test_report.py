#!/usr/bin/env python
"""Test build_comment_sentiment_report function."""

import sys
sys.path.insert(0, '.')

import main_youtube_analysis as m
from dotenv import load_dotenv

load_dotenv()

print(f'genai module: {m.genai}')
print(f'GEMINI_API_KEY: {m.GEMINI_API_KEY[:20]}...' if m.GEMINI_API_KEY else 'None')
print(f'GEMINI_MODEL: {m.GEMINI_MODEL}')
print()

# Use the video we found
video_id = 'beIeDDsdcys'
product_name = '삼성 갤럭시 S21+'

print(f'Testing build_comment_sentiment_report for video: {video_id}')
print(f'Product: {product_name}')
print('=' * 60)

try:
    result = m.build_comment_sentiment_report(video_id, product_name)
    
    if result:
        print(f'✓ Report generated successfully!')
        print(f'\nReport (first 500 chars):')
        print(result[:500])
    else:
        print('✗ Function returned None')
        print('\nDebugging info:')
        print(f'  genai is None: {m.genai is None}')
        print(f'  GEMINI_API_KEY is empty: {not m.GEMINI_API_KEY}')
        
except Exception as e:
    import traceback
    print(f'✗ Exception raised: {e}')
    traceback.print_exc()
