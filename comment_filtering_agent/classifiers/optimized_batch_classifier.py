"""
최적화된 배치 댓글 분류기

기존 파이프라인 인터페이스 유지하면서 내부 구현만 최적화:
- Batch processing (10개씩)
- 압축된 프롬프트 (few-shot 8개)
- 캐싱 시스템
- 비동기 병렬 처리
- 재판단 로직
"""
import asyncio
import hashlib
import json
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass
from datetime import datetime
import os

# RunYourAI 설정 (.env 에서 로드, scripts.config 와 동일한 환경변수)
_RUNYOURAI_API_KEY = os.getenv("RUNYOURAI_API_KEY", "")
_RUNYOURAI_BASE_URL = os.getenv("RUNYOURAI_BASE_URL", "https://api.runyour.ai/v1")
_RUNYOURAI_MODEL = os.getenv("RUNYOURAI_MODEL", "openai/gpt-4.1")

try:
    from langchain_openai import ChatOpenAI
    from langchain_core.prompts import ChatPromptTemplate
    from langchain_core.messages import SystemMessage
    from langchain_core.output_parsers import JsonOutputParser
    LANGCHAIN_AZURE_AVAILABLE = True
except ImportError:
    LANGCHAIN_AZURE_AVAILABLE = False
    print("Warning: Install langchain-openai: pip install langchain-openai")

from comment_filtering_agent.classifiers.models import (
    ClassificationResult,
    CommentLabel,
    ClassificationConfig
)


# ============================================================================
# 캐시 레이어
# ============================================================================

class ClassificationCache:
    """댓글 분류 결과 캐시"""
    
    def __init__(self, max_size: int = 10000):
        self.cache: Dict[str, Dict] = {}
        self.max_size = max_size
        self.hits = 0
        self.misses = 0
    
    def _normalize_text(self, text: str) -> str:
        """텍스트 정규화 (공백, 대소문자 무시)"""
        return text.lower().strip().replace(" ", "").replace("\n", "")
    
    def _generate_key(self, text: str, prompt_version: str = "v1") -> str:
        """캐시 키 생성"""
        normalized = self._normalize_text(text)
        key_str = f"{prompt_version}:{normalized}"
        return hashlib.md5(key_str.encode()).hexdigest()
    
    def get(self, text: str, prompt_version: str = "v1") -> Optional[Dict]:
        """캐시에서 결과 조회"""
        key = self._generate_key(text, prompt_version)
        result = self.cache.get(key)
        
        if result:
            self.hits += 1
        else:
            self.misses += 1
        
        return result
    
    def set(self, text: str, result: Dict, prompt_version: str = "v1"):
        """캐시에 결과 저장"""
        if len(self.cache) >= self.max_size:
            # FIFO 방식으로 가장 오래된 항목 제거
            oldest_key = next(iter(self.cache))
            del self.cache[oldest_key]
        
        key = self._generate_key(text, prompt_version)
        self.cache[key] = result
    
    def get_stats(self) -> Dict:
        """캐시 통계"""
        total = self.hits + self.misses
        hit_rate = (self.hits / total * 100) if total > 0 else 0
        
        return {
            "size": len(self.cache),
            "hits": self.hits,
            "misses": self.misses,
            "hit_rate": f"{hit_rate:.1f}%"
        }


# ============================================================================
# 압축된 프롬프트 템플릿
# ============================================================================

COMPACT_SYSTEM_PROMPT = """YouTube 제품 리뷰 댓글 분류기.

라벨:
- PRODUCT_OPINION: 제품 성능/품질 평가 (발열, 배터리, 성능, 디자인 등)
- VIDEO_REACTION: 영상/리뷰어 칭찬
- QUESTION: 제품 관련 질문
- CHATTER: 의미없는 반응 (ㅋㅋ, 와, 오)
- OFF_TOPIC: 완전히 무관

규칙:
1. 제품 특성 언급 → PRODUCT_OPINION
2. 영상/리뷰어 언급 → VIDEO_REACTION
3. 질문형 → QUESTION
4. 짧고 의미없음 → CHATTER
5. 무관 → OFF_TOPIC

JSON 배열로 응답: [{"id": "c1", "label": "PRODUCT_OPINION", "confidence": 0.95, "needs_recheck": false}, ...]"""


COMPACT_FEW_SHOT = [
    {"text": "발열은 심한데 성능은 좋네요", "label": "PRODUCT_OPINION", "conf": 0.95},
    {"text": "배터리 빨리 닳아요", "label": "PRODUCT_OPINION", "conf": 0.98},
    {"text": "오늘 영상 재밌네요", "label": "VIDEO_REACTION", "conf": 0.97},
    {"text": "이거 게임 잘 돌아가나요?", "label": "QUESTION", "conf": 0.99},
    {"text": "ㅋㅋㅋㅋ", "label": "CHATTER", "conf": 0.95},
    {"text": "배경음악 제목 뭔가요?", "label": "OFF_TOPIC", "conf": 0.99},
    {"text": "가격 대비 괜찮아요", "label": "PRODUCT_OPINION", "conf": 0.94},
    {"text": "리뷰 설명 상세해요", "label": "VIDEO_REACTION", "conf": 0.96},
]


def generate_batch_prompt(comments: List[Tuple[str, str]], include_examples: bool = True) -> str:
    """
    배치 분류용 프롬프트 생성
    
    Args:
        comments: [(comment_id, text), ...] 리스트
        include_examples: few-shot 예시 포함 여부
    
    Returns:
        프롬프트 문자열
    """
    # 댓글 리스트를 JSON 형태로
    comment_list = [{"id": cid, "text": text} for cid, text in comments]
    comments_json = json.dumps(comment_list, ensure_ascii=False, indent=2)
    
    prompt_parts = []
    
    # Few-shot 예시 (선택적)
    if include_examples:
        examples_str = "\n".join([
            f'- "{ex["text"]}" → {ex["label"]} (conf={ex["conf"]})'
            for ex in COMPACT_FEW_SHOT
        ])
        prompt_parts.append(f"예시:\n{examples_str}\n")
    
    # 분류할 댓글
    prompt_parts.append(f"분류할 댓글 ({len(comments)}개):\n{comments_json}")
    
    # 출력 형식
    prompt_parts.append("\nJSON 배열만 출력 (다른 텍스트 금지):")
    
    return "\n\n".join(prompt_parts)


# ============================================================================
# 배치 분류기 (동기 버전)
# ============================================================================

class OptimizedBatchClassifier:
    """
    최적화된 배치 댓글 분류기 (동기 버전)
    
    특징:
    - 배치 처리 (10개씩)
    - 압축된 프롬프트
    - 캐싱
    - 재판단 로직
    """
    
    def __init__(
        self,
        api_key: Optional[str] = None,
        batch_size: int = 10,
        confidence_threshold: float = 0.75,
        prompt_version: str = "compact_v1",
        max_concurrent: int = 3
    ):
        """
        Args:
            api_key: 호환을 위해 받아두지만 사용하지 않음 (Azure는 환경변수로 인증)
            batch_size: 배치 크기
            confidence_threshold: 재판단 임계값
            prompt_version: 프롬프트 버전
            max_concurrent: 최대 동시 배치 요청 수
        """
        if not LANGCHAIN_AZURE_AVAILABLE:
            raise ImportError("Install langchain-openai: pip install langchain-openai")
        if not _RUNYOURAI_API_KEY:
            raise ValueError(
                "RUNYOURAI_API_KEY 환경변수가 설정되지 않았습니다. "
                ".env 또는 Container App secret(runyourai-key)을 확인하세요."
            )

        self.api_key = _RUNYOURAI_API_KEY
        self.batch_size = batch_size
        self.confidence_threshold = confidence_threshold
        self.prompt_version = prompt_version
        self.max_concurrent = max_concurrent
        self.cache = ClassificationCache()

        self.model = _RUNYOURAI_MODEL
        self.max_retries = 3
        self.timeout = 30

        # LangChain chain: SystemMessage로 직접 삽입해 COMPACT_SYSTEM_PROMPT 내 {} 이스케이프 불필요
        llm = ChatOpenAI(
            api_key=_RUNYOURAI_API_KEY,
            base_url=_RUNYOURAI_BASE_URL,
            model=_RUNYOURAI_MODEL,
            temperature=0.1,
            max_tokens=5000,
            timeout=self.timeout,
        )
        self.chain = (
            ChatPromptTemplate.from_messages([
                SystemMessage(content=COMPACT_SYSTEM_PROMPT),
                ("human", "{user_prompt}"),
            ])
            | llm
            | JsonOutputParser()
        ).with_retry(stop_after_attempt=self.max_retries, wait_exponential_jitter=True)
    
    def classify_batch(
        self,
        comments: List[str],
        start_index: int = 0
    ) -> List[ClassificationResult]:
        """
        배치 댓글 분류 (캐시 활용)
        
        Args:
            comments: 댓글 텍스트 리스트
            start_index: 시작 인덱스
        
        Returns:
            ClassificationResult 리스트
        """
        # 1. 캐시 체크
        uncached_comments = []
        cached_results = {}
        
        for i, text in enumerate(comments):
            comment_id = f"c{start_index + i}"
            cached = self.cache.get(text, self.prompt_version)
            
            if cached:
                cached_results[comment_id] = cached
            else:
                uncached_comments.append((comment_id, text))
        
        # 2. 캐시되지 않은 댓글만 LLM 호출 (배치 분할 + 병렬)
        llm_results = {}
        if uncached_comments:
            batches: List[List[Tuple[str, str]]] = [
                uncached_comments[i:i + self.batch_size]
                for i in range(0, len(uncached_comments), self.batch_size)
            ]

            batch_inputs = [
                {"user_prompt": generate_batch_prompt(batch, include_examples=False)}
                for batch in batches
            ]
            batch_outputs = self.chain.batch(
                batch_inputs,
                config={"max_concurrency": self.max_concurrent},
                return_exceptions=True,
            )
            for batch, result_or_error in zip(batches, batch_outputs):
                if isinstance(result_or_error, Exception):
                    print(f"Warning: Batch classification failed: {result_or_error}")
                    for cid, _ in batch:
                        llm_results[cid] = {"label": "CHATTER", "confidence": 0.0, "needs_recheck": True}
                else:
                    for item in (result_or_error if isinstance(result_or_error, list) else []):
                        cid = item.get("id")
                        if cid:
                            llm_results[cid] = {
                                "label": item.get("label", "CHATTER"),
                                "confidence": float(item.get("confidence", 0.5)),
                                "needs_recheck": item.get("needs_recheck", False)
                            }

            # 3. 결과를 캐시에 저장
            for cid, text in uncached_comments:
                if cid in llm_results:
                    self.cache.set(text, llm_results[cid], self.prompt_version)
        
        # 4. 결과 병합 및 재판단
        all_results = {**cached_results, **llm_results}
        
        # 5. 재판단 필요한 댓글 처리
        recheck_comments = []
        for cid, result in all_results.items():
            if result.get("needs_recheck") or result.get("confidence", 1.0) < self.confidence_threshold:
                # 재판단 대상
                text = next(text for id, text in [(f"c{start_index + i}", comments[i]) for i in range(len(comments))] if id == cid)
                recheck_comments.append((cid, text))
        print(
            "[AGENT][CLASSIFIER] Recheck candidates: "
            f"{len(recheck_comments)}/{len(comments)} "
            f"(threshold={self.confidence_threshold})"
        )
        
        # 재판단 수행 (개별 호출, few-shot 포함)
        if recheck_comments:
            recheck_results = self._recheck_comments(recheck_comments)
            all_results.update(recheck_results)
            print(f"[AGENT][CLASSIFIER] Recheck applied: {len(recheck_results)} comments")
        else:
            print("[AGENT][CLASSIFIER] Recheck applied: 0 comments")
        
        # 6. ClassificationResult 객체로 변환
        results = []
        for i, text in enumerate(comments):
            comment_id = f"c{start_index + i}"
            result_dict = all_results.get(comment_id, {
                "label": "CHATTER",
                "confidence": 0.0,
                "needs_recheck": True
            })
            
            result = ClassificationResult(
                index=start_index + i,
                original_comment=text,
                label=CommentLabel(result_dict.get("label", "CHATTER")),
                confidence=float(result_dict.get("confidence", 0.5)),
                rationale_short=result_dict.get("rationale", ""),
                needs_recheck=result_dict.get("needs_recheck", False),
                mentioned_product_features=[],
                is_product_related=result_dict.get("label") in ["PRODUCT_OPINION", "QUESTION"],
                classifier_type="optimized_batch",
                model_name=self.model,
                prompt_version=self.prompt_version,
                llm_provider="azure_openai",
                latency_ms=0,
                raw_response=result_dict,
                classified_at=datetime.now()
            )
            results.append(result)
        
        return results
    
    def _classify_batch_llm(
        self,
        comments: List[Tuple[str, str]],
        include_examples: bool = False
    ) -> Dict[str, Dict]:
        """
        LLM으로 배치 분류 (압축 프롬프트)
        
        Args:
            comments: [(comment_id, text), ...]
            include_examples: few-shot 포함 여부
        
        Returns:
            {comment_id: {label, confidence, needs_recheck}, ...}
        """
        if not comments:
            return {}

        user_prompt = generate_batch_prompt(comments, include_examples=include_examples)

        try:
            result_array = self.chain.invoke({"user_prompt": user_prompt})

            results = {}
            for item in (result_array if isinstance(result_array, list) else []):
                cid = item.get("id")
                if cid:
                    results[cid] = {
                        "label": item.get("label", "CHATTER"),
                        "confidence": float(item.get("confidence", 0.5)),
                        "needs_recheck": item.get("needs_recheck", False)
                    }
            return results

        except Exception as e:
            print(f"Warning: Batch classification failed: {e}")
            return {
                cid: {"label": "CHATTER", "confidence": 0.0, "needs_recheck": True}
                for cid, _ in comments
            }
    
    def _recheck_comments(
        self,
        comments: List[Tuple[str, str]]
    ) -> Dict[str, Dict]:
        """
        애매한 댓글 재판단 (few-shot 포함)
        
        Args:
            comments: [(comment_id, text), ...]
        
        Returns:
            {comment_id: {label, confidence, needs_recheck}, ...}
        """
        return self._classify_batch_llm(comments, include_examples=True)
    
    def get_stats(self) -> Dict:
        """통계 정보"""
        return {
            "cache": self.cache.get_stats(),
            "batch_size": self.batch_size,
            "confidence_threshold": self.confidence_threshold,
            "prompt_version": self.prompt_version
        }


# ============================================================================
# 비동기 배치 분류기
# ============================================================================

class AsyncOptimizedBatchClassifier:
    """
    비동기 배치 댓글 분류기
    
    특징:
    - asyncio 기반 병렬 처리
    - Semaphore로 동시 요청 제한
    """
    
    def __init__(
        self,
        api_key: Optional[str] = None,
        batch_size: int = 10,
        max_concurrent: int = 5,
        confidence_threshold: float = 0.75,
        prompt_version: str = "compact_v1"
    ):
        """
        Args:
            api_key: 호환용 (Azure는 환경변수 사용)
            batch_size: 배치 크기
            max_concurrent: 최대 동시 요청 수
            confidence_threshold: 재판단 임계값
            prompt_version: 프롬프트 버전
        """
        if not LANGCHAIN_AZURE_AVAILABLE:
            raise ImportError("Install langchain-openai: pip install langchain-openai")
        if not _AZURE_ENDPOINT or not _AZURE_API_KEY:
            raise ValueError("Azure OpenAI not configured")

        self.api_key = _AZURE_API_KEY
        self.batch_size = batch_size
        self.max_concurrent = max_concurrent
        self.confidence_threshold = confidence_threshold
        self.prompt_version = prompt_version
        self.cache = ClassificationCache()

        self.model = _AZURE_DEPLOYMENT
        self.max_retries = 3
        self.timeout = 30
    
    async def classify_many(
        self,
        comments: List[str],
        start_index: int = 0
    ) -> List[ClassificationResult]:
        """
        전체 댓글 비동기 병렬 분류
        
        Args:
            comments: 댓글 텍스트 리스트
            start_index: 시작 인덱스
        
        Returns:
            ClassificationResult 리스트
        """
        # 배치로 나누기
        batches = []
        for i in range(0, len(comments), self.batch_size):
            batch = comments[i:i + self.batch_size]
            batch_start_idx = start_index + i
            batches.append((batch, batch_start_idx))
        
        # Semaphore로 동시 요청 제한
        semaphore = asyncio.Semaphore(self.max_concurrent)
        
        async def classify_batch_with_semaphore(batch, batch_start):
            async with semaphore:
                return await self._classify_batch_async(batch, batch_start)
        
        # 병렬 실행
        batch_results = await asyncio.gather(*[
            classify_batch_with_semaphore(batch, batch_start)
            for batch, batch_start in batches
        ])
        
        # 결과 병합
        all_results = []
        for results in batch_results:
            all_results.extend(results)
        
        return all_results
    
    async def _classify_batch_async(
        self,
        comments: List[str],
        start_index: int
    ) -> List[ClassificationResult]:
        """비동기 배치 분류 (내부 구현)"""
        # 동기 버전과 동일한 로직, async/await 사용
        # 구현 생략 (동기 버전 참고)
        pass
    
    def classify_batch_sync(
        self,
        comments: List[str],
        start_index: int = 0
    ) -> List[ClassificationResult]:
        """동기 래퍼 (기존 인터페이스 호환)"""
        return asyncio.run(self.classify_many(comments, start_index))


# ============================================================================
# 기존 인터페이스 호환 래퍼
# ============================================================================

def create_optimized_classifier(
    api_key: Optional[str] = None,
    use_async: bool = False
):
    """
    최적화된 분류기 생성
    
    Args:
        api_key: Groq API 키
        use_async: 비동기 버전 사용 여부
    
    Returns:
        OptimizedBatchClassifier 또는 AsyncOptimizedBatchClassifier
    """
    if use_async:
        return AsyncOptimizedBatchClassifier(api_key=api_key)
    else:
        return OptimizedBatchClassifier(api_key=api_key)
