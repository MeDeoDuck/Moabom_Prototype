"""
Transcript report generation service
"""
import re
from typing import Dict
from scripts.config import GROQ_API_KEY, GROQ_MODEL
from scripts.utils.prompt_manager import build_transcript_report_prompt

try:
    from openai import OpenAI
except ImportError:
    OpenAI = None


def _extract_validated_report(llm_text: str, min_chars: int = 1, max_chars: int = 1500) -> str:
    """Validate [END] marker and body length, then return cleaned body text."""
    if not llm_text:
        return ""
    text = llm_text.strip()
    if not text.endswith("[END]"):
        return ""
    body = text[:text.rfind("[END]")].strip()
    body_len = len(body)
    if body_len < min_chars or body_len > max_chars:
        return ""
    return body


def fix_encoding(text: str) -> str:
    """Attempt to fix garbled Korean characters."""
    if not text:
        return text
    
    try:
        # Try to detect and fix mojibake
        replacements = {
            "几乎": "거의",
            "提出": "제시",
            "相同": "동일",
            "类似": "유사",
        }
        
        result = text
        for old, new in replacements.items():
            result = result.replace(old, new)
        
        return result.encode('utf-8', errors='ignore').decode('utf-8', errors='ignore')
    except Exception as e:
        print(f"[ENCODING] Fix failed: {e}")
        return text


def build_transcript_report_heuristic(transcript_text: str) -> str:
    """
    Build a detailed product analysis report from transcript using rule-based approach.
    1. Product Description (features, specs, capabilities mentioned)
    2. Evaluation & Review (likes, dislikes, recommendations)
    3. Key Takeaways
    """
    normalized = re.sub(r"\s+", " ", transcript_text or "").strip()
    if not normalized:
        return "No transcript content available."

    sentences = re.split(r"(?<=[.!?])\s+", normalized)
    sentences = [s.strip() for s in sentences if len(s.strip()) > 5]

    if not sentences:
        return "Transcript too short to analyze."

    # Feature keywords
    feature_keywords = {
        "design", "feature", "spec", "performance", "battery", "camera", "display",
        "processor", "memory", "storage", "screen", "build", "material", "size",
        "weight", "quality", "speed", "power", "sound", "audio", "video",
        "기능", "디자인", "성능", "배터리", "카메라", "디스플레이", "프로세서",
        "메모리", "저장", "화면", "품질", "속도"
    }
    
    description_sentences = []
    for sentence in sentences:
        sentence_lower = sentence.lower()
        if any(kw in sentence_lower for kw in feature_keywords):
            description_sentences.append(sentence)
    
    description_sentences = description_sentences[:3]

    # Sentiment indicators
    positive_indicators = {
        "good", "great", "excellent", "amazing", "awesome", "best", "perfect",
        "love", "like", "recommend", "worth", "impressed", "impressive",
        "beautiful", "smooth", "fast", "excellent", "outstanding",
        "좋다", "훌륭하다", "추천", "완벽", "훌륭", "빠르다", "훌륭한"
    }
    
    negative_indicators = {
        "bad", "poor", "terrible", "awful", "horrible", "worst", "useless",
        "hate", "dislike", "problem", "issue", "broken", "disappointing",
        "waste", "regret", "slow", "expensive", "cheap", "fragile",
        "나쁘다", "문제", "느리다", "비싸다", "싼", "약하다"
    }
    
    positive_sentences = []
    negative_sentences = []
    
    for sentence in sentences:
        sentence_lower = sentence.lower()
        pos_count = sum(1 for word in positive_indicators if word in sentence_lower)
        neg_count = sum(1 for word in negative_indicators if word in sentence_lower)
        
        if pos_count > neg_count:
            positive_sentences.append(sentence)
        elif neg_count > pos_count:
            negative_sentences.append(sentence)

    # Keyword extraction
    token_candidates = re.findall(r"[A-Za-z0-9가-힣]{2,}", normalized.lower())
    stopwords = {
        "this", "that", "with", "from", "have", "will", "your", "about", "there",
        "would", "they", "them", "then", "into", "here", "just", "also", "than",
        "when", "what", "the", "and", "for", "but", "are", "has", "been", "is",
        "있는", "그리고", "합니다", "하는", "에서", "으로", "하는데", "것", "수"
    }
    
    filtered_tokens = [t for t in token_candidates if t not in stopwords and len(t) >= 2]
    token_counts: Dict[str, int] = {}
    for token in filtered_tokens:
        token_counts[token] = token_counts.get(token, 0) + 1
    
    top_keywords = sorted(token_counts.items(), key=lambda x: x[1], reverse=True)[:6]

    # Build report
    report_lines = [
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        "PRODUCT ANALYSIS REPORT FROM VIDEO TRANSCRIPT",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        "",
        "📋 PRODUCT DESCRIPTION",
        "-" * 40,
    ]
    
    if description_sentences:
        for idx, sent in enumerate(description_sentences, 1):
            truncated = (sent[:150] + "...") if len(sent) > 150 else sent
            report_lines.append(f"{idx}. {truncated}")
    else:
        report_lines.append("(No specific product features mentioned)")
    
    report_lines.append("")
    
    report_lines.extend([
        "👍 POSITIVE POINTS",
        "-" * 40,
    ])
    
    if positive_sentences:
        for sent in positive_sentences[:2]:
            truncated = (sent[:140] + "...") if len(sent) > 140 else sent
            report_lines.append(f"• {truncated}")
    else:
        report_lines.append("(No positive remarks found)")
    
    report_lines.append("")
    
    report_lines.extend([
        "⚠️  CONCERNS & CRITICISMS",
        "-" * 40,
    ])
    
    if negative_sentences:
        for sent in negative_sentences[:2]:
            truncated = (sent[:140] + "...") if len(sent) > 140 else sent
            report_lines.append(f"• {truncated}")
    else:
        report_lines.append("(No significant concerns mentioned)")
    
    report_lines.append("")
    
    report_lines.extend([
        "🔑 KEY TOPICS MENTIONED",
        "-" * 40,
    ])
    
    if top_keywords:
        keyword_list = ", ".join([f"{k}({c})" for k, c in top_keywords])
        report_lines.append(keyword_list)
    else:
        report_lines.append("N/A")
    
    report_lines.extend([
        "",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        f"Transcript length: {len(normalized)} characters | Sentences analyzed: {len(sentences)}",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
    ])
    
    result = "\n".join(report_lines)
    return fix_encoding(result)


def build_transcript_report(transcript_text: str) -> str:
    """
    Build transcript report with Groq Llama and strict format validation.
    Retry up to 3 times with explicit output format instructions.
    """
    normalized = re.sub(r"\s+", " ", transcript_text or "").strip()
    if not normalized:
        return "No transcript content available."

    if OpenAI is None or not GROQ_API_KEY:
        error_msg = "[ERROR] Transcript report generation failed: Groq Llama not configured."
        print(error_msg)
        return error_msg

    try:
        client = OpenAI(
            api_key=GROQ_API_KEY,
            base_url="https://api.groq.com/openai/v1"
        )
        base_prompt = build_transcript_report_prompt(normalized)
        max_attempts = 3

        for attempt in range(max_attempts):
            retry_prompt = (
                "\n\n이전 응답이 형식 조건을 충족하지 않았습니다. "
                "이번에는 반드시 본문 1000자 이내로 작성하고, "
                "마지막 줄 단독 [END]를 지켜 다시 작성하세요."
            )
            prompt = base_prompt if attempt == 0 else (base_prompt + retry_prompt)
            response = client.chat.completions.create(
                model=GROQ_MODEL,
                max_tokens=800,
                messages=[
                    {"role": "user", "content": prompt}
                ]
            )
            llm_text = response.choices[0].message.content if response.choices else None
            validated = _extract_validated_report(llm_text or "")
            if validated:
                fixed_text = fix_encoding(validated)
                return f"[자막 기반 제품 분석 보고서]\n\n{fixed_text}"
            print(
                f"[WARN] Transcript analysis format invalid at attempt {attempt + 1}/{max_attempts} "
                "(requested<=1000, validation_max=1500)"
            )

        error_msg = "[ERROR] Transcript analysis output format invalid after 3 attempts"
        print(error_msg)
        return error_msg
    except Exception as e:
        error_msg = f"[ERROR] Transcript analysis failed: {e}"
        print(error_msg)
        return error_msg
