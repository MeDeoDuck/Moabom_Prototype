"""
YouTube comment fetching service
"""
from typing import List, Dict
import httpx
from scripts.config import YOUTUBE_API_KEY


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
