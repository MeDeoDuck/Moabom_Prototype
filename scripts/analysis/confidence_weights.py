"""
Confidence-based analysis weighting constants.
"""

CONFIDENCE_WEIGHTS = {
    "high": 1.0,  # is_low_confidence=False
    "low": 0.5,   # is_low_confidence=True
}

LOW_CONFIDENCE_WARNING_THRESHOLD = 0.3


def get_analysis_weight(is_low_confidence: bool) -> float:
    return CONFIDENCE_WEIGHTS["low"] if is_low_confidence else CONFIDENCE_WEIGHTS["high"]
