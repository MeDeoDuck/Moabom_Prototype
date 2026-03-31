"""
Product-centric YouTube Analysis Service
FastAPI + PostgreSQL + YouTube Data API v3
"""

import os
import json
import random
import re
import textwrap
from typing import Optional, List, Dict, Any
from datetime import datetime
from io import BytesIO
from pathlib import Path

import psycopg2
from psycopg2.extras import RealDictCursor
from dotenv import load_dotenv

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
import httpx
import uvicorn
from prompt_manager import build_transcript_report_prompt, build_comment_sentiment_report_prompt

try:
    from youtube_transcript_api import YouTubeTranscriptApi
except ImportError:
    YouTubeTranscriptApi = None

try:
    import anthropic
except ImportError:
    anthropic = None

# Load environment variables
load_dotenv()
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/techdb")
YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY", "")
CLAUDE_API_KEY = os.getenv("CLAUDE_API_KEY", "")
CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "claude-3-5-sonnet-20241022")

# ============================================================================
# DATABASE LAYER
# ============================================================================

def get_connection():
    """Get a raw PostgreSQL connection."""
    return psycopg2.connect(DATABASE_URL)


def init_db():
    """Initialize database schema on startup."""
    conn = get_connection()
    cursor = conn.cursor()
    
    # Create tables
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS tech_products (
            product_id   SERIAL PRIMARY KEY,
            name         VARCHAR(255) NOT NULL,
            brand        VARCHAR(255),
            category     VARCHAR(255),
            created_at   TIMESTAMP DEFAULT NOW()
        );
    """)
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS videos (
            video_id     VARCHAR(64) PRIMARY KEY,
            product_id   INT NOT NULL REFERENCES tech_products(product_id) ON DELETE CASCADE,
            title        VARCHAR(255) NOT NULL,
            description  TEXT,
            published_at TIMESTAMP,
            thumbnail_url TEXT,
            view_count   BIGINT,
            like_count   BIGINT,
            comment_count BIGINT,
            created_at   TIMESTAMP DEFAULT NOW()
        );
    """)
    
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_videos_product ON videos(product_id);
    """)
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS comments (
            comment_id        VARCHAR(64) PRIMARY KEY,
            video_id          VARCHAR(64) NOT NULL REFERENCES videos(video_id) ON DELETE CASCADE,
            parent_id         VARCHAR(64),
            text_raw          TEXT NOT NULL,
            is_product_related BOOLEAN,
            created_at        TIMESTAMP DEFAULT NOW()
        );
    """)
    
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_comments_video ON comments(video_id);
    """)
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS comment_sentiments (
            id               SERIAL PRIMARY KEY,
            comment_id       VARCHAR(64) NOT NULL REFERENCES comments(comment_id) ON DELETE CASCADE,
            sentiment_label  VARCHAR(16) NOT NULL,
            sentiment_score  NUMERIC(4,3),
            created_at       TIMESTAMP DEFAULT NOW()
        );
    """)
    
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_sentiments_comment ON comment_sentiments(comment_id);
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS video_transcripts (
            video_id        VARCHAR(64) PRIMARY KEY REFERENCES videos(video_id) ON DELETE CASCADE,
            transcript_text TEXT NOT NULL,
            language_code   VARCHAR(16),
            segment_count   INT,
            source          VARCHAR(32) DEFAULT 'youtube_transcript_api',
            updated_at      TIMESTAMP DEFAULT NOW()
        );
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS video_reports (
            video_id            VARCHAR(64) PRIMARY KEY REFERENCES videos(video_id) ON DELETE CASCADE,
            transcript_report   TEXT,
            comment_report      TEXT,
            updated_at          TIMESTAMP DEFAULT NOW()
        );
    """)
    
    conn.commit()
    cursor.close()
    conn.close()
    print("✓ Database initialized")


def query_one(sql: str, params: tuple = ()) -> Optional[Dict]:
    """Execute query and return single row as dict."""
    conn = get_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)
    cursor.execute(sql, params)
    result = cursor.fetchone()
    cursor.close()
    conn.close()
    return result


def query_all(sql: str, params: tuple = ()) -> List[Dict]:
    """Execute query and return all rows as dicts."""
    conn = get_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)
    cursor.execute(sql, params)
    results = cursor.fetchall()
    cursor.close()
    conn.close()
    return results


def execute_insert(sql: str, params: tuple = ()) -> int:
    """Execute INSERT and return inserted ID (for SERIAL columns)."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(sql, params)
    result_id = cursor.fetchone()[0] if cursor.description else None
    conn.commit()
    cursor.close()
    conn.close()
    return result_id


def execute_update(sql: str, params: tuple = ()) -> int:
    """Execute UPDATE/DELETE and return row count."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(sql, params)
    row_count = cursor.rowcount
    conn.commit()
    cursor.close()
    conn.close()
    return row_count


# ============================================================================
# YOUTUBE API LAYER
# ============================================================================

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


def fetch_video_transcript(video_id: str) -> Optional[Dict[str, Any]]:
    """
    Fetch transcript text for a video using youtube-transcript-api.
    Returns dict with transcript_text, language_code, segment_count or None.
    """
    if YouTubeTranscriptApi is None:
        return None

    # Try Korean first, then English, then automatic selection.
    language_candidates = [
        ["ko"],
        ["en"],
        ["ko", "en"],
    ]

    transcript_items = None
    language_code = None

    for languages in language_candidates:
        try:
            transcript_items = YouTubeTranscriptApi.get_transcript(video_id, languages=languages)
            language_code = languages[0]
            break
        except Exception:
            continue

    if not transcript_items:
        return None

    cleaned_parts = [item.get("text", "").strip() for item in transcript_items]
    transcript_text = " ".join(part for part in cleaned_parts if part)
    if not transcript_text:
        return None

    return {
        "transcript_text": transcript_text,
        "language_code": language_code,
        "segment_count": len(transcript_items),
    }


def build_transcript_report_heuristic(transcript_text: str) -> str:
    """
    Build a detailed product analysis report from transcript:
    1. Product Description (features, specs, capabilities mentioned)
    2. Evaluation & Review (likes, dislikes, recommendations)
    3. Key Takeaways
    """
    normalized = re.sub(r"\s+", " ", transcript_text or "").strip()
    if not normalized:
        return "No transcript content available."

    # Split into sentences
    sentences = re.split(r"(?<=[.!?])\s+", normalized)
    sentences = [s.strip() for s in sentences if len(s.strip()) > 5]

    if not sentences:
        return "Transcript too short to analyze."

    # ============================================================================
    # 1. PRODUCT DESCRIPTION EXTRACTION
    # ============================================================================
    feature_keywords = {
        "design", "feature", "spec", "performance", "battery", "camera", "display",
        "processor", "memory", "storage", "screen", "build", "material", "size",
        "weight", "quality", "speed", "power", "sound", "audio", "video",
        "resolution", "fps", "refresh", "rate", "connector", "port", "interface",
        "기능", "디자인", "성능", "배터리", "카메라", "디스플레이", "프로세서",
        "메모리", "저장", "화면", "품질", "속도"
    }
    
    description_sentences = []
    for sentence in sentences:
        sentence_lower = sentence.lower()
        if any(kw in sentence_lower for kw in feature_keywords):
            description_sentences.append(sentence)
    
    description_sentences = description_sentences[:3]  # Top 3 sentences about features

    # ============================================================================
    # 2. EVALUATION & SENTIMENT EXTRACTION
    # ============================================================================
    positive_indicators = {
        "good", "great", "excellent", "amazing", "awesome", "best", "perfect",
        "love", "like", "recommend", "worth", "impressed", "impressive",
        "beautiful", "smooth", "fast", "excellent", "outstanding",
        "좋다", "훌륭하다", "추천", "완벽", "훌륭", "빠르다", "훌륭한"
    }
    
    negative_indicators = {
        "bad", "poor", "terrible", "awful", "horrible", "worst", "useless",
        "hate", "dislike", "problem", "issue", "broken", "disappointing",
        "waste", "regret", "slow", "expensive", "cheap", "fragile",
        "나쁘다", "문제", "느리다", "비싸다", "싼", "약하다"
    }
    
    upgrade_phrases = {
        "upgrade", "improve", "better", "compare", "vs", "difference",
        "instead", "alternative", "choose", "pick", "go for",
        "업그레이드", "개선", "더 나음", "비교", "차이", "선택"
    }
    
    positive_sentences = []
    negative_sentences = []
    upgrade_sentences = []
    
    for sentence in sentences:
        sentence_lower = sentence.lower()
        pos_count = sum(1 for word in positive_indicators if word in sentence_lower)
        neg_count = sum(1 for word in negative_indicators if word in sentence_lower)
        upg_count = sum(1 for word in upgrade_phrases if word in sentence_lower)
        
        if pos_count > neg_count:
            positive_sentences.append(sentence)
        elif neg_count > pos_count:
            negative_sentences.append(sentence)
        
        if upg_count > 0:
            upgrade_sentences.append(sentence)
    
    # ============================================================================
    # 3. KEYWORD EXTRACTION
    # ============================================================================
    token_candidates = re.findall(r"[A-Za-z0-9가-힣]{2,}", normalized.lower())
    stopwords = {
        "this", "that", "with", "from", "have", "will", "your", "about", "there",
        "would", "they", "them", "then", "into", "here", "just", "also", "than",
        "when", "what", "the", "and", "for", "but", "are", "has", "been", "is",
        "있는", "그리고", "합니다", "하는", "에서", "으로", "하는데", "것", "수"
    }
    
    filtered_tokens = [t for t in token_candidates if t not in stopwords and len(t) >= 2]
    token_counts: Dict[str, int] = {}
    for token in filtered_tokens:
        token_counts[token] = token_counts.get(token, 0) + 1
    
    top_keywords = sorted(token_counts.items(), key=lambda x: x[1], reverse=True)[:6]

    # ============================================================================
    # 4. BUILD REPORT
    # ============================================================================
    report_lines = [
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        "PRODUCT ANALYSIS REPORT FROM VIDEO TRANSCRIPT",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        "",
    ]
    
    # Product Description
    report_lines.extend([
        "📋 PRODUCT DESCRIPTION",
        "-" * 40,
    ])
    
    if description_sentences:
        for idx, sent in enumerate(description_sentences, 1):
            # Truncate long sentences
            truncated = (sent[:150] + "...") if len(sent) > 150 else sent
            report_lines.append(f"{idx}. {truncated}")
    else:
        report_lines.append("(No specific product features mentioned)")
    
    report_lines.append("")
    
    # Positive Evaluation
    report_lines.extend([
        "👍 POSITIVE POINTS",
        "-" * 40,
    ])
    
    if positive_sentences:
        for idx, sent in enumerate(positive_sentences[:2], 1):
            truncated = (sent[:140] + "...") if len(sent) > 140 else sent
            report_lines.append(f"• {truncated}")
    else:
        report_lines.append("(No positive remarks found)")
    
    report_lines.append("")
    
    # Negative/Concerns
    report_lines.extend([
        "⚠️  CONCERNS & CRITICISMS",
        "-" * 40,
    ])
    
    if negative_sentences:
        for idx, sent in enumerate(negative_sentences[:2], 1):
            truncated = (sent[:140] + "...") if len(sent) > 140 else sent
            report_lines.append(f"• {truncated}")
    else:
        report_lines.append("(No significant concerns mentioned)")
    
    report_lines.append("")
    
    # Upgrade/Comparison Info
    report_lines.extend([
        "🔄 ALTERNATIVES & UPGRADES",
        "-" * 40,
    ])
    
    if upgrade_sentences:
        for idx, sent in enumerate(upgrade_sentences[:2], 1):
            truncated = (sent[:140] + "...") if len(sent) > 140 else sent
            report_lines.append(f"• {truncated}")
    else:
        report_lines.append("(No comparison/upgrade info mentioned)")
    
    report_lines.append("")
    
    # Key Topics/Keywords
    report_lines.extend([
        "🔑 KEY TOPICS MENTIONED",
        "-" * 40,
    ])
    
    if top_keywords:
        keyword_list = ", ".join([f"{k}({c})" for k, c in top_keywords])
        report_lines.append(keyword_list)
    else:
        report_lines.append("N/A")
    
    report_lines.extend([
        "",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        f"Transcript length: {len(normalized)} characters | Sentences analyzed: {len(sentences)}",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
    ])
    
    return "\n".join(report_lines)


def build_transcript_report(transcript_text: str) -> str:
    """
    Build transcript report with Claude first, then fallback to heuristic analysis.
    """
    normalized = re.sub(r"\s+", " ", transcript_text or "").strip()
    if not normalized:
        return "No transcript content available."
    
    # Limit transcript to first 2000 chars to reduce token usage
    normalized = normalized[:2000]

    if anthropic is None or not CLAUDE_API_KEY:
        return build_transcript_report_heuristic(normalized)

    try:
        client = anthropic.Anthropic(api_key=CLAUDE_API_KEY)
        prompt = build_transcript_report_prompt(normalized)

        response = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=300,
            messages=[
                {"role": "user", "content": prompt}
            ]
        )

        llm_text = response.content[0].text if response.content else None
        if llm_text and llm_text.strip():
            return llm_text.strip()
    except Exception:
        pass

    return build_transcript_report_heuristic(normalized)


def analyze_sentiment_batch(comments: List[str], sentiment_type: str, product_name: str) -> str:
    """
    Analyze a batch of comments for a specific sentiment.
    Returns a summary of that sentiment's characteristics.
    """
    if not comments:
        return f"[{sentiment_type} 댓글 없음]"
    
    # Limit to first 3 comments, 100 chars each
    sample = comments[:3]
    sample = [text[:100] for text in sample]
    comments_text = " | ".join(sample)
    
    if anthropic is None or not CLAUDE_API_KEY:
        return f"{sentiment_type} 댓글: {comments_text}"
    
    try:
        client = anthropic.Anthropic(api_key=CLAUDE_API_KEY)
        prompt = (
            f"다음 {product_name} 관련 {sentiment_type} 댓글들의 공통점을 50자 이내로 요약해줘.\\n"
            f"댓글: {comments_text}"
        )
        
        response = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=100,
            messages=[{"role": "user", "content": prompt}]
        )
        
        return response.content[0].text if response.content else f"{sentiment_type} 분석 불가"
    except Exception as e:
        print(f"[ERROR] analyze_sentiment_batch ({sentiment_type}): {e}")
        return f"{sentiment_type}: {comments_text}"


def consolidate_sentiment_reports(positive_summary: str, negative_summary: str, product_name: str) -> str:
    """
    Consolidate individual sentiment summaries into a final report.
    """
    if anthropic is None or not CLAUDE_API_KEY:
        return (
            f"[{product_name} 댓글 반응 기반 평가보고서]\\n"
            f"- 긍정: {positive_summary}\\n"
            f"- 부정: {negative_summary}"
        )
    
    try:
        client = anthropic.Anthropic(api_key=CLAUDE_API_KEY)
        prompt = (
            f"{product_name}에 대한 댓글 분석 결과를 바탕으로 300자 이내의 평가보고서를 작성해줘.\\n"
            f"첫 줄: [댓글 반응 기반 평가보고서]\\n"
            f"긍정 의견: {positive_summary}\\n"
            f"부정 의견: {negative_summary}\\n"
            f"출력: 장단점과 결론만 간단하게"
        )
        
        response = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=300,
            messages=[{"role": "user", "content": prompt}]
        )
        
        return response.content[0].text if response.content else f"[{product_name} 댓글 분석] 긍정: {positive_summary}, 부정: {negative_summary}"
    except Exception as e:
        print(f"[ERROR] consolidate_sentiment_reports: {e}")
        return f"[{product_name} 댓글 반응]\\n- 긍정: {positive_summary}\\n- 부정: {negative_summary}"


def build_comment_sentiment_report(video_id: str, product_name: str = "제품") -> Optional[str]:
    """
    Build comment sentiment analysis report using heuristic analysis.
    No API calls - pure rule-based summarization for cost efficiency.
    """
    try:
        conn = psycopg2.connect(DATABASE_URL)
        cur = conn.cursor(cursor_factory=RealDictCursor)
        
        # Query comments for this video grouped by sentiment_label
        cur.execute("""
            SELECT cs.sentiment_label, c.text_raw
            FROM comments c
            LEFT JOIN comment_sentiments cs ON c.comment_id = cs.comment_id
            WHERE c.video_id = %s AND c.is_product_related = TRUE
            ORDER BY cs.sentiment_label, c.created_at DESC
        """, (video_id,))
        
        comments = cur.fetchall()
        cur.close()
        conn.close()
        
        if not comments:
            return None
        
        # Group comments by sentiment
        sentiment_map = {"positive": [], "neutral": [], "negative": []}
        for comment in comments:
            label = comment.get("sentiment_label", "neutral") or "neutral"
            text = comment.get("text_raw", "")
            if text and label in sentiment_map:
                sentiment_map[label].append(text)
        
        # Build heuristic summary without API calls
        pos_count = len(sentiment_map["positive"])
        neg_count = len(sentiment_map["negative"])
        total = pos_count + len(sentiment_map["neutral"]) + neg_count
        
        if total == 0:
            return None
        
        lines = [
            f"[{product_name} 댓글 반응 분석]",
        ]
        
        # Add sentiment summary
        if pos_count > 0:
            pos_sample = sentiment_map["positive"][:2]
            pos_text = " | ".join(pos_sample)[:100]
            lines.append(f"긍정({pos_count}): {pos_text}")
        
        if neg_count > 0:
            neg_sample = sentiment_map["negative"][:2]
            neg_text = " | ".join(neg_sample)[:100]
            lines.append(f"부정({neg_count}): {neg_text}")
        
        # Add simple conclusion based on ratio
        if pos_count > neg_count * 2:
            lines.append("→ 긍정 반응 우세")
        elif neg_count > pos_count * 2:
            lines.append("→ 부정 반응 우세")
        else:
            lines.append("→ 신중한 검토 필요")
        
        result = "\\n".join(lines)
        return result[:300] if len(result) > 300 else result
        
    except Exception as e:
        print(f"[ERROR] build_comment_sentiment_report: {e}")
        return None


def upsert_video_report(video_id: str, transcript_report: Optional[str] = None, comment_report: Optional[str] = None) -> None:
    """Upsert generated reports for a video."""
    execute_update(
        """INSERT INTO video_reports (video_id, transcript_report, comment_report, updated_at)
           VALUES (%s, %s, %s, NOW())
           ON CONFLICT (video_id)
           DO UPDATE SET
             transcript_report = COALESCE(EXCLUDED.transcript_report, video_reports.transcript_report),
             comment_report = COALESCE(EXCLUDED.comment_report, video_reports.comment_report),
             updated_at = NOW()""",
        (video_id, transcript_report, comment_report),
    )


def render_report_pdf(video_title: str, report_text: str) -> bytes:
    """Render report text into a downloadable PDF."""
    try:
        from reportlab.lib.pagesizes import letter
        from reportlab.pdfgen import canvas
    except ImportError as e:
        raise HTTPException(status_code=500, detail="reportlab is not installed") from e

    buffer = BytesIO()
    c = canvas.Canvas(buffer, pagesize=letter)
    width, height = letter

    y = height - 50
    c.setFont("Helvetica-Bold", 12)
    c.drawString(40, y, f"Video Transcript Report: {video_title[:80]}")
    y -= 24

    c.setFont("Helvetica", 10)
    for paragraph in report_text.split("\n"):
        wrapped_lines = textwrap.wrap(paragraph, width=100, break_long_words=True) if paragraph else [""]
        for line in wrapped_lines:
            if y < 40:
                c.showPage()
                c.setFont("Helvetica", 10)
                y = height - 40
            c.drawString(40, y, line)
            y -= 14

    c.save()
    buffer.seek(0)
    return buffer.read()


# ============================================================================
# SENTIMENT & PRODUCT ANALYSIS
# ============================================================================

def is_product_related(text: str, product_name: str = "") -> bool:
    """
    Simple heuristic to determine if a comment is product-related.
    Checks for product name and common tech keywords.
    """
    text_lower = text.lower()
    
    # Check for product name
    if product_name and product_name.lower() in text_lower:
        return True
    
    # Check for common tech keywords
    keywords = ["price", "spec", "battery", "performance", "quality", "feature", 
                "design", "review", "recommend", "issue", "problem", "bug", "error",
                "upgrade", "worth", "value", "camera", "screen", "cpu", "gpu",
                "ram", "storage", "display", "build", "material"]
    
    for keyword in keywords:
        if keyword in text_lower:
            return True
    
    return False


def analyze_sentiment(text: str) -> tuple[str, float]:
    """
    Simple rule-based sentiment analysis.
    Returns (sentiment_label, sentiment_score)
    """
    text_lower = text.lower()
    
    positive_words = ["good", "love", "great", "excellent", "amazing", "awesome", 
                      "best", "perfect", "fantastic", "wonderful", "brilliant",
                      "recommend", "worth", "impressive", "beautiful", "smooth"]
    
    negative_words = ["bad", "hate", "poor", "terrible", "awful", "horrible",
                      "worst", "useless", "broken", "issue", "problem", "bug",
                      "disappointing", "waste", "regret", "return"]
    
    positive_count = sum(1 for word in positive_words if word in text_lower)
    negative_count = sum(1 for word in negative_words if word in text_lower)
    
    if positive_count > negative_count:
        return ("positive", 0.85)
    elif negative_count > positive_count:
        return ("negative", 0.85)
    else:
        return ("neutral", 0.5)


# ============================================================================
# FASTAPI APP & ROUTES
# ============================================================================

app = FastAPI(title="YouTube Product Analysis Service")

# Ensure templates directory exists
TEMPLATES_DIR = Path("templates")
TEMPLATES_DIR.mkdir(exist_ok=True)

# Templates as strings
TEMPLATE_PRODUCTS = """
<!DOCTYPE html>
<html>
<head>
    <title>Tech Products</title>
    <style>
        body { font-family: Arial, sans-serif; margin: 20px; }
        .container { max-width: 900px; margin: 0 auto; }
        h1 { color: #333; }
        .form-group { margin-bottom: 15px; }
        label { display: block; margin-bottom: 5px; font-weight: bold; }
        input, select { padding: 8px; width: 200px; }
        button { padding: 10px 20px; background: #007bff; color: white; border: none; cursor: pointer; border-radius: 4px; }
        button:hover { background: #0056b3; }
        .product-list { margin-top: 30px; }
        .product-item { padding: 12px; border: 1px solid #ddd; margin-bottom: 10px; border-radius: 4px; }
        .product-item a { color: #007bff; text-decoration: none; }
        .product-item a:hover { text-decoration: underline; }
        .product-meta { font-size: 0.9em; color: #666; margin-top: 5px; }
    </style>
</head>
<body>
    <div class="container">
        <h1>📱 Tech Products Dashboard</h1>
        
        <div>
            <h2>Add New Product</h2>
            <form id="productForm">
                <div class="form-group">
                    <label for="name">Product Name *</label>
                    <input type="text" id="name" name="name" required>
                </div>
                <div class="form-group">
                    <label for="brand">Brand</label>
                    <input type="text" id="brand" name="brand">
                </div>
                <div class="form-group">
                    <label for="category">Category</label>
                    <input type="text" id="category" name="category" placeholder="e.g., Smartphone, Laptop">
                </div>
                <button type="submit">Create Product</button>
            </form>
        </div>
        
        <div class="product-list">
            <h2>Products ({{ products|length }})</h2>
            {% if products %}
                {% for product in products %}
                    <div class="product-item">
                        <strong><a href="/products/{{ product.product_id }}">{{ product.name }}</a></strong>
                        <div class="product-meta">
                            Brand: {{ product.brand or 'N/A' }} | Category: {{ product.category or 'N/A' }}
                        </div>
                    </div>
                {% endfor %}
            {% else %}
                <p>No products yet. Create one above!</p>
            {% endif %}
        </div>
    </div>

    <script>
        document.getElementById('productForm').addEventListener('submit', async (e) => {
            e.preventDefault();
            const data = {
                name: document.getElementById('name').value,
                brand: document.getElementById('brand').value,
                category: document.getElementById('category').value,
            };
            
            try {
                const response = await fetch('/products', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(data),
                });
                
                if (response.ok) {
                    location.reload();
                } else {
                    alert('Error creating product');
                }
            } catch (error) {
                alert('Error: ' + error);
            }
        });
    </script>
</body>
</html>
"""

TEMPLATE_PRODUCT_DETAIL = """
<!DOCTYPE html>
<html>
<head>
    <title>{{ product.name }} - Product Details</title>
    <style>
        body { font-family: Arial, sans-serif; margin: 20px; }
        .container { max-width: 1000px; margin: 0 auto; }
        h1 { color: #333; }
        .product-info { background: #f5f5f5; padding: 15px; border-radius: 4px; margin-bottom: 20px; }
        .product-info p { margin: 5px 0; }
        .sync-btn { padding: 12px 24px; background: #28a745; color: white; border: none; cursor: pointer; border-radius: 4px; font-size: 16px; }
        .sync-btn:hover { background: #218838; }
        .sync-btn:disabled { background: #ccc; cursor: not-allowed; }
        .videos-section { margin-top: 30px; }
        table { width: 100%; border-collapse: collapse; margin-top: 15px; }
        th, td { padding: 12px; text-align: left; border-bottom: 1px solid #ddd; }
        th { background: #007bff; color: white; }
        tr:hover { background: #f5f5f5; }
        .video-title a { color: #007bff; text-decoration: none; }
        .video-title a:hover { text-decoration: underline; }
        .video-thumb { width: 80px; height: 45px; object-fit: cover; border-radius: 3px; }
        .back-link { margin-bottom: 20px; }
        .back-link a { color: #007bff; }
        .sync-row { display: flex; align-items: center; gap: 12px; }
        .sync-progress { width: 280px; height: 8px; background: #e9ecef; border-radius: 999px; overflow: hidden; display: none; }
        .sync-progress.show { display: block; }
        .sync-progress-fill { width: 0%; height: 100%; background: linear-gradient(90deg, #17a2b8, #28a745); transition: width 0.2s ease; }
        .sync-status { font-size: 0.95em; color: #444; min-height: 20px; }
    </style>
</head>
<body>
    <div class="container">
        <div class="back-link">
            <a href="/products">← Back to Products</a>
        </div>
        
        <h1>{{ product.name }}</h1>
        
        <div class="product-info">
            <p><strong>Brand:</strong> {{ product.brand or 'N/A' }}</p>
            <p><strong>Category:</strong> {{ product.category or 'N/A' }}</p>
            <p><strong>Created:</strong> {{ product.created_at }}</p>
        </div>
        
        <div class="sync-row">
            <button class="sync-btn" onclick="syncVideos()" id="syncBtn">🔄 Sync Videos from YouTube</button>
            <div id="syncProgress" class="sync-progress" aria-hidden="true">
                <div id="syncProgressFill" class="sync-progress-fill"></div>
            </div>
            <span id="syncStatus" class="sync-status"></span>
        </div>
        
        <div class="videos-section">
            <h2>Videos ({{ videos|length }})</h2>
            {% if videos %}
                <table>
                    <thead>
                        <tr>
                            <th>Thumbnail</th>
                            <th>Title</th>
                            <th>Views</th>
                            <th>Likes</th>
                            <th>Comments</th>
                        </tr>
                    </thead>
                    <tbody>
                        {% for video in videos %}
                            <tr>
                                <td>
                                    {% if video.thumbnail_url %}
                                        <img src="{{ video.thumbnail_url }}" alt="thumbnail" class="video-thumb">
                                    {% endif %}
                                </td>
                                <td class="video-title">
                                    <a href="/products/{{ product.product_id }}/videos/{{ video.video_id }}">
                                        {{ video.title[:50] }}...
                                    </a>
                                </td>
                                <td>{{ video.view_count }}</td>
                                <td>{{ video.like_count }}</td>
                                <td>{{ video.comment_count }}</td>
                            </tr>
                        {% endfor %}
                    </tbody>
                </table>
            {% else %}
                <p>No videos yet. Click "Sync Videos from YouTube" to fetch them.</p>
            {% endif %}
        </div>
    </div>

    <script>
        async function syncVideos() {
            const btn = document.getElementById('syncBtn');
            const status = document.getElementById('syncStatus');
            const progress = document.getElementById('syncProgress');
            const progressFill = document.getElementById('syncProgressFill');
            let progressValue = 8;
            let timer = null;
            
            btn.disabled = true;
            progress.classList.add('show');
            progressFill.style.width = progressValue + '%';
            status.textContent = 'Syncing...';

            // Simulated progress while waiting for server response.
            timer = setInterval(() => {
                if (progressValue < 90) {
                    progressValue += 4;
                    progressFill.style.width = progressValue + '%';
                }
            }, 400);
            
            try {
                const response = await fetch('/products/{{ product.product_id }}/sync', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                });
                
                if (response.ok) {
                    const result = await response.json();
                    progressFill.style.width = '100%';
                    status.textContent = '✓ Synced! Videos: ' + result.videos_count + ', Comments: ' + result.comments_count;
                    setTimeout(() => location.reload(), 700);
                } else {
                    status.textContent = 'Error during sync';
                }
            } catch (error) {
                status.textContent = 'Error: ' + error;
            } finally {
                if (timer) {
                    clearInterval(timer);
                }
                if (!status.textContent.startsWith('✓')) {
                    progress.classList.remove('show');
                    progressFill.style.width = '0%';
                }
                btn.disabled = false;
            }
        }
    </script>
</body>
</html>
"""

TEMPLATE_VIDEO_DETAIL = """
<!DOCTYPE html>
<html>
<head>
    <title>{{ video.title }} - Video Analysis</title>
    <style>
        body { font-family: Arial, sans-serif; margin: 20px; }
        .container { max-width: 1000px; margin: 0 auto; }
        h1 { color: #333; }
        .video-info { background: #f5f5f5; padding: 15px; border-radius: 4px; margin-bottom: 20px; }
        .video-info p { margin: 8px 0; }
        .youtube-link { color: #ff0000; text-decoration: none; font-weight: bold; }
        .youtube-link:hover { text-decoration: underline; }
        .stats { display: grid; grid-template-columns: repeat(4, 1fr); gap: 15px; margin-bottom: 20px; }
        .stat-box { background: #007bff; color: white; padding: 15px; border-radius: 4px; text-align: center; }
        .stat-box .label { font-size: 0.9em; opacity: 0.9; }
        .stat-box .value { font-size: 1.8em; font-weight: bold; }
        .sentiment-section { margin-top: 30px; }
        .sentiment-summary { display: grid; grid-template-columns: repeat(3, 1fr); gap: 15px; margin-bottom: 20px; }
        .sentiment-box { padding: 15px; border-radius: 4px; text-align: center; }
        .sentiment-box.positive { background: #28a745; color: white; }
        .sentiment-box.neutral { background: #ffc107; color: black; }
        .sentiment-box.negative { background: #dc3545; color: white; }
        .sentiment-box .label { font-size: 0.9em; opacity: 0.9; }
        .sentiment-box .value { font-size: 1.5em; font-weight: bold; }
        .comments-section { margin-top: 30px; }
        .comment-item { background: #f9f9f9; padding: 12px; margin-bottom: 10px; border-radius: 4px; border-left: 4px solid #ddd; }
        .comment-item.positive { border-left-color: #28a745; }
        .comment-item.negative { border-left-color: #dc3545; }
        .comment-item.neutral { border-left-color: #ffc107; }
        .comment-text { margin-bottom: 5px; }
        .comment-meta { font-size: 0.85em; color: #666; }
        .back-link { margin-bottom: 20px; }
        .back-link a { color: #007bff; }
        .pagination { margin-top: 20px; display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
        .pagination a, .pagination span { padding: 6px 10px; border: 1px solid #ddd; border-radius: 4px; text-decoration: none; }
        .pagination a { color: #007bff; }
        .pagination a:hover { background: #f2f6ff; }
        .pagination .current { background: #007bff; color: #fff; border-color: #007bff; }
        .pagination .disabled { color: #999; }
        .transcript-section { margin-top: 36px; }
        .comment-sentiment-section { margin-top: 36px; }
        .transcript-meta { color: #555; font-size: 0.9em; margin-bottom: 10px; }
        .report-box {
            background: #f7fbff;
            border: 1px solid #d9e8f8;
            border-radius: 6px;
            padding: 14px;
            white-space: pre-wrap;
            line-height: 1.45;
            font-family: Consolas, "Courier New", monospace;
            font-size: 0.92em;
        }
        .pdf-download-btn {
            display: inline-block;
            margin-top: 12px;
            padding: 9px 14px;
            background: #0d6efd;
            color: white;
            text-decoration: none;
            border-radius: 4px;
        }
        .pdf-download-btn:hover { background: #0b5ed7; }
        .section-header { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
        .rewrite-btn {
            border: 1px solid #c8d6e5;
            background: #ffffff;
            color: #1f4e79;
            border-radius: 4px;
            padding: 6px 10px;
            cursor: pointer;
            font-size: 0.9em;
        }
        .rewrite-btn:hover { background: #f2f8ff; }
    </style>
</head>
<body>
    <div class="container">
        <div class="back-link">
            <a href="/products/{{ product_id }}">← Back to Product</a>
        </div>
        
        <h1>{{ video.title }}</h1>
        
        <div class="video-info">
            <p><strong>YouTube:</strong> <a href="https://www.youtube.com/watch?v={{ video.video_id }}" target="_blank" class="youtube-link">Watch Video</a></p>
            <p><strong>Published:</strong> {{ video.published_at }}</p>
        </div>
        
        <div class="stats">
            <div class="stat-box">
                <div class="label">Views</div>
                <div class="value">{{ video.view_count }}</div>
            </div>
            <div class="stat-box">
                <div class="label">Likes</div>
                <div class="value">{{ video.like_count }}</div>
            </div>
            <div class="stat-box">
                <div class="label">Comments</div>
                <div class="value">{{ video.comment_count }}</div>
            </div>
            <div class="stat-box">
                <div class="label">Product-Related</div>
                <div class="value">{{ product_related_count }}</div>
            </div>
        </div>
        
        <div class="sentiment-section">
            <h2>Sentiment Analysis</h2>
            <div class="sentiment-summary">
                <div class="sentiment-box positive">
                    <div class="label">Positive</div>
                    <div class="value">{{ sentiment_positive }}</div>
                </div>
                <div class="sentiment-box neutral">
                    <div class="label">Neutral</div>
                    <div class="value">{{ sentiment_neutral }}</div>
                </div>
                <div class="sentiment-box negative">
                    <div class="label">Negative</div>
                    <div class="value">{{ sentiment_negative }}</div>
                </div>
            </div>
        </div>
        
        <div class="comments-section">
            <h2>Product-Related Comments ({{ product_related_count }} total)</h2>
            {% if comments %}
                {% for comment in comments %}
                    <div class="comment-item {{ comment.sentiment_label }}">
                        <div class="comment-text">{{ comment.text_raw }}</div>
                        <div class="comment-meta">
                            Sentiment: <strong>{{ comment.sentiment_label|upper }}</strong> ({{ comment.sentiment_score }})
                        </div>
                    </div>
                {% endfor %}

                {% if total_pages > 1 %}
                    <div class="pagination">
                        {% if current_page > 1 %}
                            <a href="?page={{ current_page - 1 }}">Prev</a>
                        {% else %}
                            <span class="disabled">Prev</span>
                        {% endif %}

                        <span class="current">Page {{ current_page }} / {{ total_pages }}</span>

                        {% if current_page < total_pages %}
                            <a href="?page={{ current_page + 1 }}">Next</a>
                        {% else %}
                            <span class="disabled">Next</span>
                        {% endif %}
                    </div>
                {% endif %}
            {% else %}
                <p>No product-related comments found.</p>
            {% endif %}
        </div>

        <div class="transcript-section">
            <div class="section-header">
                <h2>Transcript Report</h2>
                <button class="rewrite-btn" onclick="rewriteTranscriptReport()">Rewrite</button>
            </div>
            {% if transcript_row %}
                <div class="transcript-meta">
                    Language: {{ transcript_row.language_code or 'unknown' }} |
                    Segments: {{ transcript_row.segment_count or 0 }} |
                    Updated: {{ transcript_row.updated_at }}
                </div>
                <div class="report-box">{{ transcript_report }}</div>
                <a class="pdf-download-btn" href="/products/{{ product_id }}/videos/{{ video.video_id }}/transcript-report.pdf">
                    Download PDF Report
                </a>
            {% else %}
                <p>Transcript report is unavailable for this video. This usually means the video has no accessible subtitles/captions, or subtitle access is restricted by YouTube.</p>
            {% endif %}
        </div>

        <div class="comment-sentiment-section">
            <div class="section-header">
                <h2>📊 Comment Reaction Analysis</h2>
                <button class="rewrite-btn" onclick="rewriteCommentReport()">Rewrite</button>
            </div>
            {% if comment_sentiment_report %}
                <div class="report-box">{{ comment_sentiment_report }}</div>
            {% else %}
                <p>Comment reaction analysis is unavailable. This may occur if there are insufficient product-related comments or if the analysis service is temporarily unavailable.</p>
            {% endif %}
        </div>
    </div>

    <script>
        async function rewriteTranscriptReport() {
            const response = await fetch('/products/{{ product_id }}/videos/{{ video.video_id }}/rewrite-transcript-report', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
            });
            if (!response.ok) {
                alert('Failed to rewrite transcript report');
                return;
            }
            location.reload();
        }

        async function rewriteCommentReport() {
            const response = await fetch('/products/{{ product_id }}/videos/{{ video.video_id }}/rewrite-comment-report', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
            });
            if (!response.ok) {
                alert('Failed to rewrite comment report');
                return;
            }
            location.reload();
        }
    </script>
</body>
</html>
"""

# Write templates to files on startup
def write_templates():
    """Write template strings to files."""
    templates = {
        "templates/products.html": TEMPLATE_PRODUCTS,
        "templates/product_detail.html": TEMPLATE_PRODUCT_DETAIL,
        "templates/video_detail.html": TEMPLATE_VIDEO_DETAIL,
    }
    
    for path, content in templates.items():
        Path(path).write_text(content, encoding="utf-8")
    
    print("✓ Templates written")


templates = Jinja2Templates(directory="templates")


@app.on_event("startup")
async def startup_event():
    """Initialize database and templates on startup."""
    init_db()
    write_templates()


@app.get("/", response_class=HTMLResponse)
async def root():
    """Redirect to products page."""
    return "<script>window.location.href='/products'</script>"


@app.get("/products", response_class=HTMLResponse)
async def list_products(request: Request):
    """List all products."""
    products = query_all("SELECT * FROM tech_products ORDER BY created_at DESC")
    return templates.TemplateResponse("products.html", {
        "request": request,
        "products": products,
    })


@app.post("/products")
async def create_product(data: dict):
    """Create a new product."""
    name = data.get("name", "").strip()
    brand = data.get("brand", "").strip() or None
    category = data.get("category", "").strip() or None
    
    if not name:
        raise HTTPException(status_code=400, detail="Product name is required")
    
    product_id = execute_insert(
        "INSERT INTO tech_products (name, brand, category) VALUES (%s, %s, %s) RETURNING product_id",
        (name, brand, category)
    )
    
    product = query_one("SELECT * FROM tech_products WHERE product_id = %s", (product_id,))
    return product


@app.get("/products/{product_id}", response_class=HTMLResponse)
async def product_detail(request: Request, product_id: int):
    """Show product detail page with videos."""
    product = query_one("SELECT * FROM tech_products WHERE product_id = %s", (product_id,))
    
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    
    videos = query_all(
        "SELECT * FROM videos WHERE product_id = %s ORDER BY view_count DESC",
        (product_id,)
    )
    
    return templates.TemplateResponse("product_detail.html", {
        "request": request,
        "product": product,
        "videos": videos,
    })


@app.post("/products/{product_id}/sync")
async def sync_product_videos(product_id: int, data: dict = None):
    """Sync videos and comments from YouTube for a product."""
    product = query_one("SELECT * FROM tech_products WHERE product_id = %s", (product_id,))
    
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    
    max_results = (data or {}).get("max_results", 5)
    
    # DELETE all existing data for this product (clean slate approach)
    # Order matters: delete dependent tables first
    execute_update(
        """DELETE FROM comment_sentiments
           WHERE comment_id IN (
             SELECT c.comment_id FROM comments c
             INNER JOIN videos v ON c.video_id = v.video_id
             WHERE v.product_id = %s
           )""",
        (product_id,)
    )
    execute_update(
        """DELETE FROM comments
           WHERE video_id IN (
             SELECT video_id FROM videos WHERE product_id = %s
           )""",
        (product_id,)
    )
    execute_update(
        """DELETE FROM video_transcripts
           WHERE video_id IN (
             SELECT video_id FROM videos WHERE product_id = %s
           )""",
        (product_id,)
    )
    execute_update(
        """DELETE FROM video_reports
           WHERE video_id IN (
             SELECT video_id FROM videos WHERE product_id = %s
           )""",
        (product_id,)
    )
    execute_update(
        "DELETE FROM videos WHERE product_id = %s",
        (product_id,)
    )
    
    # Fetch videos from YouTube
    videos = fetch_product_videos(product["name"], max_results=max_results)
    videos_count = 0
    comments_count = 0
    transcripts_count = 0
    
    for video in videos:
        # INSERT new video
        execute_update(
            """INSERT INTO videos (video_id, product_id, title, description, published_at,
               thumbnail_url, view_count, like_count, comment_count)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)""",
            (video["video_id"], product_id, video["title"], video["description"],
             video["published_at"], video["thumbnail_url"], video["view_count"],
             video["like_count"], video["comment_count"])
        )
        videos_count += 1
        
        # Fetch and process comments
        comments = fetch_video_comments(video["video_id"], max_pages=2)
        
        for comment in comments:
            # Determine if product-related
            is_related = is_product_related(comment["text_raw"], product["name"])
            
            # Insert comment
            execute_update(
                """INSERT INTO comments (comment_id, video_id, text_raw, is_product_related)
                   VALUES (%s, %s, %s, %s)""",
                (comment["comment_id"], video["video_id"], comment["text_raw"], is_related)
            )
            comments_count += 1
            
            # Analyze sentiment if product-related
            if is_related:
                sentiment_label, sentiment_score = analyze_sentiment(comment["text_raw"])
                
                execute_update(
                    """INSERT INTO comment_sentiments (comment_id, sentiment_label, sentiment_score)
                       VALUES (%s, %s, %s)""",
                    (comment["comment_id"], sentiment_label, sentiment_score)
                )

        # Fetch and store transcript
        transcript = fetch_video_transcript(video["video_id"])
        if transcript:
            execute_update(
                """INSERT INTO video_transcripts (video_id, transcript_text, language_code, segment_count, source)
                   VALUES (%s, %s, %s, %s, %s)""",
                (
                    video["video_id"],
                    transcript["transcript_text"],
                    transcript["language_code"],
                    transcript["segment_count"],
                    "youtube_transcript_api",
                ),
            )
            transcripts_count += 1
        
        # Reports will be generated on-demand when user views the video (video_detail page)
    
    return {
        "status": "success",
        "videos_count": videos_count,
        "comments_count": comments_count,
        "transcripts_count": transcripts_count,
    }


@app.get("/products/{product_id}/videos/{video_id}", response_class=HTMLResponse)
async def video_detail(request: Request, product_id: int, video_id: str, page: int = 1):
    """Show video detail page with sentiment analysis and pagination."""
    product = query_one("SELECT * FROM tech_products WHERE product_id = %s", (product_id,))
    
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    
    video = query_one(
        "SELECT * FROM videos WHERE video_id = %s AND product_id = %s",
        (video_id, product_id)
    )
    
    if not video:
        raise HTTPException(status_code=404, detail="Video not found")
    
    # Pagination params
    page = max(1, page)
    per_page = 10
    offset = (page - 1) * per_page
    
    # Get product-related comments with sentiment (paginated)
    comments = query_all(
        """SELECT c.comment_id, c.text_raw, cs.sentiment_label, cs.sentiment_score
           FROM comments c
           LEFT JOIN comment_sentiments cs ON c.comment_id = cs.comment_id
           WHERE c.video_id = %s AND c.is_product_related = true
           ORDER BY c.created_at DESC LIMIT %s OFFSET %s""",
        (video_id, per_page, offset)
    )
    
    # Count total product-related comments
    product_related_count = query_one(
        "SELECT COUNT(*) as count FROM comments WHERE video_id = %s AND is_product_related = true",
        (video_id,)
    )
    total_comments = product_related_count["count"] if product_related_count else 0
    total_pages = (total_comments + per_page - 1) // per_page
    
    # Count sentiment distribution
    sentiment_counts = query_all(
        """SELECT cs.sentiment_label, COUNT(*) as count
           FROM comments c
           LEFT JOIN comment_sentiments cs ON c.comment_id = cs.comment_id
           WHERE c.video_id = %s AND c.is_product_related = true
           GROUP BY cs.sentiment_label""",
        (video_id,)
    )
    
    sentiment_map = {row["sentiment_label"]: row["count"] for row in sentiment_counts}

    transcript_row = query_one(
        "SELECT transcript_text, language_code, segment_count, updated_at FROM video_transcripts WHERE video_id = %s",
        (video_id,),
    )

    # Auto-recover missing transcript once at page load so users can see report without re-sync.
    if not transcript_row:
        fetched_transcript = fetch_video_transcript(video_id)
        if fetched_transcript:
            execute_update(
                """INSERT INTO video_transcripts (video_id, transcript_text, language_code, segment_count, source)
                   VALUES (%s, %s, %s, %s, %s)
                   ON CONFLICT (video_id)
                   DO UPDATE SET
                     transcript_text = EXCLUDED.transcript_text,
                     language_code = EXCLUDED.language_code,
                     segment_count = EXCLUDED.segment_count,
                     source = EXCLUDED.source,
                     updated_at = NOW()""",
                (
                    video_id,
                    fetched_transcript["transcript_text"],
                    fetched_transcript["language_code"],
                    fetched_transcript["segment_count"],
                    "youtube_transcript_api",
                ),
            )
            transcript_row = query_one(
                "SELECT transcript_text, language_code, segment_count, updated_at FROM video_transcripts WHERE video_id = %s",
                (video_id,),
            )

    report_row = query_one(
        "SELECT transcript_report, comment_report, updated_at FROM video_reports WHERE video_id = %s",
        (video_id,),
    )
    transcript_report = report_row["transcript_report"] if report_row else None
    comment_sentiment_report = report_row["comment_report"] if report_row else None
    
    # Generate reports on-demand if not already generated
    if not transcript_report and transcript_row:
        transcript_report = build_transcript_report(transcript_row["transcript_text"])
        upsert_video_report(video_id, transcript_report=transcript_report)
    
    if not comment_sentiment_report:
        comment_sentiment_report = build_comment_sentiment_report(video_id, product["name"])
        upsert_video_report(video_id, comment_report=comment_sentiment_report)
    
    return templates.TemplateResponse("video_detail.html", {
        "request": request,
        "product_id": product_id,
        "product": product,
        "video": video,
        "comments": comments,
        "product_related_count": total_comments,
        "current_page": page,
        "total_pages": total_pages,
        "per_page": per_page,
        "sentiment_positive": sentiment_map.get("positive", 0),
        "sentiment_neutral": sentiment_map.get("neutral", 0),
        "sentiment_negative": sentiment_map.get("negative", 0),
        "transcript_row": transcript_row,
        "transcript_report": transcript_report,
        "comment_sentiment_report": comment_sentiment_report,
    })


@app.post("/products/{product_id}/videos/{video_id}/rewrite-transcript-report")
async def rewrite_transcript_report(product_id: int, video_id: str):
    """Regenerate and persist transcript report for a video."""
    video = query_one(
        "SELECT * FROM videos WHERE video_id = %s AND product_id = %s",
        (video_id, product_id),
    )
    if not video:
        raise HTTPException(status_code=404, detail="Video not found")

    transcript_row = query_one(
        "SELECT transcript_text FROM video_transcripts WHERE video_id = %s",
        (video_id,),
    )
    if not transcript_row:
        raise HTTPException(status_code=404, detail="Transcript not found")

    report_text = build_transcript_report(transcript_row["transcript_text"])
    upsert_video_report(video_id, transcript_report=report_text)
    return {"status": "success", "type": "transcript"}


@app.post("/products/{product_id}/videos/{video_id}/rewrite-comment-report")
async def rewrite_comment_report(product_id: int, video_id: str):
    """Regenerate and persist comment sentiment report for a video."""
    product = query_one("SELECT * FROM tech_products WHERE product_id = %s", (product_id,))
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    video = query_one(
        "SELECT * FROM videos WHERE video_id = %s AND product_id = %s",
        (video_id, product_id),
    )
    if not video:
        raise HTTPException(status_code=404, detail="Video not found")

    report_text = build_comment_sentiment_report(video_id, product["name"])
    if not report_text:
        raise HTTPException(status_code=404, detail="No product-related comments found")

    upsert_video_report(video_id, comment_report=report_text)
    return {"status": "success", "type": "comment"}


@app.get("/products/{product_id}/videos/{video_id}/transcript-report.pdf")
async def download_transcript_report(product_id: int, video_id: str):
    """Generate and download transcript report as PDF."""
    video = query_one(
        "SELECT * FROM videos WHERE video_id = %s AND product_id = %s",
        (video_id, product_id),
    )
    if not video:
        raise HTTPException(status_code=404, detail="Video not found")

    transcript_row = query_one(
        "SELECT transcript_text FROM video_transcripts WHERE video_id = %s",
        (video_id,),
    )
    if not transcript_row:
        raise HTTPException(status_code=404, detail="Transcript not found")

    report_text = build_transcript_report(transcript_row["transcript_text"])
    pdf_bytes = render_report_pdf(video.get("title", "Unknown Video"), report_text)

    filename = f"transcript_report_{video_id}.pdf"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ============================================================================
# APP ENTRY POINT
# ============================================================================

if __name__ == "__main__":
    import sys
    port = int(os.getenv("PORT", 8000))
    
    # Allow command line override: python main.py 8001
    if len(sys.argv) > 1:
        try:
            port = int(sys.argv[1])
        except ValueError:
            pass
    
    uvicorn.run(app, host="0.0.0.0", port=port)
