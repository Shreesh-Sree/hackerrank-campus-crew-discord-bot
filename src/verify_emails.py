from __future__ import annotations

import csv
import io
import logging
from dataclasses import dataclass
from typing import Any

from src.hrw_api import find_hrw_user_by_email, verify_test_ownership
from src.rubrics import extract_participant_count

log = logging.getLogger("hrcc.verify_emails")


@dataclass
class EmailVerificationResult:
    """Result of verifying a single email against HRW."""
    name: str
    email: str
    hrw_account_found: bool
    matches_winner_email: bool
    hrw_user_id: str | None = None
    warning: str | None = None


class EmailVerifier:
    """Bulk verifier for contest winner emails against HackerRank accounts."""

    def __init__(self, test_id: str | None = None):
        self.test_id = test_id

    async def verify_single_email(
        self, name: str, email: str
    ) -> EmailVerificationResult:
        """Verify a single email against HRW user database."""
        hrw_user = await find_hrw_user_by_email(email.lower())

        if not hrw_user:
            return EmailVerificationResult(
                name=name,
                email=email,
                hrw_account_found=False,
                matches_winner_email=False,
                warning="Email not found in HackerRank user database",
            )

        hrw_registered_email = hrw_user.get("email", "").lower()
        matches = hrw_registered_email == email.lower()

        return EmailVerificationResult(
            name=name,
            email=email,
            hrw_account_found=True,
            matches_winner_email=matches,
            hrw_user_id=hrw_user.get("user_id"),
            warning=(
                f"HRW account registered with different email: {hrw_registered_email}"
                if not matches
                else None
            ),
        )

    async def verify_batch(
        self, participants: list[dict[str, str]]
    ) -> list[EmailVerificationResult]:
        """Verify a batch of participant emails."""
        import asyncio

        tasks = [
            self.verify_single_email(p["name"], p.get("email", ""))
            for p in participants
        ]
        return await asyncio.gather(*tasks)


def validate_canva_csv_schema(csv_data, event_name: str) -> tuple[bool, list[str]]:
    """Validate Canva bulk CSV schema.

    Expected headers: Name, Email Address, College Name, Event Name, Date, Rank, Score

    Args:
        csv_data: Either bytes or string CSV content
        event_name: Name of the event (for context)

    Returns:
        (is_valid, list_of_warnings)
    """
    required_fields = [
        "Name",
        "Email Address",
        "College Name",
        "Event Name",
        "Date",
        "Rank",
        "Score",
    ]

    try:
        # Handle both bytes and string input
        if isinstance(csv_data, bytes):
            text_content = csv_data.decode("utf-8")
        else:
            text_content = csv_data

        reader = csv.DictReader(io.StringIO(text_content))
    except UnicodeDecodeError:
        return False, ["CSV file is not valid UTF-8 encoding"]

    if reader.fieldnames is None:
        return False, ["Empty CSV file"]

    missing_fields = [f for f in required_fields if f not in reader.fieldnames]
    if missing_fields:
        return False, [f"Missing required columns: {', '.join(missing_fields)}"]

    # Check for at least one data row
    rows = list(reader)
    if len(rows) == 0:
        return False, ["No participant data found"]

    # Validate each row
    warnings: list[str] = []
    for idx, row in enumerate(rows, start=2):  # Start at 2 (header is row 1)
        if not row.get("Name", "").strip():
            warnings.append(f"Row {idx}: Missing name")
        if not row.get("Email Address", "").strip():
            warnings.append(f"Row {idx}: Missing email address")
        if not row.get("College Name", "").strip():
            warnings.append(f"Row {idx}: Missing college name")
        if not row.get("Event Name", "").strip():
            warnings.append(f"Row {idx}: Missing event name")
        if not row.get("Date", "").strip():
            warnings.append(f"Row {idx}: Missing date")
        try:
            rank = int(row.get("Rank", 0))
            if rank < 1:
                warnings.append(f"Row {idx}: Invalid rank (must be >= 1)")
        except ValueError:
            warnings.append(f"Row {idx}: Invalid rank format")
        try:
            score = int(row.get("Score", 0))
            if score < 0:
                warnings.append(f"Row {idx}: Negative score")
        except ValueError:
            warnings.append(f"Row {idx}: Invalid score format")

    return len(warnings) == 0, warnings


async def verify_winner_emails(
    csv_bytes: bytes, event_name: str, participants: list[dict[str, str]] | None = None
) -> tuple[int, int, list[str]]:
    """Main verification workflow.

    Args:
        csv_bytes: Raw CSV content from contest results
        event_name: Name of the event for context
        participants: Optional pre-extracted participant list (from validate_contest_csv)

    Returns:
        (total_count, valid_count, warnings)
    """
    # Validate schema first
    is_valid, schema_warnings = validate_canva_csv_schema(csv_bytes, event_name)

    all_warnings = list(schema_warnings)

    if not is_valid:
        return 0, 0, all_warnings

    # Extract participants from CSV if not provided
    if participants is None:
        text_content = csv_bytes.decode("utf-8") if isinstance(csv_bytes, bytes) else csv_bytes
        reader = csv.DictReader(io.StringIO(text_content))
        participants = [
            {"name": row.get("Name", ""), "email": row.get("Email Address", "")}
            for row in reader
            if row.get("Name")
        ]

    total_count = len(participants)

    # Verify each email
    verifier = EmailVerifier()
    results = await verifier.verify_batch(participants)

    valid_count = sum(1 for r in results if r.matches_winner_email and r.hrw_account_found)
    mismatched = [r for r in results if not r.matches_winner_email]

    email_warnings = []
    for r in mismatched:
        email_warnings.append(
            f"{r.name}: Submitted {r.email} but HRW account uses {r.warning}"
        )

    all_warnings.extend(email_warnings)

    return total_count, valid_count, all_warnings


def generate_verification_report(
    results: list[EmailVerificationResult], include_details: bool = False
) -> str:
    """Generate a text report of email verification results."""
    lines = [
        "=" * 60,
        "EMAIL VERIFICATION REPORT",
        "=" * 60,
        f"Total checked: {len(results)}",
        f"Valid (matches HRW account): {sum(1 for r in results if r.matches_winner_email and r.hrw_account_found)}",
        f"Invalid/Mismatched: {sum(1 for r in results if not r.matches_winner_email)}",
        "",
    ]

    if include_details:
        lines.append("DETAILED RESULTS:")
        lines.append("-" * 60)
        for r in results:
            status = "VALID" if r.matches_winner_email else "INVALID"
            warning = f" — {r.warning}" if r.warning else ""
            lines.append(
                f"{status} | {r.name} | Submitted: {r.email}{warning}"
            )

        lines.append("")
        lines.append("=" * 60)
        lines.append("CRITICAL: Do NOT submit mismatched emails to Sanskruti!")
        lines.append("These will cause reward activation failures.")
        lines.append("=" * 60)

    return "\n".join(lines)


async def run_full_verification(
    csv_bytes: bytes, event_name: str
) -> dict[str, Any]:
    """Run complete verification pipeline.

    Returns dict with summary and detailed results.
    """
    total_count, valid_count, warnings = await verify_winner_emails(csv_bytes, event_name)

    # Also validate Canva schema
    is_valid_schema, schema_warnings = validate_canva_csv_schema(
        csv_bytes, event_name
    )

    return {
        "event_name": event_name,
        "total_participants": total_count,
        "valid_emails": valid_count,
        "invalid_emails": total_count - valid_count,
        "schema_valid": is_valid_schema,
        "warnings": warnings,
        "can_submit_to_sanskruti": (
            valid_count == total_count and is_valid_schema
        ),
    }
