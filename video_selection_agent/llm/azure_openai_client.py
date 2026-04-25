"""Azure OpenAI (GPT-4.1-mini) 래퍼.

환경변수:
  - AZURE_OPENAI_ENDPOINT
  - AZURE_OPENAI_API_KEY
  - AZURE_OPENAI_DEPLOYMENT     (기본: gpt-4.1-mini)
  - AZURE_OPENAI_API_VERSION    (기본: 2025-01-01-preview)

`response_format={"type":"json_schema", "json_schema": {...}}`로 구조화 출력 강제.
"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)


class LLMError(RuntimeError):
    """LLM 호출 실패 (네트워크/인증/파싱). 호출부에서 graceful degradation."""


@dataclass
class AzureOpenAIConfig:
    endpoint: str
    api_key: str
    deployment: str
    api_version: str

    @classmethod
    def from_env(cls) -> "AzureOpenAIConfig":
        return cls(
            endpoint=os.getenv("AZURE_OPENAI_ENDPOINT", ""),
            api_key=os.getenv("AZURE_OPENAI_API_KEY", ""),
            deployment=os.getenv("AZURE_OPENAI_DEPLOYMENT", "gpt-4.1-mini"),
            api_version=os.getenv("AZURE_OPENAI_API_VERSION", "2025-01-01-preview"),
        )

    def is_configured(self) -> bool:
        return bool(self.endpoint and self.api_key)


class AzureOpenAIClient:
    """GPT-4.1-mini 구조화 출력 호출 래퍼."""

    def __init__(self, config: AzureOpenAIConfig | None = None):
        self.config = config or AzureOpenAIConfig.from_env()
        self._client: Any = None

    def _get_client(self) -> Any:
        if self._client is not None:
            return self._client
        if not self.config.is_configured():
            raise LLMError("Azure OpenAI not configured (endpoint/api_key missing)")
        try:
            from openai import AzureOpenAI
        except ImportError as e:
            raise LLMError(f"openai SDK not installed: {e}") from e
        self._client = AzureOpenAI(
            azure_endpoint=self.config.endpoint,
            api_key=self.config.api_key,
            api_version=self.config.api_version,
        )
        return self._client

    def chat_structured(
        self,
        system: str,
        user: str,
        json_schema: dict[str, Any],
        max_tokens: int = 2000,
        temperature: float = 0.2,
    ) -> dict[str, Any]:
        """JSON schema 강제 응답. 실패 시 LLMError 발생."""
        client = self._get_client()
        try:
            response = client.chat.completions.create(
                model=self.config.deployment,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                response_format={"type": "json_schema", "json_schema": json_schema},
                max_tokens=max_tokens,
                temperature=temperature,
            )
        except Exception as e:
            raise LLMError(f"Azure chat completion failed: {e}") from e

        choice = response.choices[0] if response.choices else None
        if choice is None:
            raise LLMError("Azure response has no choices")
        if choice.finish_reason == "length":
            raise LLMError("Azure response truncated (max_tokens)")
        content = choice.message.content or ""
        try:
            return json.loads(content)
        except json.JSONDecodeError as e:
            raise LLMError(f"Azure response not valid JSON: {e}; content={content[:200]}") from e
