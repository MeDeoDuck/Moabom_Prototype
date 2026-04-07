"""
YouTube transcript fetching service with retry logic
"""
from typing import Optional, Dict, Any
import time
import json
import yt_dlp
import requests


def fetch_video_transcript(video_id: str) -> Optional[Dict[str, Any]]:
    """
    Fetch transcript in-memory with smart retry logic on 429.
    - yt-dlp extracts caption URLs only (no video download)
    - Fetch content with requests, parse in-memory
    - Exponential backoff on 429 errors
    - Only try preferred languages/formats
    """
    print(f"[TRANSCRIPT] Fetching for video_id={video_id}")
    
    def parse_json3(content: str) -> Optional[str]:
        """Parse JSON3 caption format, return text or None."""
        try:
            data = json.loads(content)
            text_parts = []
            if 'events' in data:
                for event in data['events']:
                    if 'segs' in event:
                        for seg in event['segs']:
                            if 'utf8' in seg:
                                text_parts.append(seg['utf8'])
            return " ".join(text_parts).strip() if text_parts else None
        except (json.JSONDecodeError, KeyError, TypeError) as e:
            print(f"[TRANSCRIPT] JSON3 parse error: {e}")
            return None
    
    def parse_vtt(content: str) -> Optional[str]:
        """Parse VTT caption format, return text or None."""
        lines = content.split('\n')
        text_parts = []
        for line in lines:
            line = line.strip()
            if line and not line.startswith('WEBVTT') and '-->' not in line:
                text_parts.append(line)
        return " ".join(text_parts).strip() if text_parts else None
    
    def fetch_with_backoff(url: str, max_retries: int = 3) -> Optional[str]:
        """
        Fetch URL with exponential backoff on 429.
        Returns content on success, None on persistent failure.
        """
        for attempt in range(max_retries):
            try:
                response = requests.get(url, timeout=30)
                
                if response.status_code == 429:
                    wait_time = 2 ** attempt
                    print(f"[TRANSCRIPT] 429 Too Many Requests, retry {attempt + 1}/{max_retries} after {wait_time}s")
                    if attempt < max_retries - 1:
                        time.sleep(wait_time)
                        continue
                    else:
                        print(f"[TRANSCRIPT] Max retries exceeded for URL")
                        return None
                
                response.raise_for_status()
                return response.text
            
            except requests.exceptions.Timeout:
                print(f"[TRANSCRIPT] Timeout on attempt {attempt + 1}")
                if attempt < max_retries - 1:
                    time.sleep(2 ** attempt)
                    continue
                return None
            
            except requests.exceptions.RequestException as e:
                print(f"[TRANSCRIPT] Request error: {e}")
                return None
        
        return None
    
    try:
        url = f"https://www.youtube.com/watch?v={video_id}"
        
        # Extract caption URLs with yt-dlp (metadata only)
        ydl_opts = {
            'quiet': True,
            'no_warnings': True,
            'skip_download': True,
        }
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            print(f"[TRANSCRIPT] Extracting metadata from {url}")
            info = ydl.extract_info(url, download=False)
            
            subtitles_data = info.get('automatic_captions') or info.get('subtitles') or {}
            print(f"[TRANSCRIPT] Available languages: {list(subtitles_data.keys())}")
        
        transcript_text = None
        language_code = None
        
        # Try preferred languages in order
        for lang in ['ko', 'en']:
            if lang not in subtitles_data or not subtitles_data[lang]:
                continue
            
            print(f"[TRANSCRIPT] Trying language: {lang}")
            
            # Only try preferred formats
            preferred_formats = ['json3', 'vtt']
            
            for subtitle_item in subtitles_data[lang]:
                if not isinstance(subtitle_item, dict) or 'url' not in subtitle_item:
                    continue
                
                subtitle_url = subtitle_item['url']
                ext = subtitle_item.get('ext', '')
                
                # Skip if not a preferred format
                if ext not in preferred_formats:
                    continue
                
                print(f"[TRANSCRIPT] Fetching {lang}/{ext}: {subtitle_url[:60]}...")
                
                # Fetch with exponential backoff
                content = fetch_with_backoff(subtitle_url)
                if not content:
                    continue
                
                # Parse based on format
                if ext == 'json3':
                    transcript_text = parse_json3(content)
                elif ext == 'vtt':
                    transcript_text = parse_vtt(content)
                
                if transcript_text:
                    language_code = lang
                    print(f"[TRANSCRIPT] SUCCESS: {len(transcript_text)} chars, language={lang}, format={ext}")
                    break
            
            # Break outer loop on success
            if transcript_text:
                break
        
        if not transcript_text:
            print(f"[TRANSCRIPT] No transcript available")
            return None
        
        return {
            "transcript_text": transcript_text,
            "language_code": language_code,
            "segment_count": len(transcript_text.split()),
        }
            
    except Exception as e:
        print(f"[TRANSCRIPT] Failed: {type(e).__name__}: {str(e)[:150]}")
        import traceback
        traceback.print_exc()
        return None
