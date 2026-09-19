from __future__ import annotations

import logging
from typing import Any

import httpx

from src.config import settings

log = logging.getLogger("hrcc.hrw_api")

_BASE_URL = "https://www.hackerrank.com/x/api/v3"


def _headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {settings.hrw_api_key}"}


async def _get(path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    if not settings.hrw_api_key:
        return {"error": "HRW API key not configured"}

    async with httpx.AsyncClient(timeout=httpx.Timeout(15.0)) as client:
        resp = await client.get(f"{_BASE_URL}{path}", headers=_headers(), params=params)
        resp.raise_for_status()
        return resp.json()


async def get_hrw_users(limit: int = 100, offset: int = 0) -> dict[str, Any]:
    return await _get("/users", {"limit": limit, "offset": offset})


async def find_hrw_user_by_email(email: str) -> dict[str, Any] | None:
    offset = 0
    while True:
        data = await get_hrw_users(limit=100, offset=offset)
        users = data.get("data", [])
        if not users:
            break
        for u in users:
            if u.get("email", "").lower() == email.lower():
                return u
        total = data.get("total", 0)
        offset += 100
        if offset >= total:
            break
    return None


async def get_tests(limit: int = 50, offset: int = 0) -> dict[str, Any]:
    return await _get("/tests", {"limit": limit, "offset": offset})


async def get_test(test_id: str) -> dict[str, Any]:
    return await _get(f"/tests/{test_id}")


async def get_test_candidates(test_id: str, limit: int = 50, offset: int = 0) -> dict[str, Any]:
    return await _get(f"/tests/{test_id}/candidates", {"limit": limit, "offset": offset})


async def get_tests_for_owner(hrw_user_id: str) -> list[dict[str, Any]]:
    all_tests: list[dict[str, Any]] = []
    offset = 0
    while True:
        data = await get_tests(limit=50, offset=offset)
        tests = data.get("data", [])
        if not tests:
            break
        for t in tests:
            if t.get("owner") == hrw_user_id:
                all_tests.append(t)
        total = data.get("total", 0)
        offset += 50
        if offset >= total:
            break
    return all_tests


async def get_questions(limit: int = 20, offset: int = 0, q_type: str = "") -> dict[str, Any]:
    params: dict[str, Any] = {"limit": limit, "offset": offset}
    if q_type:
        params["type"] = q_type
    return await _get("/questions", params)


async def verify_test_ownership(test_id: str, hrw_user_id: str) -> bool:
    try:
        test = await get_test(test_id)
        return test.get("owner") == hrw_user_id
    except Exception:
        return False
