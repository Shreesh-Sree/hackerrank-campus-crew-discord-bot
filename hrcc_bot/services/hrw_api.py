from __future__ import annotations

import asyncio
import logging
from typing import Any

import httpx

from hrcc_bot.config import settings

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
    """Verify that an HRW user owns a specific test.

    Returns True if ownership is confirmed, False otherwise (including network errors).
    """
    max_retries = settings.vllm_max_retries
    for attempt in range(max_retries):
        try:
            test = await get_test(test_id)
            return test.get("owner") == hrw_user_id
        except Exception as e:
            if attempt == max_retries - 1:
                log.error("Failed to verify test ownership after %d attempts: %s", max_retries, str(e)[:100])
                return False
            await asyncio.sleep(2 ** attempt)

    return False


async def get_questions_by_test(test_id: str) -> list[dict[str, Any]]:
    """Fetch all questions for a specific HRW test.

    Returns list of question dicts or empty list on failure.
    """
    try:
        test = await get_test(test_id)
        test_id_from_api = test.get("id")
        if not test_id_from_api:
            return []

        all_questions: list[dict[str, Any]] = []
        offset = 0
        while True:
            data = await get_questions(limit=50, offset=offset)
            questions = data.get("data", [])
            if not questions:
                break
            for q in questions:
                # Filter to only questions belonging to this test
                if q.get("test_id") == test_id_from_api:
                    all_questions.append(q)
            total = data.get("total", 0)
            offset += 50
            if offset >= total:
                break

        return all_questions
    except Exception as e:
        log.error("Failed to fetch questions for test %s: %s", test_id, str(e)[:100])
        return []


async def create_test(
    name: str,
    duration_minutes: int,
    difficulty: str = "INTERMEDIATE",
    question_ids: list[str] | None = None,
) -> dict[str, Any]:
    """Create a new HRW test with given questions.

    Returns the created test data or error dict on failure.
    """
    if not settings.hrw_api_key:
        return {"error": "HRW API key not configured"}

    async with httpx.AsyncClient(timeout=httpx.Timeout(30.0)) as client:
        payload = {
            "name": name,
            "duration_minutes": duration_minutes,
            "difficulty": difficulty,
            "public": True,
        }
        if question_ids:
            payload["question_ids"] = question_ids

        resp = await client.post(
            f"{_BASE_URL}/tests",
            headers=_headers(),
            json=payload,
        )
        resp.raise_for_status()
        return resp.json()


async def invite_recruiter(hrw_user_id: str, email: str) -> dict[str, Any]:
    """Invite a recruiter to the HRW platform.

    Returns success dict or error on failure.
    """
    if not settings.hrw_api_key:
        return {"error": "HRW API key not configured"}

    async with httpx.AsyncClient(timeout=httpx.Timeout(30.0)) as client:
        payload = {
            "user_id": hrw_user_id,
            "email": email,
            "role": "recruiter",
        }
        resp = await client.post(
            f"{_BASE_URL}/users/{hrw_user_id}/invitations",
            headers=_headers(),
            json=payload,
        )
        try:
            resp.raise_for_status()
            return resp.json()
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                log.warning("HRW user %s not found for invitation", hrw_user_id)
            return {"error": f"HTTP {e.response.status_code}"}
