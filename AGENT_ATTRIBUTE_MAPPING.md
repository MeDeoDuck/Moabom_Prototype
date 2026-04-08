# Agent 속성명 불일치 체크 리스트

## 🐛 발견된 속성명 불일치

### 1. ClassificationResult ❌
**Sync.py (잘못):**
- `classification.predicted_label` 
- `classification.confidence_score`
- `classification.reasoning`

**Agent 실제 (올바름):**
- `classification.label` ✅
- `classification.confidence` ✅
- `classification.rationale_short` ✅

---

### 2. SentimentAnalysisResult ❌
**Sync.py (잘못):**
- `sentiment_result.sentiment`
- `sentiment_result.sentiment_score`

**Agent 실제 (올바름):**
- `sentiment_result.overall_sentiment` ✅
- `sentiment_result.overall_score` ✅

---

### 3. AspectSentiment ❌  
**Sync.py (잘못):**
- `aspect.aspect_name`
- `aspect.sentiment_score`
- `aspect.confidence`

**Agent 실제 (올바름):**
- `aspect.aspect` ✅
- `aspect.score` ✅
- (confidence 속성 없음 - mention_text, reasoning만 있음)

---

## ✅ 수정 필요 위치

### 파일: `scripts/api/sync.py`

#### 1. Line 146-150 (LLM Classification 저장)
```python
# 잘못된 코드
classification.predicted_label.value,
classification.confidence_score,
classification.reasoning,

# 올바른 코드
classification.label.value,
classification.confidence,
classification.rationale_short,
```

#### 2. Line 194 (Sentiment 저장)
```python
# 잘못된 코드
sentiment_result.sentiment.value

# 올바른 코드
sentiment_result.overall_sentiment.value
```

#### 3. Line 206 (Sentiment Score 저장)
```python
# 잘못된 코드
sentiment_result.sentiment_score

# 올바른 코드
sentiment_result.overall_score
```

#### 4. Line 226-230 (Aspect 저장)
```python
# 잘못된 코드
aspect.aspect_name,
aspect.mention_text,
aspect.sentiment.value,
aspect.sentiment_score,
aspect.confidence,

# 올바른 코드
aspect.aspect,  # ⚠️ aspect_name이 아니라 aspect
aspect.mention_text,
aspect.sentiment.value,
aspect.score,  # ⚠️ sentiment_score가 아니라 score
None,  # ⚠️ confidence 속성 없음
```

---

## 📊 Agent 모델 구조 요약

### ClassificationResult
```python
@dataclass
class ClassificationResult:
    index: int
    original_comment: str
    label: CommentLabel              # ← predicted_label 아님!
    confidence: float                # ← confidence_score 아님!
    rationale_short: str             # ← reasoning 아님!
    needs_recheck: bool
    mentioned_product_features: List[str]
    is_product_related: bool
    model_name: str
    ...
```

### SentimentAnalysisResult
```python
@dataclass
class SentimentAnalysisResult:
    index: int
    original_comment: str
    overall_sentiment: SentimentType  # ← sentiment 아님!
    overall_score: float              # ← sentiment_score 아님!
    overall_intensity: IntensityType
    overall_reasoning: Optional[str]
    aspects: List[AspectSentiment]
    ...
```

### AspectSentiment
```python
@dataclass
class AspectSentiment:
    aspect: str                      # ← aspect_name 아님!
    aspect_category: str
    sentiment: SentimentType
    score: float                     # ← sentiment_score 아님!
    intensity: IntensityType
    mention_text: Optional[str]
    reasoning: Optional[str]
    # ⚠️ confidence 속성 없음!
```

---

## 🎯 체크리스트

- [ ] ClassificationResult.label (not predicted_label)
- [ ] ClassificationResult.confidence (not confidence_score)
- [ ] ClassificationResult.rationale_short (not reasoning)
- [ ] SentimentAnalysisResult.overall_sentiment (not sentiment)
- [ ] SentimentAnalysisResult.overall_score (not sentiment_score)
- [ ] AspectSentiment.aspect (not aspect_name)
- [ ] AspectSentiment.score (not sentiment_score)
- [ ] AspectSentiment - confidence 속성 없음!
