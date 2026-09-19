from __future__ import annotations

import re

NOISE_PATTERN = re.compile(
    r"^(hi|hello|hey|sup|bro|machi|gm|gn|good\s*(morning|night|afternoon|evening)"
    r"|lol|lmao|rofl|cool|nice|ok|okay|k|thanks|ty|thx|np|gg|xd|bruh|yep|yup|nah"
    r"|bye|cya|see\s*ya|later|gtg|ttyl|haha|hehe|hmm|oh|wow|damn|dang|omg|wtf"
    r"|what'?s?\s*up|wassup|howdy|yo)\b[\s!.,?~:;)*<>]*$",
    re.IGNORECASE,
)

CAMPUS_CREW_KEYWORDS = re.compile(
    r"(hackerrank|hrw|hrc|skillup|campus\s*crew|ambassador|contest|hackathon"
    r"|assessment|proctoring|chakra|infinity\s*plan|mock\s*interview"
    r"|participant|certificate|canva|csv|reward|merch|merchandise"
    r"|winner|scoreboard|leaderboard|test\s*link|buffer\s*time"
    r"|sanskruti|sreesanth|nitish|program\s*manager|technical\s*lead|design\s*lead"
    r"|hrcc|campus\s*test|coding\s*event|code\s*submission)",
    re.IGNORECASE,
)

INJECTION_PATTERNS = re.compile(
    r"(ignore\s+(all\s+)?previous\s+instructions"
    r"|you\s+are\s+now\s+DAN"
    r"|system\s*prompt"
    r"|reveal\s+(your|the)\s+(instructions|prompt|system)"
    r"|print\s+(your|the)\s+(prompt|instructions|config)"
    r"|act\s+as\s+(if\s+)?you\s+(have\s+)?no\s+restrictions"
    r"|jailbreak"
    r"|override\s+(your\s+)?(safety\s+|all\s+)?(rules|instructions|guardrails))",
    re.IGNORECASE,
)

SECRET_PATTERNS = re.compile(
    r"(10\.\d{1,3}\.\d{1,3}\.\d{1,3}"
    r"|127\.0\.0\.\d{1,3}"
    r"|/home/[a-zA-Z0-9_\-/]+"
    r"|/data/production/[a-zA-Z0-9_\-/]+"
    r"|DISCORD_BOT_TOKEN\s*=\s*\S+"
    r"|VLLM_API_KEY\s*=\s*\S+"
    r"|Bearer\s+[A-Za-z0-9._\-]+"
    r"|[MN][A-Za-z0-9_\-]{23,}\.[A-Za-z0-9_\-]{6}\.[A-Za-z0-9_\-]{27,})"
)

CHAKRA_PATTERN = re.compile(r"\bchakra\b", re.IGNORECASE)

ESCALATION_KEYWORDS: dict[str, list[str]] = {
    "sanskruti": [
        "reward", "prize", "infinity plan", "merchandise", "merch", "welcome kit",
        "onboarding", "speaker", "judge", "permission letter", "swag",
        "winner spreadsheet", "activation", "mock interview credit",
    ],
    "sreesanth": [
        "bug", "error", "500", "404", "outage", "broken", "not working",
        "hrw access", "account locked", "compiler", "sandbox", "timeout",
        "skillup bug", "platform issue", "login issue", "invitation pending",
    ],
    "nitish": [
        "logo", "brand", "certificate template", "design", "poster",
        "canva template", "visual", "creative", "brand guideline", "asset",
    ],
}


def is_noise(text: str) -> bool:
    return bool(NOISE_PATTERN.match(text.strip()))


def has_campus_crew_intent(text: str) -> bool:
    return bool(CAMPUS_CREW_KEYWORDS.search(text))


def is_injection_attempt(text: str) -> bool:
    return bool(INJECTION_PATTERNS.search(text))


def contains_chakra_reference(text: str) -> bool:
    return bool(CHAKRA_PATTERN.search(text))


def scrub_secrets(text: str) -> str:
    return SECRET_PATTERNS.sub("[REDACTED]", text)


def detect_escalation_target(text: str) -> str | None:
    text_lower = text.lower()
    scores: dict[str, int] = {"sanskruti": 0, "sreesanth": 0, "nitish": 0}
    for lead, keywords in ESCALATION_KEYWORDS.items():
        for kw in keywords:
            if kw in text_lower:
                scores[lead] += 1
    best = max(scores, key=lambda k: scores[k])
    return best if scores[best] > 0 else None


def extract_participant_count(text: str) -> int | None:
    match = re.search(r"(\d{1,6})\s*(?:participants?|attendees?|students?|people|submissions?)", text, re.IGNORECASE)
    if match:
        return int(match.group(1))
    match = re.search(r"(?:had|got|reached|over|around|about|nearly)\s*(\d{1,6})", text, re.IGNORECASE)
    if match:
        return int(match.group(1))
    return None


def chunk_message(text: str, limit: int = 2000) -> list[str]:
    if len(text) <= limit:
        return [text]

    chunks: list[str] = []
    remaining = text

    while remaining:
        if len(remaining) <= limit:
            chunks.append(remaining)
            break

        split_at = remaining.rfind("\n\n", 0, limit)
        if split_at == -1:
            split_at = remaining.rfind("\n", 0, limit)
        if split_at == -1:
            split_at = remaining.rfind(". ", 0, limit)
        if split_at == -1:
            split_at = limit - 1

        chunk = remaining[: split_at + 1].rstrip()
        remaining = remaining[split_at + 1 :].lstrip()

        open_fences = chunk.count("```") % 2
        if open_fences:
            chunk += "\n```"
            remaining = "```\n" + remaining

        chunks.append(chunk)

    return chunks
