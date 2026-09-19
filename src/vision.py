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


async def analyze_screenshot(image_bytes: bytes, filename: str = "image.png") -> str:
    vision_model = settings.vision_model or settings.vllm_model
    base_url = settings.vision_base_url or settings.vllm_base_url

    if not base_url:
        return "Vision analysis is not configured. Please contact the Technical Lead."

    b64_image = base64.b64encode(image_bytes).decode("utf-8")

    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else "png"
    mime_map = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg", "gif": "image/gif", "webp": "image/webp"}
    mime_type = mime_map.get(ext, "image/png")

    system_prompt = get_template_manager().render_template("vision_analyzer")

    payload: dict[str, Any] = {
        "model": vision_model,
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

    headers: dict[str, str] = {}
    if settings.vllm_api_key and settings.vllm_api_key != "EMPTY":
        headers["Authorization"] = f"Bearer {settings.vllm_api_key}"

    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(45.0, connect=10.0)) as client:
            resp = await client.post(
                f"{base_url}/chat/completions",
                json=payload,
                headers=headers,
            )
            resp.raise_for_status()
            data = resp.json()
            content: str = data["choices"][0]["message"]["content"]
            return scrub_secrets(content.strip())
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 400:
            log.warning("Vision model does not support image inputs (400). Model: %s", vision_model)
            return (
                "The current inference model does not support image analysis. "
                "Please describe the error you're seeing in text, or contact the Technical Lead."
            )
        log.exception("Vision API HTTP error")
        return "Could not analyze the screenshot due to a service error. Please try again or describe the issue in text."
    except Exception:
        log.exception("Vision analysis failed")
        return "Could not analyze the screenshot. Please describe the error you're seeing in text."
