"""LangChain ChatOpenAI factory wired to RunYourAI.

모든 LangChain LLM 호출은 여기서 인스턴스를 받습니다.
모델·base_url·키 교체 시 이 파일과 scripts/config.py 두 곳만 수정.
"""
from __future__ import annotations

from langchain_openai import ChatOpenAI

from scripts.config import (
    RUNYOURAI_API_KEY,
    RUNYOURAI_BASE_URL,
    RUNYOURAI_MODEL,
)


def get_chat_llm(
    *,
    temperature: float = 0.0,
    max_tokens: int | None = None,
    model: str | None = None,
) -> ChatOpenAI:
    if not RUNYOURAI_API_KEY:
        raise RuntimeError(
            "RUNYOURAI_API_KEY 환경변수가 설정되지 않았습니다. "
            ".env 또는 Container App secret(runyourai-key)을 확인하세요."
        )
    kwargs: dict = {
        "api_key": RUNYOURAI_API_KEY,
        "base_url": RUNYOURAI_BASE_URL,
        "model": model or RUNYOURAI_MODEL,
        "temperature": temperature,
    }
    if max_tokens is not None:
        kwargs["max_tokens"] = max_tokens
    return ChatOpenAI(**kwargs)
