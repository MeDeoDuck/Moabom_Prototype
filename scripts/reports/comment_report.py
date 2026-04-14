"""
Comment sentiment report generation service
"""
from typing import Optional
import psycopg2
from psycopg2.extras import RealDictCursor
from scripts.config import GROQ_API_KEY, GROQ_MODEL, DATABASE_URL
from scripts.reports.transcript_report import fix_encoding, _extract_validated_report

try:
    from openai import OpenAI
except ImportError:
    OpenAI = None


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
            SELECT c.comment_id, c.text_raw, cs.sentiment_label, cs.sentiment_score
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
        
        # Count sentiments
        positive_count = sum(1 for c in comments if c.get("sentiment_label") == "positive")
        negative_count = sum(1 for c in comments if c.get("sentiment_label") == "negative")
        neutral_count = sum(1 for c in comments if c.get("sentiment_label") == "neutral")
        
        total = len(comments)
        
        # Generate report from cached sentiments
        if OpenAI is not None and GROQ_API_KEY:
            try:
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
본문은 200~300자(허용 180~330자)로 작성하고, 마지막 줄에 반드시 [END]만 단독 출력하세요.
"""
                
                client = OpenAI(
                    api_key=GROQ_API_KEY,
                    base_url="https://api.groq.com/openai/v1"
                )
                
                retry_prompt = (
                    "\n\n형식이 맞지 않으면 다시 작성하세요: 본문 200~300자(허용 180~330자), 마지막 줄 [END]."
                )
                for attempt in range(2):
                    prompt = llama_prompt if attempt == 0 else (llama_prompt + retry_prompt)
                    response = client.chat.completions.create(
                        model=GROQ_MODEL,
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

                print("[WARN] Comment report output format invalid after retry, using heuristic summary")
            except Exception as e:
                print(f"[WARN] Llama analysis failed: {e}, using heuristic summary")
        
        # Fallback: Heuristic sentiment analysis
        pos_comment_ids = [c.get("comment_id") for c in comments if c.get("sentiment_label") == "positive"]
        neg_comment_ids = [c.get("comment_id") for c in comments if c.get("sentiment_label") == "negative"]
        neutral_comment_ids = [c.get("comment_id") for c in comments if c.get("sentiment_label") == "neutral"]
        
        pos_count = len(pos_comment_ids)
        neg_count = len(neg_comment_ids)
        neutral_count = len(neutral_comment_ids)
        
        # Generate heuristic summary report
        lines = [
            f"[{product_name} 댓글 반응 분석]",
            f"총 댓글: {total}개 (긍정: {pos_count}, 중립: {neutral_count}, 부정: {neg_count})",
            "",
        ]
        
        pos_percent = (pos_count / total * 100) if total > 0 else 0
        neg_percent = (neg_count / total * 100) if total > 0 else 0
        
        # Show positive comments
        if pos_count > 0:
            lines.append(f"✅ 긍정 반응 ({pos_count}개, {pos_percent:.1f}%):")
            pos_comment_texts = [c.get("text_raw", "") for c in comments if c.get("comment_id") in pos_comment_ids]
            for i, comment in enumerate(pos_comment_texts[:5], 1):
                short_text = comment[:60] + "..." if len(comment) > 60 else comment
                lines.append(f"  {i}. {short_text}")
            lines.append("")
        
        # Show negative comments
        if neg_count > 0:
            lines.append(f"❌ 부정 반응 ({neg_count}개, {neg_percent:.1f}%):")
            neg_comment_texts = [c.get("text_raw", "") for c in comments if c.get("comment_id") in neg_comment_ids]
            for i, comment in enumerate(neg_comment_texts[:5], 1):
                short_text = comment[:60] + "..." if len(comment) > 60 else comment
                lines.append(f"  {i}. {short_text}")
            lines.append("")
        
        # Analysis and conclusion
        lines.append("📊 종합 평가:")
        
        if pos_count > 0 and neg_count == 0:
            lines.append(f"→ 모든 댓글이 긍정적입니다 (긍정만 {pos_count}개)")
        elif neg_count > 0 and pos_count == 0:
            lines.append(f"→ 모든 댓글이 부정적입니다 (부정만 {neg_count}개)")
        elif pos_count > neg_count:
            diff_percent = ((pos_count - neg_count) / neg_count * 100) if neg_count > 0 else 0
            lines.append(f"→ 긍정이 우세 (긍정이 부정보다 {diff_percent:.1f}% 더 많음)")
        elif neg_count > pos_count:
            diff_percent = ((neg_count - pos_count) / pos_count * 100) if pos_count > 0 else 0
            lines.append(f"→ 부정이 우세 (부정이 긍정보다 {diff_percent:.1f}% 더 많음)")
        else:
            lines.append(f"→ 긍정과 부정이 동등 ({pos_count}개씩)")
        
        result = "\n".join(lines)
        fixed_result = fix_encoding(result)
        return fixed_result if len(fixed_result) <= 2000 else fixed_result[:2000]
        
    except Exception as e:
        print(f"[ERROR] build_comment_sentiment_report: {e}")
        return None
