"""
자막 기반 제품 핵심 인사이트 보고서 생성 (RunYourAI 통합 — 기본 openai/gpt-4.1)

- v1 프롬프트(구매 결정 애널리스트 페르소나 + few-shot 2종)
- 자막이 매우 길 경우(150,000자 초과) 청킹 후 청크별 중간 요약 → 최종 보고서로 합성
- get_report_llm_client / REPORT_LLM_DEPLOYMENT / fix_encoding / _extract_validated_report:
  comment_report.py / integrated_report.py 가 동일 클라이언트와 검증 헬퍼를 재사용하도록 export
"""
import re
from openai import OpenAI

from scripts.config import (
    RUNYOURAI_API_KEY,
    RUNYOURAI_BASE_URL,
    RUNYOURAI_MODEL,
)

# ── 청킹 기준 ──────────────────────────────────────────────────
# GPT-4.1 128K 컨텍스트 기준
CHUNK_THRESHOLD = 150_000
CHUNK_SIZE = 100_000
CHUNK_OVERLAP = 3_000

# ── 검증 파라미터 (comment_report / integrated_report 가 사용) ──
VALIDATION_MAX_CHARS = 1500

# 보고서가 사용하는 모델 이름 (모듈 표면에 export — 이름은 하위 호환)
REPORT_LLM_DEPLOYMENT = RUNYOURAI_MODEL

# ── LLM 클라이언트 ──────────────────────────────────────────────
_client = None


def get_report_llm_client() -> OpenAI:
    """보고서 3종이 공유하는 OpenAI-호환 (RunYourAI) lazy 싱글턴."""
    global _client
    if _client is None:
        if not RUNYOURAI_API_KEY:
            raise ValueError(
                "RUNYOURAI_API_KEY 환경변수가 설정되지 않았습니다. "
                ".env 또는 Container App secret(runyourai-key)을 확인하세요."
            )
        _client = OpenAI(
            api_key=RUNYOURAI_API_KEY,
            base_url=RUNYOURAI_BASE_URL,
        )
    return _client


def _get_client() -> OpenAI:  # 내부 호환 alias
    return get_report_llm_client()


# ── 프롬프트 (v1 verbatim) ─────────────────────────────────────

_SYSTEM_PROMPT = """당신은 테크 제품 구매 결정 전문 애널리스트입니다.
유튜브 리뷰 영상의 자막을 읽고, 바쁜 소비자가 "이 제품을 살지 말지"를 빠르게 판단할 수 있는 핵심 인사이트 보고서를 작성합니다.

규칙:
- 영상 요약이 아닌 구매 판단에 필요한 인사이트만 추출
- 수치(배터리 시간, 주사율, 밝기, 무게, 가격 등)가 자막에 언급되면 반드시 괄호로 병기
  예) 배터리 지속 시간 우수 (실사용 12시간, 전작 대비 +2시간)
- 수치가 없으면 "(수치 미언급)" 표기, 절대 추측하지 말 것
- 장단점은 리뷰어 평가 강도를 기호로 구분
  ◎ 확실한 강점 / ○ 장점 / △ 아쉬운 점 / ✕ 명확한 단점
- 전작 비교는 반드시 표로 작성, 비교 언급이 없어도 "비교 언급 없음" 표기
- 없는 정보는 "언급 없음"으로 표기, 절대 추측 금지
- 반드시 아래 형식을 그대로 따를 것"""

_CHUNK_PROMPT = """아래는 유튜브 테크 리뷰 영상 자막의 일부(파트 {chunk_num})입니다.
이 부분에서 보고서 작성에 필요한 핵심 정보를 아래 항목별로 빠짐없이 추출하세요.

자막 파트 {chunk_num}:
{chunk}

다음 항목별로 언급된 정보를 bullet point로 정리하세요. 언급 없으면 해당 항목 생략:
- **수치 정보**: 스펙 수치, 가격, 무게 등 구체적인 숫자 (반드시 수치 그대로 기록)
- **장점/강점**: 리뷰어가 긍정적으로 평가한 내용
- **단점/아쉬운 점**: 리뷰어가 부정적으로 평가한 내용
- **전작 비교**: 전작 대비 변화 언급
- **추천/비추 대상**: 리뷰어가 언급한 적합/부적합 사용자
- **기타 주요 언급**: 위에 해당하지 않는 중요 정보"""

_FINAL_PROMPT = """아래 두 가지 예시를 참고해 주어진 자막으로 동일한 형식의 보고서를 작성하세요.

---
[예시 1 — 수치 정보가 풍부한 경우]

### 입력 자막 (요약):
"갤럭시 S24 울트라 리뷰입니다. 디스플레이는 6.8인치 120Hz, 최대 밝기 2600니트로 전작 1750니트 대비 확실히 밝아졌어요. 무게는 232g으로 전작 234g에서 소폭 감소. 배터리는 5000mAh 동일한데 최적화가 잘 돼서 실사용 하루 반은 거뜬합니다. 전작은 하루 빠듯했어요. 발열은 여전히 있고 장시간 게임 시 성능 하락이 느껴집니다. 티타늄 프레임으로 바뀌면서 그립감이 좋아졌어요. AI 기능이 대폭 추가됐는데 실사용에서 유용합니다. 가격은 169만원으로 전작보다 10만원 올랐어요. S펜 헤비유저나 영상 편집 유저에게 강력 추천, 일반 사용자는 S24 기본이 낫습니다."

### 출력:
---
## 📦 제품 핵심 인사이트 보고서
**제품명:** 삼성 갤럭시 S24 울트라

---
### 장점 / 단점

**장점**
- ◎ 디스플레이 밝기 대폭 향상 (최대 2600 nit, 전작 1750 nit 대비 +49%)
- ◎ AI 기능 실사용 유용성 확인 (리뷰어 직접 언급)
- ○ 배터리 효율 개선 (5000mAh 동일 용량, 실사용 하루 반 / 전작 하루 빠듯)
- ○ 티타늄 프레임으로 그립감 개선
- ○ 경량화 (232g → 전작 234g 대비 2g 감소)

**단점**
- ✕ 발열 미해결 — 장시간 게임 시 성능 하락 체감 (전작과 동일 수준)
- △ 가격 인상 (169만원, 전작 대비 +10만원) 대비 하드웨어 업그레이드 체감 미미
- △ 일반 사용자에게는 과스펙 (리뷰어 직접 언급)

---
### 전작 대비 달라진 것

| 항목 | S23 울트라 | S24 울트라 | 변화 |
|------|-----------|-----------|------|
| 디스플레이 밝기 | 1750 nit | 2600 nit | ↑ +49% |
| 무게 | 234g | 232g | ↑ 소폭 감소 |
| 배터리 용량 | 5000mAh | 5000mAh | 동일 |
| 배터리 실사용 | 하루 빠듯 | 하루 반 | ↑ 개선 |
| 프레임 소재 | 알루미늄 | 티타늄 | ↑ 개선 |
| AI 기능 | 기본 | 대폭 강화 | ↑ 개선 |
| 발열 | 있음 | 있음 | 동일 |
| 가격 | 159만원 | 169만원 | ↓ +10만원 |

---
### 이런 사람한테 맞습니다
- S펜을 실제로 쓰는 메모·스케치 헤비유저
- 스마트폰으로 영상 편집 등 고성능 작업을 하는 사람
- 야외 사용이 많아 고밝기 디스플레이가 필요한 사람

### 이런 사람한테는 비추
- S펜 사용 계획 없는 일반 사용자 → S24 기본 모델이 합리적
- 발열·성능 하락에 민감한 게이머
- 전작(S23 울트라) 사용 중인 사람 → 업그레이드 메리트 낮음

---
### 차별성 & 구매 합리성
- S펜 내장 플래그십은 시장에서 사실상 독보적 포지션
- 전작 대비 가격 +10만원이나, 하드웨어 스펙 업그레이드 폭은 크지 않음 (디스플레이·AI 제외)
- 신규 구매라면 합리적, 전작 사용자라면 업그레이드 메리트 낮음

---
### 리뷰어가 강조한 핵심 포인트
1. AI 기능이 이 제품의 핵심 셀링포인트 — 실사용 유용성 직접 확인
2. 디스플레이 밝기 향상이 가장 눈에 띄는 하드웨어 개선
3. 발열은 여전히 미해결 과제
4. S펜 유저에게는 대안 없는 선택지, 일반 유저에게는 과스펙

---
### 🛒 한 줄 구매 판정
> **S펜·고성능 작업 유저라면 명확한 선택. 전작 사용자나 일반 유저는 패스.**
---


[예시 2 — 수치 정보가 부족한 경우]

### 입력 자막 (요약):
"소니 WH-1000XM5 리뷰입니다. 노이즈 캔슬링이 전작보다 좋아졌고, 가벼워졌어요. 착용감도 편하고 통화 품질도 나쁘지 않습니다. 40만원대 가격입니다."

### 출력:
---
## 📦 제품 핵심 인사이트 보고서
**제품명:** 소니 WH-1000XM5

---
### 장점 / 단점

**장점**
- ◎ 노이즈 캔슬링 전작 대비 향상 (수치 미언급)
- ○ 경량화 (구체적 무게 수치 미언급)
- ○ 착용감 편함 (수치 미언급)
- ○ 통화 품질 양호 (수치 미언급)

**단점**
- 언급 없음

---
### 전작 대비 달라진 것

| 항목 | XM4 | XM5 | 변화 |
|------|-----|-----|------|
| 노이즈 캔슬링 | - | 향상 | ↑ (수치 미언급) |
| 무게 | - | 감소 | ↑ (수치 미언급) |
| 착용감 | - | 개선 | ↑ (수치 미언급) |

*(전작 구체적 수치 비교는 리뷰에서 언급 없음)*

---
### 이런 사람한테 맞습니다
- 노이즈 캔슬링이 최우선인 사용자
- 장시간 착용이 필요한 사용자 (착용감 강조)

### 이런 사람한테는 비추
- 언급 없음

---
### 차별성 & 구매 합리성
- 경쟁 제품 비교 및 가격 합리성 평가는 리뷰에서 다루지 않음
- 이 리뷰만으로는 구매 합리성 판단 정보 부족

---
### 리뷰어가 강조한 핵심 포인트
1. 노이즈 캔슬링 성능 향상이 핵심 강점
2. 경량화 및 착용감 개선

---
### 🛒 한 줄 구매 판정
> **노이즈 캔슬링 목적이라면 유력한 선택지. 단, 이 리뷰만으로는 경쟁 제품 대비 판단 정보 부족.**
---


[실제 입력]
아래 자막을 분석해서 위 형식으로 보고서를 작성하세요.
수치가 언급된 경우 반드시 괄호로 병기하고, 없는 정보는 반드시 "언급 없음" 또는 "수치 미언급"으로 표기하세요.

### 입력 자막:
{text}"""


# ── 검증 / 인코딩 보정 ─────────────────────────────────────────

def _extract_validated_report(llm_text: str, min_chars: int = 1, max_chars: int = VALIDATION_MAX_CHARS) -> str:
    """[END] 마커와 본문 길이를 검증하고 통과 시 본문 텍스트를 반환.

    transcript 경로에서는 호출하지 않으나 comment_report / integrated_report 가
    동일 검증 규칙을 공유하므로 export 유지.
    """
    if not llm_text:
        return ""
    text = llm_text.strip()
    if not text.endswith("[END]"):
        return ""
    body = text[: text.rfind("[END]")].strip()
    body_len = len(body)
    if body_len < min_chars or body_len > max_chars:
        return ""
    return body


def fix_encoding(text: str) -> str:
    """한국어 인코딩 깨짐 보정 (integrated_report.py에서도 사용)."""
    if not text:
        return text
    try:
        return text.encode("utf-8", errors="ignore").decode("utf-8", errors="ignore")
    except Exception:
        return text


# ── 내부 유틸 ───────────────────────────────────────────────────

def _split_chunks(text: str) -> list:
    chunks = []
    start = 0
    while start < len(text):
        end = min(start + CHUNK_SIZE, len(text))
        chunks.append(text[start:end])
        start = end - CHUNK_OVERLAP if end < len(text) else end
    return chunks


def _call_llm(prompt: str, system_prompt: str = "", temperature: float = 0.3) -> str:
    client = get_report_llm_client()
    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": prompt})

    response = client.chat.completions.create(
        model=REPORT_LLM_DEPLOYMENT,
        messages=messages,
        temperature=temperature,
        max_tokens=4096,
    )
    return response.choices[0].message.content.strip()


# ── 메인 함수 ────────────────────────────────────────────────────

def build_transcript_report(transcript_text: str) -> str:
    """
    자막 기반 제품 핵심 인사이트 보고서 생성.

    - 150,000자 이하: 전체 자막을 한 번에 처리
    - 150,000자 초과: 청크별 중간 요약 후 최종 보고서 합성
    """
    normalized = re.sub(r"\s+", " ", transcript_text or "").strip()
    if not normalized:
        return "No transcript content available."

    if not RUNYOURAI_API_KEY:
        error_msg = "[ERROR] Transcript report generation failed: RUNYOURAI_API_KEY not configured."
        print(error_msg)
        return error_msg

    print(f"  [자막 보고서] 자막 길이: {len(normalized):,}자")

    try:
        if len(normalized) <= CHUNK_THRESHOLD:
            prompt = _FINAL_PROMPT.format(text=normalized)
            report = _call_llm(prompt, _SYSTEM_PROMPT)
        else:
            chunks = _split_chunks(normalized)
            print(f"  [자막 보고서] {len(chunks)}개 청크로 분할 처리")

            summaries = []
            for i, chunk in enumerate(chunks):
                print(f"  [자막 보고서] 청크 {i + 1}/{len(chunks)} 중간 요약 중...")
                chunk_prompt = _CHUNK_PROMPT.format(chunk_num=i + 1, chunk=chunk)
                summary = _call_llm(chunk_prompt, _SYSTEM_PROMPT)
                summaries.append(summary)

            combined = "\n\n---\n\n".join(summaries)
            print(f"  [자막 보고서] 최종 보고서 생성 중...")
            final_prompt = _FINAL_PROMPT.format(text=combined)
            report = _call_llm(final_prompt, _SYSTEM_PROMPT)

        return fix_encoding(report)

    except Exception as e:
        error_msg = f"[ERROR] Transcript report generation failed: {e}"
        print(error_msg)
        return error_msg
