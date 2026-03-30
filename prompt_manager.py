"""
Centralized prompt definitions for LLM calls.

Edit this file to change prompts sent to Gemini.
"""

from __future__ import annotations


def build_transcript_report_prompt(transcript_text: str) -> str:
    """Build the prompt used for transcript-based product review reports."""
    return (
        "영상의 자막을 보고 제품에 대한 리뷰어의 평가에 대한 보고서 만들어줘. "
        "아래의 내용은 영상의 자막이야.\n\n"
        "출력 형식 제약:\n"
        "- 첫 줄은 반드시 다음 문장 그대로 시작해: [선택한 영상 자막 기준 요약 보고서]\n"
        "- 한국어로 작성\n"
        "- 항목별로 읽기 쉽게 작성\n\n"
        "요구사항:\n"
        "1) 제품 설명/특징 요약\n"
        "2) 리뷰어의 긍정 평가\n"
        "3) 리뷰어의 부정 평가 및 우려사항\n"
        "4) 구매 추천 여부와 근거\n"
        "5) 핵심 키워드 5개\n"
        "6) 마지막에 한 줄 결론\n\n"
        "자막:\n"
        f"{transcript_text}\n\n"
        "중요: 이 보고서는 각 영상별로 생성되는 보고서이며, 지금 사용자가 선택해서 들어온 해당 영상의 자막만 기반으로 요약해줘."
    )


def build_comment_sentiment_report_prompt(
    positive_comments: str,
    neutral_comments: str,
    negative_comments: str,
    product_name: str = "제품",
) -> str:
    """Build the prompt for analyzing product reactions from video comments."""
    return (
        f"유튜브 영상의 댓글을 sentiment별로 분석해서 {product_name}에 대한 사람들의 반응 보고서를 만들어줘.\n\n"
        "출력 형식:\n"
        "- 첫 줄: [댓글 반응 기반 제품 평가보고서]\n"
        "- 한국어로 작성\n"
        "- 각 sentiment별로 사람들이 어떤 말을 하는지 요약\n"
        "- 마지막에 장점 3가지, 단점 3가지 종합\n\n"
        "긍정적 댓글 (positive):\n"
        f"{positive_comments}\n\n"
        "중립적 댓글 (neutral):\n"
        f"{neutral_comments}\n\n"
        "부정적 댓글 (negative):\n"
        f"{negative_comments}\n\n"
        "요구사항:\n"
        "1) 긍정 댓글을 보면 어떤 말을 주로 하는가?\n"
        "2) 중립 댓글을 보면 어떤 말을 주로 하는가?\n"
        "3) 부정 댓글을 보면 어떤 말을 주로 하는가?\n"
        "4) 이를 종합했을 때, 이 제품의 주요 장점 3가지는?\n"
        "5) 이를 종합했을 때, 이 제품의 주요 단점 3가지는?\n"
        "6) 마지막에 한 줄 결론\n"
    )
