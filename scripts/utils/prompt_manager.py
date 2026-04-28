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
- 본문은 1000자 이내로 작성 (공백 포함)
- 명확한 구조로 읽기 쉽게 작성
- 문장은 중간에 끊기지 않게 완결형으로 마무리
- 마지막 줄에 반드시 [END]만 단독으로 출력

보고서를 작성해주세요.
"""


def build_product_integrated_insight_prompt(
    product_name: str,
    per_video_reports: list,
    today_str: str = "",
) -> str:
    """
    제품 단위 통합 인사이트 보고서 프롬프트.

    per_video_reports: [{"video_id": str, "title": str, "transcript_report": str}, ...]

    환각 방지를 위해 절대 규칙을 강하게 명시한다 — 입력 보고서에 등장하지 않은
    사실/수치/사양/가격/비교 제품/출시일/리뷰어 이름을 만들어 내지 못하도록 한다.
    """
    joined_blocks = []
    for i, r in enumerate(per_video_reports):
        title = (r.get("title") or "").strip()
        body = (r.get("transcript_report") or "").strip()
        joined_blocks.append(
            f"[영상 {i+1} | video_id={r.get('video_id','')} | 제목: {title}]\n{body}"
        )
    joined = "\n\n".join(joined_blocks)
    n = len(per_video_reports)
    today_line = f"보고서 생성일: {today_str}" if today_str else "보고서 생성일: (오늘 날짜)"

    return f"""당신은 테크 제품 리뷰 메타분석 전문가입니다.

아래는 동일 제품 "{product_name}"에 대한 서로 다른 유튜브 리뷰 영상 {n}건의
"자막 기반 분석 보고서"입니다. 이 보고서들만을 유일한 근거로 사용하여,
제품 단위 통합 인사이트 보고서를 작성하세요.

================ 절대 규칙 (위반 시 작성 실패로 간주) ================
1. 아래 영상별 보고서에 등장하지 않은 사실, 수치, 사양, 가격, 비교 제품, 출시일,
   리뷰어 이름 등을 새로 만들어 내지 않는다.
2. 어떤 차원/항목에 대해 입력 보고서에 정보가 없으면 반드시 "데이터 부족"으로 표기한다.
   추정, 일반 상식, 사전 지식으로 빈칸을 채우지 않는다.
3. 점수, 합의도, 빈도수는 입력 보고서에 등장한 표현을 근거로만 산출한다.
   계산 근거가 없으면 "데이터 부족".
4. 인용 시 어느 영상(영상 N)에서 나온 의견인지 표기한다.

================ 입력: 영상별 자막 기반 보고서 ================
{joined}

================ 출력 형식 (마크다운, 9개 섹션 + 메타 박스) ================
## ① 한줄 구매 판정 + 종합 점수
- 한 문장 결론
- 종합 평가: X.X / 10  (분석 영상 {n}개 기반)
- 리뷰어 합의도: 높음 / 중간 / 낮음

## ② 핵심 요약 (3~5문장)

## ③ 6차원 종합 평가
| 차원 | 점수 | 커버리지 | 리뷰어 합의 | 핵심 코멘트 |
| --- | --- | --- | --- | --- |
| 배터리 | ... | N/{n} 영상 | ... | ... |
| 가격 | ... | ... | ... | ... |
| 카메라 | ... | ... | ... | ... |
| 성능 | ... | ... | ... | ... |
| 디스플레이 | ... | ... | ... | ... |
| 디자인 | ... | ... | ... | ... |
- 1개 영상에서만 언급된 차원은 점수 대신 "데이터 부족"으로 표기

## ④ 장점 / 단점 (합의 기반)
- 2명 이상 영상에서 언급된 항목만 합의 항목으로 채택, 빈도수(N/{n})를 함께 표기
- 1명만 언급한 항목은 별도 "개별 리뷰어 의견"으로 분리

## ⑤ 리뷰어 간 의견이 갈리는 지점 (Divergence)
- 같은 항목에 대해 영상별 평가가 다른 케이스를 그대로 노출
- 가능한 경우 리뷰어 성향(엄격/관대)도 함께 표기

## ⑥ 리뷰어 vs 실사용자 갭
- 영상별 보고서 안에 댓글/실사용자 언급이 있는 경우만 작성
- 입력 보고서에 없는 댓글 데이터를 새로 만들지 말 것
- 해당 정보가 없으면 "데이터 부족"

## ⑦ 전작 대비 달라진 점 (표)
| 항목 | 전작 | 현재 | 변화 평가 | 언급 영상 수 |

## ⑧ 이런 사람에게 추천 / 비추
- 각 항목 옆에 근거(영상 N) 표기

## ⑨ 경쟁/대체 제품 비교
- 입력 보고서에 등장한 경쟁 제품에 한해서만 비교

---
📊 분석 기반
   분석 영상: {n}개
   리뷰어 성향: (영상별 보고서에 명시된 경우에만)
   {today_line}
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
