"""
YouTube video search and statistics service
"""
from typing import List, Dict, Any
import httpx
from scripts.config import YOUTUBE_API_KEY


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
