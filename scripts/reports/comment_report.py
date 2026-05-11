"""
Comment sentiment report generation service (RunYourAI / openai/gpt-4.1-2025-04-14)
"""
from typing import Optional
import psycopg2
from psycopg2.extras import RealDictCursor
from scripts.config import DATABASE_URL
from scripts.reports.transcript_report import (
    fix_encoding,
    _extract_validated_report,
    get_report_llm_client,
    REPORT_LLM_DEPLOYMENT,
)


def _compute_weighted_sentiment_metrics(comments):
    """
    Weighted aggregation with fallback:
    - analysis_weight missing/NULL -> 1.0
    Returns dict while keeping report interface unchanged.
    """
    weighted_totals = {"positive": 0.0, "negative": 0.0, "neutral": 0.0}
    total_weight = 0.0
    analyzed_count = 0
    low_conf_weight_count = 0

    for c in comments:
        label = c.get("sentiment_label")
        if label not in weighted_totals:
            continue
        weight = c.get("analysis_weight")
        if weight is None:
            weight = 1.0
        weight = float(weight)
        weighted_totals[label] += weight
        total_weight += weight
        analyzed_count += 1
        if weight < 1.0:
            low_conf_weight_count += 1

    if total_weight <= 0:
        return {
            "positive_weighted_ratio": 0.0,
            "negative_weighted_ratio": 0.0,
            "neutral_weighted_ratio": 0.0,
            "total_weight": 0.0,
            "low_confidence_ratio": 0.0,
        }

    low_conf_ratio = (low_conf_weight_count / analyzed_count) if analyzed_count > 0 else 0.0
    return {
        "positive_weighted_ratio": weighted_totals["positive"] / total_weight,
        "negative_weighted_ratio": weighted_totals["negative"] / total_weight,
        "neutral_weighted_ratio": weighted_totals["neutral"] / total_weight,
        "total_weight": total_weight,
        "low_confidence_ratio": low_conf_ratio,
    }

def build_comment_sentiment_report(video_id: str, product_name: str = "제품") -> Optional[str]:
    """
    Build comment sentiment analysis report using cached sentiment data.
    Sentiments are analyzed during sync phase, not during report generation.
    This function just formats the cached results into a report.
    """
    try:
        conn = psycopg2.connect(DATABASE_URL)
        cur = conn.cursor(cursor_factory=RealDictCursor)
        
        # Fetch comments with cached sentiment data
        cur.execute("""
            SELECT c.comment_id, c.text_raw, cs.sentiment_label, cs.sentiment_score, cs.analysis_weight
            FROM comments c
            LEFT JOIN comment_sentiments cs ON c.comment_id = cs.comment_id
            WHERE c.video_id = %s
            ORDER BY c.created_at DESC
        """, (video_id,))
        
        comments = cur.fetchall()
        cur.close()
        conn.close()
        
        if not comments:
            return None
        
        # Count sentiments (keep existing interface counts)
        positive_count = sum(1 for c in comments if c.get("sentiment_label") == "positive")
        negative_count = sum(1 for c in comments if c.get("sentiment_label") == "negative")
        neutral_count = sum(1 for c in comments if c.get("sentiment_label") == "neutral")
        weighted_metrics = _compute_weighted_sentiment_metrics(comments)
        
        total = len(comments)
        
        try:
            client = get_report_llm_client()
        except ValueError as e:
            error_msg = f"[ERROR] Comment report generation failed: {e}"
            print(error_msg)
            return error_msg

        # Prepare comment groups by sentiment
        positive_comments = [c.get("text_raw", "") for c in comments if c.get("sentiment_label") == "positive"]
        negative_comments = [c.get("text_raw", "") for c in comments if c.get("sentiment_label") == "negative"]
        neutral_comments = [c.get("text_raw", "") for c in comments if c.get("sentiment_label") == "neutral"]
        
        # Format for Llama
        positive_text = "\n".join(f"- {c}" for c in positive_comments[:10])
        negative_text = "\n".join(f"- {c}" for c in negative_comments[:10])
        neutral_text = "\n".join(f"- {c}" for c in neutral_comments[:10])
        
        # Ask Llama to summarize the sentiment groups
        llama_prompt = f"""
당신은 유튜브 댓글 감정분석 전문가입니다. 다음은 이미 감정분석된 {product_name}에 대한 댓글들입니다.

📊 감정분석 결과:
긍정적: {positive_count}개
부정적: {negative_count}개
중립적: {neutral_count}개
총합: {total}개
가중 비율(확신도 반영): 긍정 {weighted_metrics["positive_weighted_ratio"]:.1%}, 부정 {weighted_metrics["negative_weighted_ratio"]:.1%}, 중립 {weighted_metrics["neutral_weighted_ratio"]:.1%}
저확신 비율: {weighted_metrics["low_confidence_ratio"]:.1%}

📋 긍정 댓글 (샘플):
================
{positive_text if positive_comments else "없음"}

📋 부정 댓글 (샘플):
================
{negative_text if negative_comments else "없음"}

📋 중립 댓글 (샘플):
================
{neutral_text if neutral_comments else "없음"}

📊 분석 요청:
1. 긍정 댓글의 주요 의견 요약
2. 부정 댓글의 주요 불만 요약
3. 중립 댓글의 특징 요약
4. 전체 시장 반응 평가

한국어로 전문적이고 객관적인 톤으로 분석해주세요.
본문은 1000자 이내로 작성하고, 마지막 줄에 반드시 [END]만 단독 출력하세요.
"""

        max_attempts = 3
        for attempt in range(max_attempts):
            retry_prompt = (
                "\n\n형식이 맞지 않으면 다시 작성하세요: "
                "본문 1000자 이내, 마지막 줄 [END]."
            )
            prompt = llama_prompt if attempt == 0 else (llama_prompt + retry_prompt)
            response = client.chat.completions.create(
                model=REPORT_LLM_DEPLOYMENT,
                max_tokens=800,
                messages=[{"role": "user", "content": prompt}]
            )
            if response.choices:
                llm_report = response.choices[0].message.content
                validated = _extract_validated_report(llm_report or "")
                if validated:
                    fixed_report = fix_encoding(validated)
                    header = f"[{product_name} 유튜브 댓글 분석]\n총 분석 댓글: {total}개 (긍정: {positive_count}, 부정: {negative_count}, 중립: {neutral_count})\n"
                    return header + "=" * 50 + "\n\n" + fixed_report
            print(
                f"[WARN] Comment report format invalid at attempt {attempt + 1}/{max_attempts} "
                "(requested<=1000, validation_max=1500)"
            )

        error_msg = "[ERROR] Comment report output format invalid after 3 attempts"
        print(error_msg)
        return error_msg
        
    except Exception as e:
        print(f"[ERROR] build_comment_sentiment_report: {e}")
        return None
