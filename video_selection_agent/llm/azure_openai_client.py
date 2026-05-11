"""RunYourAI 통합 LLM 래퍼 (기본 openai/gpt-4.1, OpenAI 호환).

환경변수:
  - RUNYOURAI_API_KEY
  - RUNYOURAI_BASE_URL    (기본: https://api.runyour.ai/v1)
  - RUNYOURAI_MODEL       (기본: openai/gpt-4.1)

`response_format={"type":"json_schema", "json_schema": {...}}`로 구조화 출력 강제.

파일명은 하위호환을 위해 azure_openai_client.py로 유지 — provider_factory.py
등에서 이 이름으로 import하는 곳을 깨지 않기 위함.
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
    """이름은 하위호환을 위해 유지. 내부는 RunYourAI 설정."""

    base_url: str
    api_key: str
    model: str

    @classmethod
    def from_env(cls) -> "AzureOpenAIConfig":
        return cls(
            base_url=os.getenv("RUNYOURAI_BASE_URL", "https://api.runyour.ai/v1"),
            api_key=os.getenv("RUNYOURAI_API_KEY", ""),
            model=os.getenv("RUNYOURAI_MODEL", "openai/gpt-4.1"),
        )

    def is_configured(self) -> bool:
        return bool(self.api_key)


class AzureOpenAIClient:
    """RunYourAI(OpenAI 호환) 구조화 출력 호출 래퍼.

    클래스명은 하위호환 유지. provider_factory.get_default_llm() 결과.
    """

    def __init__(self, config: AzureOpenAIConfig | None = None):
        self.config = config or AzureOpenAIConfig.from_env()
        self._client: Any = None

    def _get_client(self) -> Any:
        if self._client is not None:
            return self._client
        if not self.config.is_configured():
            raise LLMError("RunYourAI not configured (RUNYOURAI_API_KEY missing)")
        try:
            from openai import OpenAI
        except ImportError as e:
            raise LLMError(f"openai SDK not installed: {e}") from e
        self._client = OpenAI(
            api_key=self.config.api_key,
            base_url=self.config.base_url,
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
                model=self.config.model,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                response_format={"type": "json_schema", "json_schema": json_schema},
                max_tokens=max_tokens,
                temperature=temperature,
            )
        except Exception as e:
            raise LLMError(f"RunYourAI chat completion failed: {e}") from e

        choice = response.choices[0] if response.choices else None
        if choice is None:
            raise LLMError("LLM response has no choices")
        if choice.finish_reason == "length":
            raise LLMError("LLM response truncated (max_tokens)")
        content = choice.message.content or ""
        try:
            return json.loads(content)
        except json.JSONDecodeError as e:
            raise LLMError(f"LLM response not valid JSON: {e}; content={content[:200]}") from e
