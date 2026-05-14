"""
YouTube transcript fetching service with retry logic
"""
from typing import Optional, Dict, Any
import os
import time
import json
import requests
import yt_dlp

from scripts.youtube.cookies import apply_to_ytdlp_opts, make_session


def _fetch_via_worker(video_id: str, base_url: str, token: str) -> Optional[Dict[str, Any]]:
    """POST to fetch worker /transcript. Returns dict on 200, None otherwise.

    Caller distinguishes:
      - dict          → use directly, skip local fallback
      - None + 404    → worker says no transcript; local fallback unlikely to help
      - None + 5xx/timeout → worker problem; local fallback worth trying
    The 404-vs-5xx distinction is encoded by the second return value.
    """
    url = base_url.rstrip("/") + "/transcript"
    headers = {"Authorization": f"Bearer {token}"}
    payload = {"video_id": video_id}

    last_status: Optional[int] = None
    for attempt in range(3):
        try:
            resp = requests.post(url, json=payload, headers=headers, timeout=60)
            last_status = resp.status_code
            if resp.status_code == 200:
                data = resp.json()
                return {
                    "transcript_text": data["transcript_text"],
                    "language_code": data["language_code"],
                    "segment_count": data["segment_count"],
                }
            if resp.status_code == 404:
                print(f"[TRANSCRIPT] worker: no transcript for {video_id}")
                return None
            if 500 <= resp.status_code < 600:
                print(f"[TRANSCRIPT] worker 5xx ({resp.status_code}), retry {attempt + 1}/3")
                time.sleep(2 ** attempt)
                continue
            # 4xx other than 404 → config/auth error; don't retry
            print(f"[TRANSCRIPT] worker client error {resp.status_code}: {resp.text[:200]}")
            return None
        except requests.exceptions.RequestException as e:
            print(f"[TRANSCRIPT] worker request error attempt {attempt + 1}/3: {type(e).__name__}: {e}")
            time.sleep(2 ** attempt)
            continue

    # All retries failed with 5xx/timeout — caller should try local fallback.
    print(f"[TRANSCRIPT] worker exhausted retries (last_status={last_status})")
    return None


def fetch_video_transcript(video_id: str) -> Optional[Dict[str, Any]]:
    """
    Fetch transcript in-memory with smart retry logic on 429.
    - If YOUTUBE_FETCH_WORKER_URL is set, try the residential-IP worker first
      and fall back to the local yt-dlp path only on 5xx/timeout (not 404).
    - yt-dlp extracts caption URLs only (no video download)
    - Fetch content with requests, parse in-memory
    - Exponential backoff on 429 errors
    - Only try preferred languages/formats
    """
    print(f"[TRANSCRIPT] Fetching for video_id={video_id}")

    worker_url = os.environ.get("YOUTUBE_FETCH_WORKER_URL")
    worker_token = os.environ.get("YOUTUBE_FETCH_WORKER_TOKEN")
    if worker_url and worker_token:
        print(f"[TRANSCRIPT] Trying worker first: {worker_url}")
        result = _fetch_via_worker(video_id, worker_url, worker_token)
        if result is not None:
            print(f"[TRANSCRIPT] worker SUCCESS: {len(result['transcript_text'])} chars")
            return result
        # _fetch_via_worker returned None either via 404 or exhausted 5xx retries.
        # In both cases we fall through to the local path; 404 fallback is cheap
        # if cookies happen to be valid, and the local path returns None fast
        # when no captions exist.
        print(f"[TRANSCRIPT] Falling back to local fetch")
    
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
    
    session = make_session()

    def fetch_with_backoff(url: str, max_retries: int = 3) -> Optional[str]:
        """
        Fetch URL with exponential backoff on 429.
        Returns content on success, None on persistent failure.
        """
        for attempt in range(max_retries):
            try:
                response = session.get(url, timeout=30)
                
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
        
        # Extract caption URLs with yt-dlp (metadata only).
        # process=False avoids the format/n-challenge pipeline that throws
        # "No video formats found" under cookie auth (yt-dlp wiki: PO Token).
        ydl_opts: Dict[str, Any] = {
            'quiet': True,
            'no_warnings': True,
            'skip_download': True,
        }
        apply_to_ytdlp_opts(ydl_opts)

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            print(f"[TRANSCRIPT] Extracting metadata from {url}")
            info = ydl.extract_info(url, download=False, process=False)
            
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
