"""
감정 및 항목(Aspect) 분석 — RunYourAI 통합 (기본 openai/gpt-4.1)

원래 Groq Llama → Azure OpenAI → RunYourAI 순으로 이관.
클래스명(GroqAspectSentimentAnalyzer) 은 호출부 호환을 위해 그대로 유지.
"""
import os
from typing import Optional
from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage

from .base_analyzer import BaseAspectSentimentAnalyzer
from .models import AnalyzerConfig


_RUNYOURAI_API_KEY = os.getenv("RUNYOURAI_API_KEY", "")
_RUNYOURAI_BASE_URL = os.getenv("RUNYOURAI_BASE_URL", "https://api.runyour.ai/v1")
_RUNYOURAI_MODEL = os.getenv("RUNYOURAI_MODEL", "openai/gpt-4.1")


class GroqAspectSentimentAnalyzer(BaseAspectSentimentAnalyzer):
    """RunYourAI 를 사용한 감정 및 항목 분석기 (이름은 하위호환성 유지)."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        config: Optional[AnalyzerConfig] = None
    ):
        """
        Args:
            api_key: 호환을 위해 받지만 사용하지 않음 (RunYourAI 는 환경변수로 인증)
            config: 분석기 설정 — model_name 은 무시되고 RUNYOURAI_MODEL 환경변수가 우선
        """
        super().__init__(config)

        if not _RUNYOURAI_API_KEY:
            raise ValueError(
                "RUNYOURAI_API_KEY 환경변수가 설정되지 않았습니다. "
                ".env 또는 Container App secret(runyourai-key)을 확인하세요."
            )
        self.api_key = _RUNYOURAI_API_KEY

        self.llm = ChatOpenAI(
            api_key=_RUNYOURAI_API_KEY,
            base_url=_RUNYOURAI_BASE_URL,
            model=_RUNYOURAI_MODEL,
            temperature=self.config.temperature,
            max_tokens=self.config.max_tokens,
            model_kwargs={"response_format": {"type": "json_object"}},
        )

    def _call_llm(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.1,
        max_tokens: int = 1000
    ) -> str:
        """LangChain ChatOpenAI 호출 (temperature / max_tokens 은 __init__ 시 적용됨)."""
        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_prompt),
        ]
        response = self.llm.invoke(messages)
        return response.content


def create_analyzer(
    api_key: Optional[str] = None,
    model_name: str = "gpt-4.1-mini",
    temperature: float = 0.1,
    max_tokens: int = 1000
) -> GroqAspectSentimentAnalyzer:
    """분석기 생성 편의 함수 (Azure 사용)."""
    config = AnalyzerConfig(
        model_name=model_name,
        temperature=temperature,
        max_tokens=max_tokens
    )
    return GroqAspectSentimentAnalyzer(api_key=api_key, config=config)
