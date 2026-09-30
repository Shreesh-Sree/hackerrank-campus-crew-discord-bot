from __future__ import annotations

from langchain_core.tools import tool

from hrcc_bot.core.db import (
    get_ambassador_events,
    get_ticket,
)
from hrcc_bot.services.escalation import POC_DISPLAY, resolve_lead
from hrcc_bot.pipeline.knowledge import get_reward_tier, retrieve_relevant_chunks


ESCALATION_TOOL_NAME = "create_escalation_ticket"


@tool
def create_escalation_ticket(
    category: str, urgency: str, description: str, poc_name: str
) -> str:
    """Prepare an escalation to a program lead. Nothing is sent until the
    ambassador clicks the Confirm Dispatch button attached to your reply.

    Args:
        category: One of OPS, TECH, or DESIGN.
        urgency: One of P0, P1, or P2.
        description: Brief description of the issue.
        poc_name: Lead to route to — sanskruti, sreesanth, or nitish.
    """
    lead_key = resolve_lead(poc_name, category)
    if lead_key is None:
        return (
            f"Failed to prepare escalation: unknown lead '{poc_name}' / category '{category}'. "
            "Use sanskruti (OPS), sreesanth (TECH), or nitish (DESIGN)."
        )
    return (
        f"Escalation to {POC_DISPLAY[lead_key]} prepared but NOT sent yet. "
        "A 'Confirm Dispatch' button is attached to your reply; the lead is only notified "
        "after the ambassador clicks it. Tell the ambassador to click Confirm Dispatch. "
        "Do not mention a ticket code — none exists until they confirm."
    )


@tool
def lookup_ticket_status(ticket_code: str) -> str:
    """Look up the live status and resolution notes of an escalation ticket.

    Args:
        ticket_code: The ticket identifier, e.g. HRCC-101.
    """
    ticket = get_ticket(ticket_code.upper().strip())
    if not ticket:
        return f"No ticket found with code {ticket_code}."
    status = ticket["status"]
    notes = ticket.get("resolution_notes", "")
    return (
        f"Ticket {ticket['ticket_code']}: Status={status}, "
        f"Category={ticket['category']}, Urgency={ticket['urgency']}, "
        f"POC={ticket['poc_name'].title()}"
        + (f", Resolution: {notes}" if notes else "")
        + f", Created: {ticket['created_at']}"
    )


@tool
def calculate_reward_tier(participant_count: int) -> str:
    """Calculate the exact reward tier based on active participant count.

    Args:
        participant_count: Number of participants who submitted code/answers.
    """
    tier = get_reward_tier(participant_count)
    threshold = tier.get("threshold", "unknown")
    packages = tier.get("winner_package", [])
    has_merch = tier.get("merchandise_included", False)
    certs = tier.get("certificates", "")
    return (
        f"For {participant_count} active participants ({threshold}):\n"
        f"Winner Package: {', '.join(packages)}\n"
        f"Merchandise: {'Yes — shipped to Ambassador as SPOC' if has_merch else 'No'}\n"
        f"Certificates: {certs}"
    )


@tool
def search_handbook_knowledge(query: str) -> str:
    """Search the official Ambassador Handbook and reference docs for relevant info.

    Args:
        query: The search query describing what information is needed.
    """
    chunks = retrieve_relevant_chunks(query, top_k=5)
    if not chunks:
        return "No relevant handbook sections found for this query."
    return "\n\n---\n\n".join(chunks)


@tool
def lookup_ambassador_profile(ambassador_id: int) -> str:
    """Query past event history and stats for a specific ambassador.

    Args:
        ambassador_id: The Discord user ID of the ambassador.
    """
    from hrcc_bot.core.db import get_ambassador_events as _get_events

    events = _get_events(ambassador_id)
    if not events:
        return f"No events recorded for ambassador {ambassador_id}."

    total_participants = sum(e["participant_count"] for e in events)
    merch_events = sum(1 for e in events if e["merch_eligible"])
    lines = [
        f"Ambassador {events[0]['ambassador_name']} — {len(events)} event(s), "
        f"{total_participants} total participants, {merch_events} merch-eligible event(s).",
    ]
    for e in events[:5]:
        lines.append(
            f"  - {e['event_name']} ({e['event_date'] or 'no date'}) "
            f"— {e['participant_count']} participants, {e['reward_tier']}"
        )
    if len(events) > 5:
        lines.append(f"  ... and {len(events) - 5} more.")
    return "\n".join(lines)


ALL_TOOLS = [
    create_escalation_ticket,
    lookup_ticket_status,
    calculate_reward_tier,
    search_handbook_knowledge,
    lookup_ambassador_profile,
]
