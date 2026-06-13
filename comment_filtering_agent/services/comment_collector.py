"""
YouTube 댓글 수집 서비스
"""
import os
import logging
from typing import List, Dict, Optional
from datetime import datetime
import uuid

from scripts.youtube.api_keys import current_key, is_google_quota_error, rotate

logger = logging.getLogger(__name__)


class Comment:
    """댓글 데이터 모델"""
    def __init__(
        self,
        comment_id: str,
        video_id: str,
        author_name: str,
        author_channel_id: str,
        text_original: str,
        text_display: str,
        like_count: int,
        reply_count: int,
        published_at: str,
        is_reply: bool = False,
        parent_comment_id: Optional[str] = None
    ):
        self.comment_id = comment_id
        self.video_id = video_id
        self.author_name = author_name
        self.author_channel_id = author_channel_id
        self.text_original = text_original
        self.text_display = text_display
        self.like_count = like_count
        self.reply_count = reply_count
        self.published_at = published_at
        self.collected_at = datetime.now()
        self.collection_batch_id = None
        self.is_reply = is_reply
        self.parent_comment_id = parent_comment_id
    
    def to_dict(self) -> dict:
        """딕셔너리로 변환"""
        return {
            "comment_id": self.comment_id,
            "video_id": self.video_id,
            "author_name": self.author_name,
            "author_channel_id": self.author_channel_id,
            "text_original": self.text_original,
            "text_display": self.text_display,
            "like_count": self.like_count,
            "reply_count": self.reply_count,
            "published_at": self.published_at,
            "collected_at": self.collected_at.isoformat(),
            "collection_batch_id": self.collection_batch_id,
            "is_reply": self.is_reply,
            "parent_comment_id": self.parent_comment_id
        }


class YouTubeCommentCollector:
    """YouTube Data API v3를 사용한 댓글 수집"""
    
    def __init__(self, api_key: Optional[str] = None):
        """
        초기화
        
        Args:
            api_key: YouTube Data API 키 (없으면 환경 변수 사용)
        """
        # 키 풀 커서에서 시작(이미 rotate 됐으면 그 키). quota 시 _list_comment_threads
        # 가 다음 키로 client 를 재생성한다 — .env 에 키만 채우면 자동 rotation.
        self.api_key = api_key or current_key()
        if not self.api_key:
            logger.warning("YOUTUBE_API_KEY not set, using mock mode")
            self.api_available = False
            self.youtube = None
            return
        
        # googleapiclient 임포트는 선택적
        try:
            from googleapiclient.discovery import build
            self.youtube = build('youtube', 'v3', developerKey=self.api_key)
            self.api_available = True
        except ImportError:
            logger.warning("google-api-python-client not installed. Using mock mode")
            self.youtube = None
            self.api_available = False
    
    def collect_comments(
        self,
        video_id: str,
        max_results: int = 100
    ) -> List[Comment]:
        """
        비디오의 댓글 수집
        
        Args:
            video_id: YouTube 비디오 ID
            max_results: 최대 수집 댓글 수
            
        Returns:
            Comment 리스트
        """
        if not self.api_available:
            logger.info("Using mock data (API not available)")
            return self._get_mock_comments(video_id, max_results)
        
        logger.info(f"Collecting comments for video: {video_id}")
        
        comments = []
        batch_id = str(uuid.uuid4())
        
        try:
            # 댓글 스레드 요청 (kwargs 로 보관 → quota rotation 시 새 client 로 재요청)
            kwargs = dict(
                part="snippet,replies",
                videoId=video_id,
                maxResults=min(max_results, 100),
                textFormat="plainText",
                order="relevance",
            )

            while kwargs and len(comments) < max_results:
                response = self._list_comment_threads(**kwargs)

                for item in response.get('items', []):
                    # 최상위 댓글
                    top_comment = self._parse_comment(
                        item['snippet']['topLevelComment'],
                        video_id,
                        batch_id
                    )
                    comments.append(top_comment)

                    if len(comments) >= max_results:
                        break

                # 다음 페이지
                if 'nextPageToken' in response and len(comments) < max_results:
                    kwargs = dict(
                        part="snippet,replies",
                        videoId=video_id,
                        maxResults=min(max_results - len(comments), 100),
                        pageToken=response['nextPageToken'],
                        textFormat="plainText",
                        order="relevance",
                    )
                else:
                    kwargs = None

            logger.info(f"Collected {len(comments)} comments")
            return comments

        except Exception as e:
            logger.error(f"Failed to collect comments: {e}")
            raise

    def _list_comment_threads(self, **kwargs) -> dict:
        """commentThreads().list(**kwargs).execute() + quota(403) failover.

        quotaExceeded 면 다음 키로 youtube client 를 재생성해 재시도한다(키 풀 공유
        커서). quota 가 아니거나 키가 소진되면 원래 예외를 그대로 올린다.
        """
        while True:
            try:
                return self.youtube.commentThreads().list(**kwargs).execute()
            except Exception as e:
                if not is_google_quota_error(e):
                    raise
                nxt = rotate(self.api_key)
                if not nxt or nxt == self.api_key:
                    raise                       # 더 쓸 키 없음 → 기존 동작대로 전파
                self.api_key = nxt
                from googleapiclient.discovery import build
                self.youtube = build('youtube', 'v3', developerKey=self.api_key)

    def _parse_comment(self, comment_data: dict, video_id: str, batch_id: str) -> Comment:
        """API 응답을 Comment 객체로 변환"""
        snippet = comment_data['snippet']
        
        comment = Comment(
            comment_id=comment_data['id'],
            video_id=video_id,
            author_name=snippet.get('authorDisplayName', 'Unknown'),
            author_channel_id=snippet.get('authorChannelId', {}).get('value', ''),
            text_original=snippet.get('textOriginal', ''),
            text_display=snippet.get('textDisplay', ''),
            like_count=snippet.get('likeCount', 0),
            reply_count=0,
            published_at=snippet.get('publishedAt', ''),
            is_reply=False,
            parent_comment_id=None
        )
        comment.collection_batch_id = batch_id
        
        return comment
    
    def _get_mock_comments(self, video_id: str, count: int) -> List[Comment]:
        """테스트용 mock 댓글 생성"""
        batch_id = str(uuid.uuid4())
        comments = []
        
        mock_texts = [
            "이거 게임 돌아가나요?",
            "발열은 심한데 성능은 좋네요",
            "배터리가 빨리 닳아요",
            "가격 대비 만족스럽습니다",
            "디자인도 예쁘고 성능도 좋아요",
            "잘 보고 갑니다",
            "ㅋㅋㅋㅋㅋ",
            "배경음악 제목 뭔가요?",
            "1등!",
            "오늘 영상 재밌네요"
        ]
        
        for i in range(min(count, len(mock_texts))):
            comment = Comment(
                comment_id=f"mock_{video_id}_{i}",
                video_id=video_id,
                author_name=f"User{i}",
                author_channel_id=f"channel_{i}",
                text_original=mock_texts[i],
                text_display=mock_texts[i],
                like_count=i,
                reply_count=0,
                published_at=datetime.now().isoformat(),
                is_reply=False,
                parent_comment_id=None
            )
            comment.collection_batch_id = batch_id
            comments.append(comment)
        
        logger.info(f"Generated {len(comments)} mock comments")
        return comments
