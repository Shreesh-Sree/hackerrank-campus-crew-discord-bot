from __future__ import annotations

import logging

from langchain_openai import ChatOpenAI

from src.config import settings

log = logging.getLogger("hrcc.llm")

_llm: ChatOpenAI | None = None
_classifier_llm: ChatOpenAI | None = None


def get_llm() -> ChatOpenAI:
    """Primary LLM for knowledge-grounded response generation (temperature=0.1)."""
    global _llm
    if _llm is None:
        _llm = ChatOpenAI(
            model=settings.vllm_model,
            openai_api_key=settings.vllm_api_key,
            openai_api_base=settings.vllm_base_url,
            temperature=settings.model_temperature,
            max_tokens=settings.model_max_tokens,
            max_retries=settings.vllm_max_retries,
            request_timeout=settings.vllm_timeout,
        )
    return _llm


def get_classifier_llm() -> ChatOpenAI:
    """Deterministic classifier LLM (temperature=0.0) for intent routing."""
    global _classifier_llm
    if _classifier_llm is None:
        _classifier_llm = ChatOpenAI(
            model=settings.vllm_model,
            openai_api_key=settings.vllm_api_key,
            openai_api_base=settings.vllm_base_url,
            temperature=0.0,
            max_tokens=50,
            max_retries=settings.vllm_max_retries,
            request_timeout=settings.vllm_timeout,
        )
    return _classifier_llm
