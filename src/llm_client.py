from __future__ import annotations

import logging
from typing import Any

import httpx
from langchain_core.language_models import BaseChatModel
from langchain_openai import ChatOpenAI

from src.config import settings

log = logging.getLogger("hrcc.llm")


class LLMFailoverError(RuntimeError):
    """Raised when both the primary vLLM engine and the NIM fallback fail."""


def _is_engine_failure(exc: Exception) -> bool:
    """True for transport-level or API failures that justify failover."""
    if isinstance(exc, (httpx.ConnectError, httpx.TimeoutException)):
        return True
    # LangChain wraps OpenAI errors; treat any non-programming error as an
    # engine failure so the fallback gets a chance.
    return not isinstance(exc, (TypeError, AttributeError, KeyError, ValueError))


class ResilientChatModel:
    """Drop-in wrapper around ``ChatOpenAI`` with automatic vLLM → NVIDIA NIM failover.

    Exposes the same surface the codebase relies on (``ainvoke``, ``invoke``,
    ``bind_tools``, ``bind``). On primary-engine transport/API errors — after
    LangChain's own retries are exhausted — the identical request is routed to
    the configured NVIDIA NIM endpoint.
    """

    def __init__(self, primary: BaseChatModel, fallback: BaseChatModel | None) -> None:
        self._primary = primary
        self._fallback = fallback

    # ── Invocation ────────────────────────────────────────────────────────

    async def ainvoke(self, input: Any, config: Any = None, **kwargs: Any) -> Any:
        try:
            return await self._primary.ainvoke(input, config=config, **kwargs)
        except Exception as exc:
            if self._fallback is None or not _is_engine_failure(exc):
                raise
            log.warning(
                "[LLM FAILOVER] Primary vLLM failed. Routing request to NVIDIA NIM fallback... (%s: %s)",
                type(exc).__name__,
                str(exc)[:200],
            )
            try:
                return await self._fallback.ainvoke(input, config=config, **kwargs)
            except Exception as fb_exc:
                log.error(
                    "[LLM FAILOVER] NVIDIA NIM fallback also failed (%s: %s)",
                    type(fb_exc).__name__,
                    str(fb_exc)[:200],
                )
                raise LLMFailoverError(
                    f"Both inference engines failed. Primary: {exc!r}; Fallback: {fb_exc!r}"
                ) from fb_exc

    def invoke(self, input: Any, config: Any = None, **kwargs: Any) -> Any:
        try:
            return self._primary.invoke(input, config=config, **kwargs)
        except Exception as exc:
            if self._fallback is None or not _is_engine_failure(exc):
                raise
            log.warning(
                "[LLM FAILOVER] Primary vLLM failed. Routing request to NVIDIA NIM fallback... (%s: %s)",
                type(exc).__name__,
                str(exc)[:200],
            )
            try:
                return self._fallback.invoke(input, config=config, **kwargs)
            except Exception as fb_exc:
                log.error(
                    "[LLM FAILOVER] NVIDIA NIM fallback also failed (%s: %s)",
                    type(fb_exc).__name__,
                    str(fb_exc)[:200],
                )
                raise LLMFailoverError(
                    f"Both inference engines failed. Primary: {exc!r}; Fallback: {fb_exc!r}"
                ) from fb_exc

    # ── Binding (tool-use and generic) ────────────────────────────────────

    def bind_tools(self, tools: Any, **kwargs: Any) -> ResilientChatModel:
        bound_primary = self._primary.bind_tools(tools, **kwargs)
        bound_fallback = self._fallback.bind_tools(tools, **kwargs) if self._fallback else None
        return ResilientChatModel(bound_primary, bound_fallback)

    def bind(self, **kwargs: Any) -> ResilientChatModel:
        bound_primary = self._primary.bind(**kwargs)
        bound_fallback = self._fallback.bind(**kwargs) if self._fallback else None
        return ResilientChatModel(bound_primary, bound_fallback)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"ResilientChatModel(primary={self._primary!r}, fallback={self._fallback!r})"


# ── Engine factories ──────────────────────────────────────────────────────

_llm: ResilientChatModel | None = None
_classifier_llm: ResilientChatModel | None = None


def _build_nim_client(temperature: float, max_tokens: int) -> ChatOpenAI | None:
    """Build the NVIDIA NIM fallback client, or ``None`` when fallback is disabled."""
    if not settings.enable_nim_fallback or not settings.nim_base_url:
        return None
    return ChatOpenAI(
        model=settings.nim_model,
        openai_api_key=settings.nim_api_key or "EMPTY",
        openai_api_base=settings.nim_base_url,
        temperature=temperature,
        max_tokens=max_tokens,
        max_retries=settings.vllm_max_retries,
        request_timeout=settings.nim_timeout,
    )


def get_llm() -> ResilientChatModel:
    """Primary LLM for knowledge-grounded response generation (temperature=0.1).

    Returns a resilient proxy: vLLM first, automatic NVIDIA NIM failover.
    """
    global _llm
    if _llm is None:
        primary = ChatOpenAI(
            model=settings.vllm_model,
            openai_api_key=settings.vllm_api_key,
            openai_api_base=settings.vllm_base_url,
            temperature=settings.model_temperature,
            max_tokens=settings.model_max_tokens,
            max_retries=settings.vllm_max_retries,
            request_timeout=settings.vllm_timeout,
        )
        _llm = ResilientChatModel(primary, _build_nim_client(settings.model_temperature, settings.model_max_tokens))
    return _llm


def get_classifier_llm() -> ResilientChatModel:
    """Deterministic classifier LLM (temperature=0.0) for intent routing.

    Returns a resilient proxy: vLLM first, automatic NVIDIA NIM failover.
    """
    global _classifier_llm
    if _classifier_llm is None:
        primary = ChatOpenAI(
            model=settings.vllm_model,
            openai_api_key=settings.vllm_api_key,
            openai_api_base=settings.vllm_base_url,
            temperature=0.0,
            max_tokens=50,
            max_retries=settings.vllm_max_retries,
            request_timeout=settings.vllm_timeout,
        )
        _classifier_llm = ResilientChatModel(primary, _build_nim_client(0.0, 50))
    return _classifier_llm
