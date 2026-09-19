from __future__ import annotations

import csv
import hashlib
import io
import logging
import re
from dataclasses import dataclass, field
from typing import Any

import discord

log = logging.getLogger("hrcc.csv")

EMAIL_RE = re.compile(r"^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$")

CANVA_HEADERS = ["Full Name", "Email Address", "College Name", "Event Name", "Event Date", "Rank", "Score"]

_NAME_ALIASES = {"name", "full name", "full_name", "student name", "candidate name", "participant name", "username"}
_EMAIL_ALIASES = {"email", "email address", "email_address", "mail", "e-mail"}
_SCORE_ALIASES = {"score", "total score", "marks", "points", "total_score", "final score"}
_RANK_ALIASES = {"rank", "position", "#", "standing", "final rank"}


def _find_column(headers: list[str], aliases: set[str]) -> str | None:
    lowered = {h.strip().lower(): h for h in headers}
    for alias in aliases:
        if alias in lowered:
            return lowered[alias]
    return None


@dataclass
class ContestResult:
    total_rows: int = 0
    active_participants: int = 0
    inactive_count: int = 0
    reward_tier: str = ""
    merch_eligible: bool = False
    winners: list[dict[str, Any]] = field(default_factory=list)
    canva_csv: str = ""
    csv_sha256: str = ""
    warnings: list[str] = field(default_factory=list)
    event_name: str = ""
    college_name: str = ""


def _try_parse_xlsx(raw_bytes: bytes) -> str | None:
    try:
        import openpyxl
        wb = openpyxl.load_workbook(io.BytesIO(raw_bytes), read_only=True, data_only=True)
        ws = wb.active
        if ws is None:
            return None
        buf = io.StringIO()
        writer = csv.writer(buf)
        for row in ws.iter_rows(values_only=True):
            writer.writerow([str(c) if c is not None else "" for c in row])
        wb.close()
        return buf.getvalue()
    except Exception:
        return None


def parse_contest_csv(
    raw_bytes: bytes,
    *,
    event_name: str = "Campus Event",
    event_date: str = "",
    college_name: str = "",
    filename: str = "",
) -> ContestResult:
    result = ContestResult(event_name=event_name, college_name=college_name)

    text: str | None = None

    is_xlsx = filename.lower().endswith(".xlsx") or raw_bytes[:4] == b"PK\x03\x04"

    if is_xlsx:
        text = _try_parse_xlsx(raw_bytes)
        if text is None:
            result.warnings.append("Could not parse .xlsx file. Please export as CSV.")
            return result
    else:
        try:
            text = raw_bytes.decode("utf-8-sig")
        except UnicodeDecodeError:
            text = raw_bytes.decode("latin-1")

    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        result.warnings.append("CSV has no headers or is empty.")
        return result

    headers = list(reader.fieldnames)
    name_col = _find_column(headers, _NAME_ALIASES)
    email_col = _find_column(headers, _EMAIL_ALIASES)
    score_col = _find_column(headers, _SCORE_ALIASES)
    rank_col = _find_column(headers, _RANK_ALIASES)

    if not name_col:
        result.warnings.append("Could not find a 'Name' column. Looked for: " + ", ".join(sorted(_NAME_ALIASES)))
        return result

    rows: list[dict[str, Any]] = []
    for row in reader:
        result.total_rows += 1
        name = (row.get(name_col) or "").strip()
        if not name:
            continue

        email = (row.get(email_col) or "").strip() if email_col else ""
        score_raw = (row.get(score_col) or "0").strip() if score_col else "0"
        rank_raw = (row.get(rank_col) or "0").strip() if rank_col else "0"

        try:
            score = float(score_raw)
        except ValueError:
            score = 0.0

        try:
            rank = int(rank_raw)
        except ValueError:
            rank = 0

        if email and not EMAIL_RE.match(email):
            result.warnings.append(f"Invalid email for '{name}': {email}")

        is_active = score > 0
        rows.append({
            "name": name,
            "email": email,
            "score": score,
            "rank": rank,
            "active": is_active,
        })

    active_rows = [r for r in rows if r["active"]]
    inactive_rows = [r for r in rows if not r["active"]]

    result.active_participants = len(active_rows)
    result.inactive_count = len(inactive_rows)

    if result.active_participants >= 300:
        result.reward_tier = "Tier 300+"
        result.merch_eligible = True
    else:
        result.reward_tier = "Standard (< 300)"
        result.merch_eligible = False

    active_sorted = sorted(active_rows, key=lambda r: (-r["score"], r["rank"] if r["rank"] else 9999))
    for i, r in enumerate(active_sorted, start=1):
        if r["rank"] == 0:
            r["rank"] = i

    result.winners = active_sorted[:10]

    canva_buf = io.StringIO()
    writer = csv.writer(canva_buf)
    writer.writerow(CANVA_HEADERS)
    for i, r in enumerate(active_sorted, start=1):
        writer.writerow([
            r["name"],
            r["email"],
            college_name,
            event_name,
            event_date,
            i,
            int(r["score"]) if r["score"] == int(r["score"]) else r["score"],
        ])
    result.canva_csv = canva_buf.getvalue()
    result.csv_sha256 = hashlib.sha256(result.canva_csv.encode()).hexdigest()

    if inactive_rows:
        result.warnings.append(
            f"{len(inactive_rows)} participant(s) had score=0 and were excluded from certificates."
        )

    return result


def build_summary_embed(result: ContestResult) -> discord.Embed:
    color = discord.Color.green() if result.merch_eligible else discord.Color.blue()
    embed = discord.Embed(
        title=f"Contest Validation — {result.event_name}",
        color=color,
    )
    embed.add_field(
        name="Participants",
        value=(
            f"**Total Rows:** {result.total_rows}\n"
            f"**Active (score > 0):** {result.active_participants}\n"
            f"**Inactive (score = 0):** {result.inactive_count}"
        ),
        inline=True,
    )
    embed.add_field(
        name="Reward Tier",
        value=(
            f"**{result.reward_tier}**\n"
            f"Merchandise: {'Yes' if result.merch_eligible else 'No'}"
        ),
        inline=True,
    )

    if result.winners:
        top = "\n".join(
            f"`#{w['rank']}` **{w['name']}** — {int(w['score'])} pts"
            for w in result.winners[:5]
        )
        embed.add_field(name="Top Winners", value=top, inline=False)

    if result.warnings:
        embed.add_field(
            name="Warnings",
            value="\n".join(f"- {w}" for w in result.warnings[:5]),
            inline=False,
        )

    embed.set_footer(text=f"Canva CSV SHA256: {result.csv_sha256[:16]}...")
    return embed


def build_canva_file(result: ContestResult) -> discord.File:
    buf = io.BytesIO(result.canva_csv.encode("utf-8"))
    return discord.File(buf, filename="canva_bulk_certificates.csv")


def build_event_report(
    result: ContestResult, ambassador_name: str = "", include_emails: bool = False,
) -> str:
    lines = [
        "**Post-Event Report — Ready to send to Program Manager**",
        "",
        f"**Event Name:** {result.event_name}",
        f"**Ambassador:** {ambassador_name}" if ambassador_name else "",
        f"**College:** {result.college_name}" if result.college_name else "",
        f"**Platform:** HRW / HRC",
        f"**Total Submissions:** {result.total_rows}",
        f"**Active Participants (score > 0):** {result.active_participants}",
        f"**Completion Rate:** {round(result.active_participants / max(result.total_rows, 1) * 100)}%",
        f"**Reward Tier:** {result.reward_tier}",
        f"**Merchandise Eligible:** {'Yes' if result.merch_eligible else 'No'}",
        "",
    ]

    if result.winners:
        lines.append("**Verified Winners:**")
        for i, w in enumerate(result.winners[:5], start=1):
            if include_emails and w.get("email"):
                lines.append(f"{i}. **{w['name']}** — {int(w['score'])} pts | Email: {w['email']}")
            else:
                lines.append(f"{i}. **{w['name']}** — {int(w['score'])} pts")
        lines.append("")

    lines.extend([
        "**Certificates:** Issued via Canva Bulk Create (CSV attached)",
        f"**CSV SHA256:** `{result.csv_sha256[:16]}...`",
        "",
        "---",
        "*Copy the above and DM to the Program Manager for reward activation.*",
    ])
    return "\n".join(line for line in lines if line is not None)
