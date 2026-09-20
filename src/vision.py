from __future__ import annotations

import base64
import logging
from typing import Any

import httpx

from src.config import settings
from src.prompts.template_manager import get_template_manager
from src.rubrics import scrub_secrets

log = logging.getLogger("hrcc.vision")

SUPPORTED_IMAGE_TYPES = (".png", ".jpg", ".jpeg", ".gif", ".webp")


def is_image_attachment(filename: str) -> bool:
    return filename.lower().endswith(SUPPORTED_IMAGE_TYPES)


# ── Endpoint chain ────────────────────────────────────────────────────────


def _vision_endpoints() -> list[dict[str, Any]]:
    """Ordered list of vision endpoints to try: dedicated → NIM → Ollama → vLLM."""
    endpoints: list[dict[str, Any]] = []

    # 1. Dedicated vision endpoint (vLLM multimodal or any OpenAI-compatible server)
    if settings.vision_base_url:
        endpoints.append({
            "base_url": settings.vision_base_url,
            "model": settings.vision_model or "llava",
            "api_key": settings.vllm_api_key,
            "label": "dedicated-vision",
        })

    # 2. NVIDIA NIM vision (e.g. meta/llama-3.2-11b-vision-instruct)
    if settings.enable_nim_fallback:
        nim_base = settings.nim_vision_base_url or settings.nim_base_url
        if nim_base:
            endpoints.append({
                "base_url": nim_base,
                "model": settings.nim_vision_model,
                "api_key": settings.nim_api_key,
                "label": "nvidia-nim-vision",
            })

    # 3. Ollama multimodal fallback (OpenAI-compatible /v1 API)
    if settings.ollama_base_url:
        endpoints.append({
            "base_url": settings.ollama_base_url,
            "model": settings.ollama_vision_model,
            "api_key": "",
            "label": "ollama-vision",
        })

    # 4. Plain vLLM as a last resort (may or may not support images)
    if settings.vllm_base_url and not endpoints:
        endpoints.append({
            "base_url": settings.vllm_base_url,
            "model": settings.vllm_model,
            "api_key": settings.vllm_api_key,
            "label": "vllm",
        })

    return endpoints


# ── Deterministic triage classification ───────────────────────────────────

_P0_CHAKRA_BANNER = (
    "\n\n> 🚨 **P0 SECURITY TRIGGER — CHAKRA TAB DETECTED**\n"
    "> The **Chakra** tab is STRICTLY INTERNAL to HackerRank enterprise staff. "
    "> The ambassador must **NEVER access, click, or interact** with it. "
    "> Instruct them to close the tab immediately and use mock-interview vouchers "
    "> requested via Sanskruti (Program Manager) instead."
)

_404_BANNER = (
    "\n\n> ⚠️ **HRW TEST 404 / INACTIVE CONTEST**\n"
    "> The assessment link is not resolving or the contest has ended. Verify the "
    "> contest window on HRW, confirm the correct link was shared, and if the "
    "> contest genuinely lapsed, escalate to **Sreesanth (Technical Lead)**."
)

_PROCTORING_BANNER = (
    "\n\n> ⚠️ **CANDIDATE DISQUALIFIED / PROCTORING VIOLATION**\n"
    "> A proctoring or eligibility violation is visible. Capture the incident "
    "> details, note the candidate's email, and route to **Sreesanth (Technical Lead)** "
    "for review before any re-test is offered."
)


def _classify_triage(analysis: str) -> str:
    """Append deterministic severity banners based on detected signals."""
    text = analysis.lower()

    if "chakra" in text:
        return analysis + _P0_CHAKRA_BANNER
    if "404" in text or "inactive" in text or "not found" in text or "no longer active" in text:
        return analysis + _404_BANNER
    if "disqualif" in text or "proctor" in text or "violation" in text:
        return analysis + _PROCTORING_BANNER

    return analysis


# ── Analysis ──────────────────────────────────────────────────────────────


async def _query_endpoint(endpoint: dict[str, Any], payload: dict[str, Any]) -> str:
    headers: dict[str, str] = {}
    if endpoint["api_key"] and endpoint["api_key"] != "EMPTY":
        headers["Authorization"] = f"Bearer {endpoint['api_key']}"

    async with httpx.AsyncClient(timeout=httpx.Timeout(45.0, connect=10.0)) as client:
        resp = await client.post(
            f"{endpoint['base_url'].rstrip('/')}/chat/completions",
            json=payload,
            headers=headers,
        )
        resp.raise_for_status()
        data = resp.json()
        return data["choices"][0]["message"]["content"].strip()


async def analyze_screenshot(image_bytes: bytes, filename: str = "image.png") -> str:
    """Analyze an ambassador's screenshot via the first working vision endpoint.

    Routes through NVIDIA NIM Vision or Ollama multimodal fallback when the
    primary endpoint is unavailable, then applies deterministic triage
    classification (HRW 404 / proctoring violations / Chakra P0 trigger).
    """
    endpoints = _vision_endpoints()
    if not endpoints:
        return "Vision analysis is not configured. Please contact the Technical Lead."

    b64_image = base64.b64encode(image_bytes).decode("utf-8")

    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else "png"
    mime_map = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg", "gif": "image/gif", "webp": "image/webp"}
    mime_type = mime_map.get(ext, "image/png")

    system_prompt = get_template_manager().render_template("vision_analyzer")

    payload: dict[str, Any] = {
        "messages": [
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "Analyze this screenshot from a HackerRank Campus Crew ambassador and provide diagnostic guidance."},
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:{mime_type};base64,{b64_image}"},
                    },
                ],
            },
        ],
        "max_tokens": 1000,
        "temperature": 0.1,
    }

    last_error: Exception | None = None
    for endpoint in endpoints:
        payload["model"] = endpoint["model"]
        try:
            content = await _query_endpoint(endpoint, payload)
            if endpoint is not endpoints[0]:
                log.info("[VISION FAILOVER] Succeeded via %s (%s)", endpoint["label"], endpoint["model"])
            return scrub_secrets(_classify_triage(content))
        except httpx.HTTPStatusError as exc:
            last_error = exc
            if exc.response.status_code == 400:
                log.warning(
                    "[VISION FAILOVER] %s (%s) does not support image inputs (400), trying next endpoint",
                    endpoint["label"],
                    endpoint["model"],
                )
            else:
                log.warning(
                    "[VISION FAILOVER] %s (%s) returned HTTP %s, trying next endpoint",
                    endpoint["label"],
                    endpoint["model"],
                    exc.response.status_code,
                )
        except Exception as exc:
            last_error = exc
            log.warning(
                "[VISION FAILOVER] %s (%s) unreachable (%s: %s), trying next endpoint",
                endpoint["label"],
                endpoint["model"],
                type(exc).__name__,
                str(exc)[:120],
            )

    log.error("All vision endpoints failed. Last error: %r", last_error)
    return (
        "Could not analyze the screenshot — all inference endpoints are currently unavailable. "
        "Please describe the error you're seeing in text, or contact the Technical Lead."
    )
