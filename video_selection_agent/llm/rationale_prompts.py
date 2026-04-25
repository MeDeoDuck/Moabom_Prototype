"""`llm_rerank` / `generate_rationale` 노드 프롬프트.

프롬프트 텍스트만 이 파일에 상수로 모음 — 코드와 분리해 튜닝 용이.
"""
from __future__ import annotations

RERANK_SYSTEM_PROMPT = """당신은 유튜브 리뷰 영상을 선별하는 전문가입니다.
각 후보에 대해 topical_fit(0-1)과 100자 이내 한국어 rationale_short를 부여하세요.

감점: 언박싱만 있는 영상, 라이브스트림, 단순 리액션.
가점: 비교 리뷰, 장기 사용기, 스펙 심층 분석, 비판적 리뷰.
"""


RERANK_JSON_SCHEMA = {
    "name": "rerank_result",
    "schema": {
        "type": "object",
        "properties": {
            "results": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "video_id": {"type": "string"},
                        "topical_fit": {"type": "number"},
                        "rationale_short": {"type": "string"},
                    },
                    "required": ["video_id", "topical_fit", "rationale_short"],
                    "additionalProperties": False,
                },
            }
        },
        "required": ["results"],
        "additionalProperties": False,
    },
    "strict": True,
}


RATIONALE_SYSTEM_PROMPT = """선정된 유튜브 영상들에 대해 각각 2-3문장 한국어 rationale을 작성하세요.
중립적·사실 기반 작성, 과장 금지. 점수 차원과 채널 티어, 리뷰어 관점 다양성을 반영.
"""


RATIONALE_JSON_SCHEMA = {
    "name": "rationale_result",
    "schema": {
        "type": "object",
        "properties": {
            "rationales": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "video_id": {"type": "string"},
                        "rationale_full": {"type": "string"},
                    },
                    "required": ["video_id", "rationale_full"],
                    "additionalProperties": False,
                },
            }
        },
        "required": ["rationales"],
        "additionalProperties": False,
    },
    "strict": True,
}
