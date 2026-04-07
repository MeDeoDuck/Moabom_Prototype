"""
Sentiment analysis service
"""


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
