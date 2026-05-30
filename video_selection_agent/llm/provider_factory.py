"""LLM 공급자 팩토리.

현재는 RunYourAI(OpenAI 호환) 통합 게이트웨이만 primary
— default 모델은 `RUNYOURAI_MODEL` 환경변수가 결정한다(미설정 시 `openai/gpt-4.1`).
추후 Groq/Claude 교체 대비 얇은 추상.
"""
from __future__ import annotations

from video_selection_agent.llm.azure_openai_client import AzureOpenAIClient


def get_default_llm() -> AzureOpenAIClient:
    """기본 LLM 공급자 반환."""
    return AzureOpenAIClient()
