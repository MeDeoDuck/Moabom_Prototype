"""
Sentiment analysis service - rule-based keyword scoring (Korean + English).
"""
from typing import Tuple

POSITIVE_KEYWORDS = frozenset({
    # English
    "good", "love", "great", "excellent", "amazing", "awesome", "best",
    "perfect", "fantastic", "wonderful", "brilliant", "recommend", "worth",
    "impressive", "impressed", "beautiful", "smooth", "fast", "powerful",
    # Korean
    "좋다", "좋은", "좋습니다", "훌륭", "훌륭한", "훌륭합니다", "추천",
    "완벽", "최고", "멋진", "빠르다", "빠른", "강력", "강력한",
})

NEGATIVE_KEYWORDS = frozenset({
    # English
    "bad", "hate", "poor", "terrible", "awful", "horrible", "worst",
    "useless", "broken", "issue", "problem", "bug", "disappointing",
    "waste", "regret", "return", "slow", "expensive", "fragile",
    # Korean
    "나쁘다", "문제", "느리다", "느린", "비싸다", "비싼", "약하다", "약한",
    "못쓸", "망했", "실망", "후회", "환불",
})


def analyze_sentiment(text: str) -> Tuple[str, float]:
    """
    Rule-based sentiment scoring.
    Returns (label, score) where label is one of "positive" / "negative" / "neutral".
    """
    text_lower = (text or "").lower()
    pos_count = sum(1 for kw in POSITIVE_KEYWORDS if kw in text_lower)
    neg_count = sum(1 for kw in NEGATIVE_KEYWORDS if kw in text_lower)

    if pos_count > neg_count:
        return ("positive", 0.7)
    if neg_count > pos_count:
        return ("negative", 0.3)
    return ("neutral", 0.5)
