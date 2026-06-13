"""
YouTube video search and statistics service
"""
from typing import List, Dict, Any
import httpx
from scripts.youtube.api_keys import get_with_rotation, has_keys


def fetch_product_videos(product_name: str, max_results: int = 5) -> List[Dict[str, Any]]:
    """
    Search YouTube for videos about a product and fetch their statistics.
    Returns list of dicts: {video_id, title, description, published_at, thumbnail_url, view_count, like_count, comment_count}
    """
    if not has_keys():
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
        }
        search_resp = get_with_rotation(client, search_url, search_params)
        search_data = search_resp.json()

        video_ids = [item["id"]["videoId"] for item in search_data.get("items", [])]
        if not video_ids:
            return []

        # Step 2: Get video statistics
        videos_url = "https://www.googleapis.com/youtube/v3/videos"
        videos_params = {
            "part": "snippet,statistics",
            "id": ",".join(video_ids),
        }
        videos_resp = get_with_rotation(client, videos_url, videos_params)
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
