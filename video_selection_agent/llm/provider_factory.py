"""LLM 공급자 팩토리.

현재는 Azure GPT-4.1-mini만 primary. 추후 Groq/Claude 교체 대비 얇은 추상.
"""
from __future__ import annotations

from video_selection_agent.llm.azure_openai_client import AzureOpenAIClient


def get_default_llm() -> AzureOpenAIClient:
    """기본 LLM 공급자 반환."""
    return AzureOpenAIClient()
