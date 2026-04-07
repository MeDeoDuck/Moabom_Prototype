"""
Centralized prompt definitions for LLM calls.

Edit this file to change prompts sent to Groq Llama.
"""

from __future__ import annotations


def build_transcript_report_prompt(transcript_text: str) -> str:
    """Build the prompt used for transcript-based product review reports using Llama."""
    return f"""
당신은 제품 리뷰 분석 전문가입니다. 다음 유튜브 영상 자막을 분석하여 전문적인 보고서를 작성해주세요.

📋 영상 자막
================
{transcript_text}

📊 분석 요청
================
위 자막을 기반으로 다음 항목을 포함한 상세 분석 보고서를 작성해주세요:

1. **제품 설명 및 특징**
   - 자막에서 언급된 제품의 주요 특징과 사양
   - 기술적 사양이나 디자인 요소

2. **리뷰어의 긍정 평가**
   - 리뷰어가 칭찬하는 부분
   - 제품의 강점으로 평가되는 항목들

3. **리뷰어의 부정 평가 및 우려사항**
   - 지적된 문제점이나 단점
   - 개선이 필요한 영역

4. **시장 평가 및 추천도**
   - 전반적인 제품 평가
   - 구매/추천 여부

5. **핵심 키워드**
   - 자막에서 반복되는 주요 개념 3~5개

✅ 작성 가이드:
- 한국어로 전문적이고 객관적인 톤 유지
- 자막의 실제 내용을 근거로 작성
- 약 400~600자 분량의 상세 보고서
- 명확한 구조로 읽기 쉽게 작성

보고서를 작성해주세요.
"""


def build_comment_sentiment_report_prompt(
    positive_comments: str,
    neutral_comments: str,
    negative_comments: str,
    product_name: str = "제품",
) -> str:
    """Build the prompt for analyzing product reactions from video comments."""
    return (
        f"유튜브 영상의 댓글을 sentiment별로 분석해서 {product_name}에 대한 사람들의 반응 보고서를 만들어줘.\\n\\n"
        "출력 형식:\\n"
        "- 첫 줄: [댓글 반응 기반 제품 평가보고서]\\n"
        "- 한국어로 작성\\n"
        "- 약 300자 이내로 간결하게 (중복 제거, 핵심만)\\n"
        "- 각 sentiment별로 사람들이 어떤 말을 하는지 간단히 정리\\n"
        "- 마지막에 장점 3가지, 단점 3가지 종합\\n\\n"
        "긍정적 댓글 (positive):\\n"
        f"{positive_comments}\\n\\n"
        "중립적 댓글 (neutral):\\n"
        f"{neutral_comments}\\n\\n"
        "부정적 댓글 (negative):\\n"
        f"{negative_comments}\\n\\n"
        "요구사항 (300자 이내):\\n"
        "1) 긍정 댓글의 주요 주제는?\\n"
        "2) 부정 댓글의 주요 이유는?\\n"
        "3) 이 제품의 핵심 장점 3가지\\n"
        "4) 이 제품의 핵심 단점 3가지\\n"
        "5) 한 줄 결론\\n"
        "\\n중요: 300자 이내로 작성하는 것이 핵심이야. 불필요한 설명은 제외하고 핵심만 담아줘."
    )
