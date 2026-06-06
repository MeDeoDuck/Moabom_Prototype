"""lang_normalize (설계 §4 [5]).

임베딩 입력 언어를 한국어로 통일 — PoC 에서 언어가 클러스터 1차 분할축이라
통일 시 관점 분리가 살아난다. 영문 후보만 RunYourAI GPT-4.1 1콜로 한국어
번역, 한국어는 그대로 통과. 실전 후보 대부분 한국어라 평소 비용 ≈ 0.

입력 텍스트 = `제목 + 설명 앞부분`. 번역 실패 시 원문 유지(안전 퇴화).
"""
from __future__ import annotations

import json
import re

_HANGUL_RE = re.compile(r"[가-힣]")
_LATIN_RE = re.compile(r"[A-Za-z]")


def is_english(text: str) -> bool:
    """한글이 거의 없고 라틴 알파벳 위주면 영문으로 판정.

    혼용(한글 일부 포함)은 한국어로 본다 — 번역 불필요.
    """
    if not text:
        return False
    hangul = len(_HANGUL_RE.findall(text))
    latin = len(_LATIN_RE.findall(text))
    if latin == 0:
        return False
    # 한글이 라틴의 10% 미만이면 영문 취급
    return hangul < max(1, latin * 0.1)


_TRANSLATE_SCHEMA = {
    "name": "translations",
    "schema": {
        "type": "object",
        "properties": {
            "items": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "integer"},
                        "ko": {"type": "string"},
                    },
                    "required": ["id", "ko"],
                    "additionalProperties": False,
                },
            }
        },
        "required": ["items"],
        "additionalProperties": False,
    },
    "strict": True,
}

_TRANSLATE_SYSTEM = (
    "다음 유튜브 영상 제목·설명들을 자연스러운 한국어로 번역하세요. "
    "제품명·브랜드·모델명은 원형 유지. 의미만 한국어로 옮기고 과장·요약 금지. "
    "각 항목의 id 를 그대로 반환하세요."
)


def normalize_texts(texts: list[str]) -> tuple[list[str], dict]:
    """영문 항목만 번역해 한국어로 통일한 텍스트 리스트 반환.

    반환: (정규화 텍스트(입력 순서 정렬), meta{n_total, n_english, translated, error?})
    번역 LLM 실패 시 원문 유지 + meta["error"].
    """
    meta = {"n_total": len(texts), "n_english": 0, "translated": False}
    if not texts:
        return [], meta

    en_idx = [i for i, t in enumerate(texts) if is_english(t)]
    meta["n_english"] = len(en_idx)
    if not en_idx:
        return list(texts), meta

    result = list(texts)
    payload = [{"id": i, "text": texts[i][:1200]} for i in en_idx]
    try:
        from video_selection_agent.llm.azure_openai_client import AzureOpenAIClient

        data = AzureOpenAIClient().chat_structured(
            system=_TRANSLATE_SYSTEM,
            user=json.dumps(payload, ensure_ascii=False),
            json_schema=_TRANSLATE_SCHEMA,
            max_tokens=2000,
            temperature=0.0,
        )
        for item in data.get("items", []):
            idx = int(item["id"])
            ko = item.get("ko", "")
            if ko and 0 <= idx < len(result):
                result[idx] = ko
        meta["translated"] = True
    except Exception as e:  # 번역 실패 → 원문 유지(안전 퇴화)
        meta["error"] = f"translate failed: {e}"
        print(f"[lang_normalize] {meta['error']}", flush=True)

    return result, meta
