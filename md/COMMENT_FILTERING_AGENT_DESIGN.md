# YouTube 댓글 필터링 Agent 설계 문서

## 1. 시스템 개요

### 1.1 목적
YouTube 테크 제품 리뷰 댓글을 자동으로 분류하고 필터링하여, 제품 평가에 유용한 댓글만을 추출하는 지능형 Agent 시스템을 구축한다.

### 1.2 핵심 원칙
- **고정 구조 유지**: 댓글 수집 → 1차 규칙 필터 → 댓글 필터링 Agent → DB 저장 → 보고서 작성
- **Agent는 조정자**: 단순 분류기가 아닌, 분류 결과를 보고 다음 단계로 보낼지 결정하는 의사결정자
- **비용 효율성**: few-shot 분류를 기본으로 하되, 향후 fine-tuning 전환 가능하도록 모듈화
- **확장성**: 규칙 추가, LLM 교체, 분류 모델 교체가 쉽도록 설계

### 1.3 처리 흐름

```
댓글 수집 (YouTube API)
    ↓
[1차 규칙 필터] ← 빠르고 가벼운 패턴 기반
    ↓
[댓글 필터링 Agent] ← LLM 기반 지능형 조정자
    ├─ 제품 평가 댓글 → 감정 분석 / 항목 분석
    ├─ 제품 질문 댓글 → 보조 정보 저장
    ├─ 영상 반응 댓글 → 제외
    ├─ 무관 댓글(스팸, 중복) → 제외
    ├─ 욕설 댓글 → 제외
    └─ 애매한 댓글 → LLM 재판단
    ↓
정제된 댓글 DB 저장
    ↓
댓글 분석 보고서 작성
```

---

## 2. 모듈별 책임

### 2.1 1차 규칙 필터 (Rule-Based Filter)
**파일**: `comment_filtering_agent/filters/rule_based_filter.py`

**책임**:
- 명확하게 걸러낼 수 있는 댓글을 빠르게 제거
- 정규식, stopword 사전, 패턴 매칭 기반
- LLM 호출 전 비용 절감

**제거 대상**:
- 글자 수 너무 짧음 (< 5자)
- 이모지만 있는 댓글 (📱🔥❤️)
- 단순 반응 패턴 ("1등", "ㅋㅋㅋ", "잘 보고 갑니다")
- URL 포함 댓글 (광고성)
- 유튜버 칭찬만 있는 댓글 ("채널 대박나세요")
- 반복 문자 (ㅋㅋㅋㅋㅋㅋㅋㅋ > 6개)
- 특수문자만 있는 댓글

**출력**: 통과 댓글 리스트 + 제거 사유

---

### 2.2 LLM 분류기 (LLM Classifier)
**파일**: `comment_filtering_agent/classifiers/base_classifier.py`

**책임**:
- 1차 필터 통과 댓글을 5개 라벨로 분류
- few-shot learning 기반 (현재)
- 향후 fine-tuned 모델로 교체 가능

**라벨 정의**:
| 라벨 | 설명 | 예시 |
|------|------|------|
| `PRODUCT_OPINION` | 제품 평가 댓글 | "발열은 심한데 성능은 좋네요" |
| `VIDEO_REACTION` | 영상/리뷰어 반응 | "오늘 영상 재밌네요" |
| `CHATTER` | 잡담/밈/의미 없음 | "ㅋㅋㅋㅋㅋ", "와" |
| `QUESTION` | 제품 관련 질문 | "이거 게임도 잘 돌아가나요?" |
| `OFF_TOPIC` | 제품과 무관한 댓글 | "배경음악 제목 뭔가요?" |

**출력**: (라벨, 신뢰도, 근거)

---

### 2.3 댓글 필터링 Agent (Comment Filtering Agent)
**파일**: `comment_filtering_agent/core/agent.py`

**책임**:
- 1차 필터 + LLM 분류 결과를 종합하여 **최종 결정**
- 단순 분류기가 아닌 **조정자 역할**
- 규칙에 따라 다음 단계 결정

**판단 로직**:

```python
if comment_class == "PRODUCT_OPINION":
    if confidence > 0.8:
        → 감정 분석 / 항목 분석으로 전달
    else:
        → LLM 재판단 요청

elif comment_class == "QUESTION":
    if is_product_related(text):
        → 보조 분석 데이터로 저장
    else:
        → 제외

elif comment_class == "VIDEO_REACTION":
    → 제외

elif comment_class in ["CHATTER", "OFF_TOPIC"]:
    → 제외

if has_profanity(text):
    → 제외

if is_duplicate(text):
    → 제외

if is_spam(text):
    → 제외

if confidence < 0.6:
    → LLM 재판단 또는 보류
```

**출력**: 필터링된 댓글 + 메타데이터 (라벨, 신뢰도, 사유, 다음 단계)

---

### 2.4 확장 모듈 (향후 대체 가능)

#### 2.4.1 분류 모델 학습 모듈
**파일**: `comment_filtering_agent/utils/classifier_trainer.py` (향후)

**책임**:
- 고성능 LLM으로 1차 라벨링
- 수기 라벨 정제
- 분류 모델 fine-tuning
- 모델 평가 및 배포

**데이터 파이프라인**:
```
수집된 댓글
    ↓
고성능 LLM (GPT-4o) 라벨링
    ↓
수기 검증 (Labelbox/Label Studio)
    ↓
Train/Valid/Test 분할
    ↓
DistilBERT/KoBERT fine-tuning
    ↓
성능 평가 (F1 > 0.85)
    ↓
배포 (HuggingFace / TorchServe)
```

#### 2.4.2 욕설 필터
**파일**: `comment_filtering_agent/filters/profanity_filter.py`

**책임**:
- 욕설/비속어 탐지
- 변형 욕설 탐지 (자음 분리, 특수문자 삽입)
- KoBERT 기반 문맥 욕설 탐지

#### 2.4.3 스팸 필터
**파일**: `comment_filtering_agent/utils/spam_detector.py`

**책임**:
- 중복 댓글 탐지 (Levenshtein 거리)
- 광고성 패턴 탐지
- 봇 댓글 탐지 (짧은 시간 내 유사 댓글)

---

## 3. 추천 폴더 구조

```
Moabom_Prototype/
├── app/
│   ├── models.py                     # Comment, CommentFilterResult 모델
│   ├── repositories.py               # CommentRepository
│   └── services.py                   # 기존 서비스
│
├── services/
│   └── analysis/
│       ├── comment_filter_service.py  # 기존 (deprecated 예정)
│       ├── analysis_pipeline_service.py
│       └── report_service.py
│
├── comment_filtering_agent/          # [NEW] 댓글 필터링 Agent 독립 모듈
│   ├── __init__.py
│   │
│   ├── core/                         # 핵심 Agent 로직
│   │   ├── __init__.py
│   │   ├── agent.py                  # CommentFilteringAgent 메인 클래스
│   │   ├── decision.py               # AgentDecision 데이터 클래스
│   │   └── pipeline.py               # 전체 파이프라인 오케스트레이터
│   │
│   ├── filters/                      # 1차 규칙 기반 필터
│   │   ├── __init__.py
│   │   ├── rule_based_filter.py     # RuleBasedFilter 메인 클래스
│   │   ├── length_filter.py         # 길이 체크 필터
│   │   ├── emoji_filter.py          # 이모지 전용 댓글 필터
│   │   ├── pattern_filter.py        # 반응 패턴 필터
│   │   ├── url_filter.py            # URL/광고 필터
│   │   └── profanity_filter.py      # 욕설 필터
│   │
│   ├── classifiers/                  # 2차 LLM 기반 분류기
│   │   ├── __init__.py
│   │   ├── base_classifier.py       # LLMClassifier 추상 인터페이스
│   │   ├── few_shot_classifier.py   # few-shot 구현체 (현재)
│   │   ├── finetuned_classifier.py  # fine-tuned 모델 구현체 (향후)
│   │   └── models.py                # CommentLabel, ClassificationResult
│   │
│   ├── utils/                        # 유틸리티
│   │   ├── __init__.py
│   │   ├── spam_detector.py         # 스팸/중복 탐지
│   │   ├── text_processor.py        # 텍스트 전처리
│   │   ├── cache_manager.py         # 분류 결과 캐싱
│   │   ├── logger.py                # 로깅 유틸
│   │   └── classifier_trainer.py    # 분류 모델 학습 (향후)
│   │
│   ├── prompts/                      # LLM 프롬프트 템플릿
│   │   ├── few_shot_base.txt        # 기본 few-shot 프롬프트
│   │   ├── few_shot_ko.txt          # 한국어 프롬프트
│   │   └── recheck_prompt.txt       # 재판단용 프롬프트
│   │
│   ├── data/                         # 데이터 파일
│   │   ├── stopwords_ko.txt         # 한국어 불용어 사전
│   │   ├── profanity_list.txt       # 욕설 사전
│   │   └── reaction_patterns.json   # 반응 패턴 정의
│   │
│   ├── tests/                        # 테스트
│   │   ├── __init__.py
│   │   ├── test_rule_filter.py      # 규칙 필터 테스트
│   │   ├── test_classifier.py       # 분류기 테스트
│   │   ├── test_agent.py            # Agent 통합 테스트
│   │   └── fixtures/                # 테스트 데이터
│   │       └── sample_comments.json
│   │
│   ├── config.py                     # Agent 설정
│   ├── README.md                     # Agent 사용 가이드
│   └── STRUCTURE.md                  # 구조 설명서
│
├── llm/                              # 기존 LLM 클라이언트
└── main.py
```

---

## 4. 주요 클래스 / 함수 설계

### 4.1 RuleBasedFilter

```python
# comment_filtering_agent/filters/rule_based_filter.py

from dataclasses import dataclass
from typing import List, Tuple

@dataclass
class FilterRule:
    name: str
    apply: callable
    reason: str

class RuleBasedFilter:
    def __init__(self):
        self.rules: List[FilterRule] = [
            FilterRule("length", self._check_length, "too_short"),
            FilterRule("emoji_only", self._check_emoji_only, "emoji_only"),
            FilterRule("reaction_pattern", self._check_reaction, "reaction_pattern"),
            FilterRule("url", self._check_url, "contains_url"),
            FilterRule("special_chars_only", self._check_special_chars, "special_chars_only"),
        ]
    
    def filter(self, comments: List[str]) -> Tuple[List[str], List[dict]]:
        """
        Returns:
            - passed_comments: 통과한 댓글 리스트
            - rejected: 제거된 댓글 + 사유
        """
        passed = []
        rejected = []
        
        for idx, text in enumerate(comments):
            for rule in self.rules:
                if rule.apply(text):
                    rejected.append({
                        "index": idx,
                        "text": text,
                        "rule": rule.name,
                        "reason": rule.reason
                    })
                    break
            else:
                passed.append(text)
        
        return passed, rejected
    
    def _check_length(self, text: str) -> bool:
        return len(text.strip()) < 5
    
    def _check_emoji_only(self, text: str) -> bool:
        import emoji
        text_no_emoji = emoji.replace_emoji(text, "")
        return len(text_no_emoji.strip()) == 0
    
    # ... 기타 규칙 메서드
```

---

### 4.2 LLMClassifier (추상 인터페이스)

```python
# comment_filtering_agent/classifiers/base_classifier.py

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum

class CommentLabel(str, Enum):
    PRODUCT_OPINION = "PRODUCT_OPINION"
    VIDEO_REACTION = "VIDEO_REACTION"
    CHATTER = "CHATTER"
    QUESTION = "QUESTION"
    OFF_TOPIC = "OFF_TOPIC"

@dataclass
class ClassificationResult:
    label: CommentLabel
    confidence: float
    reasoning: str

class LLMClassifier(ABC):
    @abstractmethod
    def classify(self, text: str) -> ClassificationResult:
        """댓글을 분류하고 신뢰도 반환"""
        pass
    
    @abstractmethod
    def classify_batch(self, texts: List[str]) -> List[ClassificationResult]:
        """배치 분류 (비용 효율화)"""
        pass
```

---

### 4.3 FewShotClassifier (구현체)

```python
# comment_filtering_agent/classifiers/few_shot_classifier.py

from comment_filtering_agent.classifiers.base_classifier import LLMClassifier, ClassificationResult, CommentLabel
from llm.groq_client import GroqClient  # 기존 LLM 클라이언트

class FewShotClassifier(LLMClassifier):
    def __init__(self, llm_client: GroqClient, prompt_template_path: str):
        self.llm_client = llm_client
        self.prompt_template = self._load_prompt(prompt_template_path)
    
    def classify(self, text: str) -> ClassificationResult:
        prompt = self.prompt_template.format(comment=text)
        response = self.llm_client.chat(prompt)
        
        # 응답 파싱 (JSON 형식 예상)
        label = CommentLabel(response["label"])
        confidence = response["confidence"]
        reasoning = response["reasoning"]
        
        return ClassificationResult(label, confidence, reasoning)
    
    def classify_batch(self, texts: List[str]) -> List[ClassificationResult]:
        # 배치 처리로 API 호출 최소화
        results = []
        for text in texts:
            results.append(self.classify(text))
        return results
    
    def _load_prompt(self, path: str) -> str:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
```

---

### 4.4 CommentFilteringAgent (핵심 조정자)

```python
# comment_filtering_agent/core/agent.py

from dataclasses import dataclass
from typing import List, Optional

@dataclass
class AgentDecision:
    index: int
    text: str
    label: CommentLabel
    confidence: float
    action: str  # "include", "exclude", "recheck", "hold"
    next_stage: Optional[str]  # "sentiment_analysis", "auxiliary", None
    reasoning: str

class CommentFilteringAgent:
    def __init__(
        self,
        rule_filter: RuleBasedFilter,
        classifier: LLMClassifier,
        profanity_filter: ProfanityFilter,
        spam_filter: SpamFilter,
        confidence_threshold: float = 0.6
    ):
        self.rule_filter = rule_filter
        self.classifier = classifier
        self.profanity_filter = profanity_filter
        self.spam_filter = spam_filter
        self.confidence_threshold = confidence_threshold
    
    def process(self, comments: List[str]) -> List[AgentDecision]:
        """
        댓글 필터링 파이프라인 실행
        """
        # 1단계: 규칙 기반 1차 필터
        passed_comments, rejected = self.rule_filter.filter(comments)
        
        # 2단계: LLM 분류
        classifications = self.classifier.classify_batch(passed_comments)
        
        # 3단계: Agent 판단
        decisions = []
        for idx, (text, classification) in enumerate(zip(passed_comments, classifications)):
            decision = self._make_decision(idx, text, classification)
            decisions.append(decision)
        
        return decisions
    
    def _make_decision(self, idx: int, text: str, classification: ClassificationResult) -> AgentDecision:
        """
        Agent의 최종 판단 로직
        """
        label = classification.label
        confidence = classification.confidence
        
        # 욕설 체크
        if self.profanity_filter.contains_profanity(text):
            return AgentDecision(
                index=idx,
                text=text,
                label=label,
                confidence=1.0,
                action="exclude",
                next_stage=None,
                reasoning="contains_profanity"
            )
        
        # 스팸/중복 체크
        if self.spam_filter.is_spam(text):
            return AgentDecision(
                index=idx,
                text=text,
                label=label,
                confidence=1.0,
                action="exclude",
                next_stage=None,
                reasoning="spam_or_duplicate"
            )
        
        # 신뢰도 낮은 경우
        if confidence < self.confidence_threshold:
            return AgentDecision(
                index=idx,
                text=text,
                label=label,
                confidence=confidence,
                action="recheck",
                next_stage=None,
                reasoning="low_confidence_needs_recheck"
            )
        
        # 라벨별 판단
        if label == CommentLabel.PRODUCT_OPINION:
            return AgentDecision(
                index=idx,
                text=text,
                label=label,
                confidence=confidence,
                action="include",
                next_stage="sentiment_analysis",
                reasoning="product_opinion_for_analysis"
            )
        
        elif label == CommentLabel.QUESTION:
            if self._is_product_related(text):
                return AgentDecision(
                    index=idx,
                    text=text,
                    label=label,
                    confidence=confidence,
                    action="include",
                    next_stage="auxiliary_data",
                    reasoning="product_question_for_auxiliary"
                )
            else:
                return AgentDecision(
                    index=idx,
                    text=text,
                    label=label,
                    confidence=confidence,
                    action="exclude",
                    next_stage=None,
                    reasoning="non_product_question"
                )
        
        elif label in [CommentLabel.VIDEO_REACTION, CommentLabel.CHATTER, CommentLabel.OFF_TOPIC]:
            return AgentDecision(
                index=idx,
                text=text,
                label=label,
                confidence=confidence,
                action="exclude",
                next_stage=None,
                reasoning=f"excluded_by_label_{label.value}"
            )
        
        # 기본: 보류
        return AgentDecision(
            index=idx,
            text=text,
            label=label,
            confidence=confidence,
            action="hold",
            next_stage=None,
            reasoning="default_hold"
        )
    
    def _is_product_related(self, text: str) -> bool:
        """제품 관련 질문인지 휴리스틱 판단"""
        product_question_keywords = ["성능", "가격", "배터리", "화질", "사용", "구매", "추천"]
        return any(kw in text for kw in product_question_keywords)
```

---

### 4.5 Few-Shot 프롬프트 템플릿

```
# comment_filtering_agent/prompts/few_shot_ko.txt

당신은 YouTube 제품 리뷰 댓글을 분류하는 전문가입니다.

아래 댓글을 다음 5개 카테고리 중 하나로 분류하세요:
1. PRODUCT_OPINION: 제품 평가 댓글
2. VIDEO_REACTION: 영상이나 리뷰어 반응 댓글
3. CHATTER: 잡담/밈/의미 없는 댓글
4. QUESTION: 제품 관련 질문
5. OFF_TOPIC: 제품과 무관한 댓글

[예시]
댓글: "발열은 심한데 성능은 좋네요"
라벨: PRODUCT_OPINION
신뢰도: 0.95
근거: 제품의 발열과 성능을 평가하는 의견 댓글

댓글: "오늘 영상 재밌네요"
라벨: VIDEO_REACTION
신뢰도: 0.92
근거: 영상 자체에 대한 반응

댓글: "ㅋㅋㅋㅋㅋ"
라벨: CHATTER
신뢰도: 0.98
근거: 의미 없는 웃음 표현

댓글: "이거 게임도 잘 돌아가나요?"
라벨: QUESTION
신뢰도: 0.93
근거: 제품 성능에 대한 질문

댓글: "배경음악 제목 뭔가요?"
라벨: OFF_TOPIC
신뢰도: 0.96
근거: 제품과 무관한 음악 질문

[분류 대상]
댓글: {comment}

JSON 형식으로 답변하세요:
{{
  "label": "PRODUCT_OPINION",
  "confidence": 0.95,
  "reasoning": "..."
}}
```

---

## 5. 데이터 흐름

### 5.1 전체 파이프라인

```
[YouTube API]
    ↓ 댓글 수집
[Raw Comments List]
    ↓
┌─────────────────────────────────┐
│ CommentFilteringAgent.process() │
└─────────────────────────────────┘
    ↓
┌──────────────────────┐
│ RuleBasedFilter      │ ← 1차 필터
│ - 길이 체크          │
│ - 이모지 체크        │
│ - 패턴 매칭          │
└──────────────────────┘
    ↓ passed_comments
┌──────────────────────┐
│ LLMClassifier        │ ← 2차 분류
│ (FewShotClassifier)  │
│ - LLM API 호출       │
│ - 배치 처리          │
└──────────────────────┘
    ↓ classifications
┌──────────────────────┐
│ Agent Decision Logic │ ← 3차 판단
│ - 욕설 필터          │
│ - 스팸 필터          │
│ - 신뢰도 체크        │
│ - 라벨별 라우팅      │
└──────────────────────┘
    ↓ decisions
┌──────────────────────┐
│ AgentDecision List   │
│ - action: include    │
│ - next_stage: ...    │
└──────────────────────┘
    ↓
[DB 저장]
    ├─ include → 분석 대상 댓글
    ├─ exclude → 제외된 댓글 (로그)
    └─ hold → 보류된 댓글 (재검토)
    ↓
[분석 파이프라인]
    ├─ sentiment_analysis → 감정 분석
    ├─ item_analysis → 항목별 분석
    └─ auxiliary_data → 보조 정보
```

### 5.2 데이터 구조

```python
# 입력 (YouTube API → DB)
raw_comment = {
    "comment_id": "abc123",
    "video_id": "xyz789",
    "text": "발열은 심한데 성능은 좋네요",
    "author": "user123",
    "published_at": "2026-04-01T10:00:00Z",
    "like_count": 15
}

# 1차 필터 통과 후
passed_comment = {
    "text": "발열은 심한데 성능은 좋네요"
}

# LLM 분류 후
classification = {
    "label": "PRODUCT_OPINION",
    "confidence": 0.92,
    "reasoning": "제품의 발열과 성능을 평가하는 의견"
}

# Agent 판단 후
decision = {
    "index": 0,
    "text": "발열은 심한데 성능은 좋네요",
    "label": "PRODUCT_OPINION",
    "confidence": 0.92,
    "action": "include",
    "next_stage": "sentiment_analysis",
    "reasoning": "product_opinion_for_analysis"
}

# DB 저장 (comment_filter_results 테이블)
filtered_comment = {
    "comment_id": "abc123",
    "video_id": "xyz789",
    "text": "발열은 심한데 성능은 좋네요",
    "label": "PRODUCT_OPINION",
    "confidence": 0.92,
    "action": "include",
    "next_stage": "sentiment_analysis",
    "reasoning": "product_opinion_for_analysis",
    "filtered_at": "2026-04-02T04:50:00Z"
}
```

---

## 6. 향후 few-shot → fine-tuning 전환 확장 포인트

### 6.1 설계 원칙
**의존성 역전 (Dependency Inversion)**
- `CommentFilteringAgent`는 추상 인터페이스 `LLMClassifier`에 의존
- 구현체 (`FewShotClassifier`, `FineTunedClassifier`)는 쉽게 교체 가능

```python
# 현재 구성
agent = CommentFilteringAgent(
    rule_filter=RuleBasedFilter(),
    classifier=FewShotClassifier(llm_client, prompt_path),  # few-shot
    profanity_filter=ProfanityFilter(),
    spam_filter=SpamFilter()
)

# 향후 구성 (fine-tuned 모델로 교체)
agent = CommentFilteringAgent(
    rule_filter=RuleBasedFilter(),
    classifier=FineTunedClassifier(model_path),  # fine-tuned
    profanity_filter=ProfanityFilter(),
    spam_filter=SpamFilter()
)
```

### 6.2 전환 로드맵

#### Phase 1: Few-Shot 운영 (현재)
- Groq API (Llama 3.1) 사용
- 프롬프트 엔지니어링 개선
- 분류 성능 측정 (정확도, F1)
- **데이터 수집**: 분류된 댓글 + 라벨 저장

#### Phase 2: 라벨 수집 및 정제
- 목표: 10,000개 라벨링 댓글 확보
- 방법:
  1. Few-shot 분류기로 자동 라벨링
  2. 신뢰도 높은 것 (> 0.9) 자동 승인
  3. 신뢰도 낮은 것 (< 0.7) 수기 검증
  4. Labelbox / Label Studio 사용

#### Phase 3: 모델 학습
- 베이스 모델: `klue/roberta-base`, `beomi/kcbert-base`, `monologg/koelectra-base-v3`
- 학습 방법: Fine-tuning (Classification Head)
- 평가 지표: Accuracy, F1-macro, Confusion Matrix
- 성능 목표: F1 > 0.85

#### Phase 4: 모델 배포 및 A/B 테스트
- 배포 방법: HuggingFace Inference API / TorchServe / FastAPI
- A/B 테스트: few-shot vs fine-tuned 성능/비용 비교
- 모니터링: Latency, Cost, Accuracy

#### Phase 5: 전환 완료
- Fine-tuned 모델로 완전 전환
- Few-shot은 fallback으로 유지
- 정기적인 재학습 (매 분기)

### 6.3 확장 포인트 코드 예시

```python
# comment_filtering_agent/classifiers/finetuned_classifier.py (향후 구현)

from transformers import AutoTokenizer, AutoModelForSequenceClassification
import torch

class FineTunedClassifier(LLMClassifier):
    def __init__(self, model_path: str, device: str = "cuda"):
        self.tokenizer = AutoTokenizer.from_pretrained(model_path)
        self.model = AutoModelForSequenceClassification.from_pretrained(model_path)
        self.model.to(device)
        self.device = device
        
        self.label_map = {
            0: CommentLabel.PRODUCT_OPINION,
            1: CommentLabel.VIDEO_REACTION,
            2: CommentLabel.CHATTER,
            3: CommentLabel.QUESTION,
            4: CommentLabel.OFF_TOPIC
        }
    
    def classify(self, text: str) -> ClassificationResult:
        inputs = self.tokenizer(text, return_tensors="pt", truncation=True, max_length=128)
        inputs = {k: v.to(self.device) for k, v in inputs.items()}
        
        with torch.no_grad():
            outputs = self.model(**inputs)
            logits = outputs.logits
            probs = torch.softmax(logits, dim=-1)[0]
            predicted_class = torch.argmax(probs).item()
            confidence = probs[predicted_class].item()
        
        label = self.label_map[predicted_class]
        
        return ClassificationResult(
            label=label,
            confidence=confidence,
            reasoning=f"finetuned_model_prediction"
        )
    
    def classify_batch(self, texts: List[str]) -> List[ClassificationResult]:
        # 배치 추론 (GPU 효율)
        results = []
        for text in texts:
            results.append(self.classify(text))
        return results
```

### 6.4 비용 비교

| 방식 | 초기 비용 | 운영 비용 (10k 댓글/일) | 지연시간 | 정확도 |
|------|----------|------------------------|---------|--------|
| Few-Shot (Groq) | $0 | ~$10/일 | 500ms | 0.80 |
| Fine-Tuned (로컬) | $200 (학습) | $0 (GPU 상각) | 50ms | 0.88 |
| Fine-Tuned (HF API) | $200 (학습) | $5/일 | 200ms | 0.88 |

→ **ROI 분석**: 월 300달러 절감 시, 1개월 내 투자 회수

---

## 7. 성능 최적화 고려사항

### 7.1 배치 처리
- LLM API 호출 시 배치 단위로 처리 (10~50개)
- 병렬 처리로 latency 감소

### 7.2 캐싱
- 동일 댓글 재분류 방지 (Redis 캐시)
- 캐시 키: `hash(text)` → `ClassificationResult`

### 7.3 비동기 처리
- Celery / FastAPI BackgroundTasks로 비동기 처리
- 실시간 분석 불필요 시 큐 방식 사용

### 7.4 모니터링
- 분류 신뢰도 분포 추적
- 재판단 요청 비율 모니터링
- 라벨별 분포 이상 탐지

---

## 8. 테스트 전략

### 8.1 단위 테스트
- `RuleBasedFilter`: 각 규칙별 테스트
- `FewShotClassifier`: 예시 댓글 분류 정확도
- `CommentFilteringAgent`: 판단 로직 테스트

### 8.2 통합 테스트
- 전체 파이프라인 end-to-end 테스트
- 실제 댓글 샘플 (100개) 정확도 측정

### 8.3 성능 테스트
- 1000개 댓글 처리 시간 측정
- API 호출 횟수 최적화 검증

### 8.4 A/B 테스트
- Few-shot vs Fine-tuned 정확도 비교
- 사용자 피드백 수집 (분류 오류 보고)

---

## 9. 구현 우선순위

### Sprint 1: 기본 인프라 (Week 1)
1. 폴더 구조 생성
2. `RuleBasedFilter` 구현
3. `LLMClassifier` 추상 인터페이스 정의
4. Few-shot 프롬프트 작성

### Sprint 2: Agent 핵심 로직 (Week 2)
5. `FewShotClassifier` 구현
6. `CommentFilteringAgent` 구현
7. 판단 로직 구현
8. 단위 테스트 작성

### Sprint 3: 보조 필터 (Week 3)
9. `ProfanityFilter` 구현
10. `SpamFilter` 구현
11. 통합 테스트 작성

### Sprint 4: 통합 및 최적화 (Week 4)
12. 기존 시스템 연동
13. 배치 처리 최적화
14. 성능 테스트 및 모니터링

### Sprint 5: 확장 준비 (Week 5~)
15. 라벨 수집 파이프라인 구축
16. `FineTunedClassifier` 인터페이스 설계
17. 모델 학습 실험

---

## 10. 사용 예시

### 10.1 기본 사용법

```python
# main.py 또는 FastAPI 엔드포인트에서

from comment_filtering_agent.core.pipeline import FilteringPipeline
from comment_filtering_agent.core.agent import CommentFilteringAgent
from comment_filtering_agent.filters.rule_based_filter import RuleBasedFilter
from comment_filtering_agent.classifiers.few_shot_classifier import FewShotClassifier
from comment_filtering_agent.utils.spam_detector import SpamDetector
from llm.groq_client import GroqClient

# 초기화
llm_client = GroqClient()
classifier = FewShotClassifier(
    llm_client=llm_client,
    prompt_path="comment_filtering_agent/prompts/few_shot_ko.txt"
)

agent = CommentFilteringAgent(
    rule_filter=RuleBasedFilter(),
    classifier=classifier,
    spam_detector=SpamDetector(),
    confidence_threshold=0.6
)

pipeline = FilteringPipeline(agent=agent)

# 댓글 필터링 실행
comments = [
    "발열은 심한데 성능은 좋네요",
    "ㅋㅋㅋㅋㅋ",
    "오늘 영상 재밌네요",
]

decisions = pipeline.process(comments)

# 결과 확인
for decision in decisions:
    print(f"댓글: {decision.text}")
    print(f"라벨: {decision.label}")
    print(f"액션: {decision.action}")
    print(f"다음 단계: {decision.next_stage}")
    print("---")
```

### 10.2 FastAPI 엔드포인트 통합

```python
# app/services.py

from comment_filtering_agent.core.pipeline import FilteringPipeline
from comment_filtering_agent.core.agent import CommentFilteringAgent
# ... imports

class CommentAnalysisService:
    def __init__(self, filtering_pipeline: FilteringPipeline):
        self.filtering_pipeline = filtering_pipeline
    
    def analyze_video_comments(self, video_id: str):
        # 1. 댓글 수집
        raw_comments = self.fetch_comments(video_id)
        
        # 2. Agent 필터링
        decisions = self.filtering_pipeline.process(raw_comments)
        
        # 3. include된 댓글만 분석
        filtered_comments = [
            d for d in decisions if d.action == "include"
        ]
        
        # 4. 감정 분석 / 항목 분석
        # ...
```

---

## 11. 마이그레이션 계획

### 11.1 기존 시스템과의 호환성
- 기존 `services/analysis/comment_filter_service.py` 유지 (deprecated)
- 새 Agent는 `comment_filtering_agent/` 독립 모듈로 제공
- 점진적 전환 (일부 비디오부터 적용)
- Feature flag로 Agent on/off 제어

### 11.2 통합 방법
```python
# app/app_factory.py 또는 dependency injection

from comment_filtering_agent.core.pipeline import FilteringPipeline
from comment_filtering_agent.core.agent import CommentFilteringAgent
# ... 

def create_filtering_pipeline() -> FilteringPipeline:
    """댓글 필터링 Agent 파이프라인 생성"""
    llm_client = GroqClient()
    classifier = FewShotClassifier(
        llm_client=llm_client,
        prompt_path="comment_filtering_agent/prompts/few_shot_ko.txt"
    )
    
    agent = CommentFilteringAgent(
        rule_filter=RuleBasedFilter(),
        classifier=classifier,
        spam_detector=SpamDetector(),
        confidence_threshold=0.6
    )
    
    return FilteringPipeline(agent=agent)
```

### 11.3 데이터 마이그레이션
- 새 테이블 `comment_filter_results` 생성
- 기존 댓글에 대해 재분류 실행 (배치)

### 11.4 롤백 계획
- 문제 발생 시 기존 `services/analysis/comment_filter_service.py`로 즉시 전환
- Feature flag로 Agent on/off 제어
- 독립 모듈이므로 제거/추가가 쉬움

---

## 12. 독립 모듈의 장점

1. **명확한 책임 분리**: Agent 관련 코드가 `comment_filtering_agent/` 한 곳에 모여있음
2. **재사용성**: 다른 프로젝트에서도 쉽게 가져다 쓸 수 있음
3. **테스트 용이**: 독립적인 테스트 실행 가능
4. **유지보수성**: 변경 사항이 다른 모듈(`app/`, `services/`)에 영향을 미치지 않음
5. **확장성**: 새로운 필터/분류기 추가가 쉬움
6. **버전 관리**: Agent 모듈 자체를 별도로 버전 관리 가능

---

## 참고 자료
- [Groq API 문서](https://console.groq.com/docs)
- [HuggingFace Transformers](https://huggingface.co/docs/transformers)
- [Few-Shot Learning 논문](https://arxiv.org/abs/2005.14165)
- [Text Classification 모범 사례](https://github.com/microsoft/nlp-recipes)
