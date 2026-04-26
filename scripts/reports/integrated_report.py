"""
Integrated analysis report generation service
Compares reviewer (transcript) vs consumer (comments) opinions
"""
from typing import Optional
from scripts.config import GROQ_API_KEY, GROQ_MODEL
from scripts.reports.transcript_report import fix_encoding, _extract_validated_report

try:
    from openai import OpenAI
except ImportError:
    OpenAI = None


def build_integrated_analysis_report(video_id: str, product_name: str, transcript_report: str, comment_sentiment_report: str) -> Optional[str]:
    """
    통합 분석: 리뷰어(자막) + 사람들의 반응(댓글) 비교
    Llama를 사용해 의견 유사도 계산
    """
    if not transcript_report or not comment_sentiment_report:
        print(f"[DEBUG] build_integrated_analysis_report: Missing reports - transcript: {bool(transcript_report)}, comment: {bool(comment_sentiment_report)}")
        return None
    
    if OpenAI is None or not GROQ_API_KEY:
        error_msg = "[ERROR] Integrated analysis generation failed: Groq Llama not configured."
        print(error_msg)
        return error_msg

    try:
        print(f"[DEBUG] build_integrated_analysis_report: Starting Llama call for {product_name}")
        integration_prompt = f"""
당신은 시장 분석 전문가입니다. 다음 두 분석을 비교하여 통합 보고서를 작성해주세요.

📋 자막 기반 리뷰어 분석 (전문 리뷰어의 의견)
================
{transcript_report}

📋 댓글 기반 사람들의 반응 (일반 소비자의 의견)  
================
{comment_sentiment_report}

📊 통합 분석 요청
================
위 두 분석을 바탕으로 다음을 포함한 통합 보고서를 작성해주세요:

1. **리뷰어 평가 요약**
   - 자막에서 드러난 리뷰어의 핵심 평가

2. **사람들의 반응 요약**
   - 댓글에서 드러난 소비자들의 핵심 의견

3. **의견 유사도 분석**
   - 리뷰어의 의견과 소비자의 의견이 얼마나 일치하는지 분석
   - 계산 방식: 다음 항목들의 일치도를 평가
     (1) 제품 강점에 대한 평가 일치도
     (2) 제품 약점에 대한 평가 일치도
     (3) 전체 제품 평가 방향 일치도
   - 종합 유사도: (항목1 + 항목2 + 항목3) / 3 = ___%

4. **일치점과 불일치점**
   - 리뷰어와 소비자가 모두 언급한 공통 의견
   - 리뷰어는 칭찬하지만 소비자는 비판하는 부분
   - 리뷰어는 비판하지만 소비자는 칭찬하는 부분

5. **시장 인사이트**
   - 리뷰어와 소비자 간의 인식 차이가 의미하는 바
   - 제품 마케팅/개선 시 고려할 사항

✅ 작성 가이드:
- 한국어로 전문적이고 객관적인 톤 유지
- 유사도는 반드시 백분율(%)로 명시
- 계산 방식도 명확하게 표시
- 본문은 1000자 이내로 간결하게 작성
- 문장은 중간에 끊기지 않게 완결형으로 마무리
- 마지막 줄에 반드시 [END]만 단독으로 출력

보고서를 작성해주세요.
"""
            
        client = OpenAI(
            api_key=GROQ_API_KEY,
            base_url="https://api.groq.com/openai/v1"
        )

        print(f"[DEBUG] Sending request to Groq...")
        max_attempts = 3
        for attempt in range(max_attempts):
            retry_prompt = (
                "\n\n형식이 맞지 않으면 다시 작성하세요: "
                "본문 1000자 이내, 마지막 줄 [END]."
            )
            prompt = integration_prompt if attempt == 0 else (integration_prompt + retry_prompt)
            response = client.chat.completions.create(
                model=GROQ_MODEL,
                max_tokens=1200,
                messages=[{"role": "user", "content": prompt}]
            )
            if response.choices:
                llm_report = response.choices[0].message.content
                validated = _extract_validated_report(llm_report or "")
                if validated:
                    fixed_report = fix_encoding(validated)
                    print(f"[DEBUG] Received response from Groq, length: {len(llm_report)}")
                    header = f"[{product_name} 리뷰어-댓글 통합 분석 보고서]\n\n"
                    return header + fixed_report
            print(
                f"[WARN] Integrated analysis format invalid at attempt {attempt + 1}/{max_attempts} "
                "(requested<=1000, validation_max=1500)"
            )
        error_msg = "[ERROR] Integrated analysis output format invalid after 3 attempts"
        print(error_msg)
        return error_msg
    except Exception as e:
        error_msg = f"[ERROR] Integrated analysis failed: {type(e).__name__}: {e}"
        print(error_msg)
        return error_msg


def generate_and_save_all_reports(video_id: str, product_name: str, force_rewrite: bool = False):
    """
    Generate all reports (transcript, comment, integrated) and save to DB.
    If force_rewrite=False and reports exist, return cached reports.
    Returns (transcript_report, comment_report, integrated_analysis)
    """
    from scripts.database.queries import query_one, execute_update
    from scripts.reports.transcript_report import build_transcript_report
    from scripts.reports.comment_report import build_comment_sentiment_report
    
    print(f"[REPORT] START: video_id={video_id}, product={product_name}, force_rewrite={force_rewrite}")
    
    # Cache hit only when ALL three reports are present. Otherwise a row with
    # transcript_report only (saved before the comment pipeline ran) would be
    # served forever, hiding the comment/integrated reports even after comments
    # become available on a later visit.
    if not force_rewrite:
        existing_reports = query_one(
            """SELECT transcript_report, comment_report, integrated_report, updated_at
               FROM video_reports WHERE video_id = %s""",
            (video_id,)
        )
        if existing_reports and (
            existing_reports.get("transcript_report")
            and existing_reports.get("comment_report")
            and existing_reports.get("integrated_report")
        ):
            print(f"[REPORT] Using cached reports (updated: {existing_reports.get('updated_at')})")
            return (
                existing_reports.get("transcript_report"),
                existing_reports.get("comment_report"),
                existing_reports.get("integrated_report"),
            )
    
    print(f"[REPORT] Generating fresh reports...")
    try:
        # Get transcript
        transcript_row = query_one(
            "SELECT transcript_text FROM video_transcripts WHERE video_id = %s",
            (video_id,),
        )
        if not transcript_row:
            print(f"[REPORT] No transcript found")
            return None, None, None
        
        # Generate and save transcript report
        print(f"[REPORT] Generating transcript report...")
        transcript_report = build_transcript_report(transcript_row["transcript_text"])
        print(f"[REPORT] Transcript report length: {len(transcript_report) if transcript_report else 0}")
        
        # Generate and save comment report
        print(f"[REPORT] Generating comment sentiment report...")
        comment_report = build_comment_sentiment_report(video_id, product_name)
        print(f"[REPORT] Comment report length: {len(comment_report) if comment_report else 0}")
        
        # Generate integrated analysis
        integrated_analysis = None
        if transcript_report and comment_report:
            print(f"[REPORT] Generating integrated analysis...")
            integrated_analysis = build_integrated_analysis_report(
                video_id, product_name, transcript_report, comment_report
            )
            print(f"[REPORT] Integrated analysis length: {len(integrated_analysis) if integrated_analysis else 0}")
        else:
            print(f"[REPORT] Skipping integrated (transcript={bool(transcript_report)}, comment={bool(comment_report)})")
        
        # Save all reports to DB
        print(f"[REPORT] Saving to database...")
        upsert_video_report(video_id, transcript_report=transcript_report, comment_report=comment_report, integrated_report=integrated_analysis)
        print(f"[REPORT] COMPLETE")
        
        return transcript_report, comment_report, integrated_analysis
    except Exception as e:
        print(f"[REPORT] ERROR: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
        return None, None, None


def upsert_video_report(video_id: str, transcript_report: Optional[str] = None, comment_report: Optional[str] = None, integrated_report: Optional[str] = None) -> None:
    """Upsert generated reports for a video - completely replace old reports."""
    from scripts.database.queries import execute_update
    
    execute_update(
        """INSERT INTO video_reports (video_id, transcript_report, comment_report, integrated_report, updated_at)
           VALUES (%s, %s, %s, %s, NOW())
           ON CONFLICT (video_id)
           DO UPDATE SET
             transcript_report = EXCLUDED.transcript_report,
             comment_report = EXCLUDED.comment_report,
             integrated_report = EXCLUDED.integrated_report,
             updated_at = NOW()""",
        (video_id, transcript_report, comment_report, integrated_report),
    )
