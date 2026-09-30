"""Helpers, embeds and constants shared by the slash command modules."""
from __future__ import annotations

import logging
import discord
from discord import ui
from hrcc_bot.config import settings
from hrcc_bot.bot.auth_gate import can_view_user_data
from hrcc_bot.core.db import get_ticket

log = logging.getLogger("hrcc.commands")

QUIZ_QUESTIONS = [
    {
        "q": "Which tab in HRW must ambassadors NEVER access?",
        "options": ["Analytics", "Chakra", "Dashboard", "Settings"],
        "answer": 1,
    },
    {
        "q": "Can you host a campus event on SkillUp?",
        "options": ["Yes, any event", "Only workshops", "No, never", "Only if HRW is down"],
        "answer": 2,
    },
    {
        "q": "What's the minimum for merchandise eligibility?",
        "options": ["100 participants", "200 participants", "300 participants", "500 participants"],
        "answer": 2,
    },
    {
        "q": "What counts as an 'active participant'?",
        "options": ["Registered for event", "Opened the link", "Submitted code/answers", "Attended online"],
        "answer": 2,
    },
    {
        "q": "Contest end time is reached. Can you reopen it?",
        "options": ["Yes, from dashboard", "Yes, contact support", "No, never", "Only within 1 hour"],
        "answer": 2,
    },
]

def _rewards_embed(participants: int) -> discord.Embed:
    if participants >= 300:
        tier = "Tier 300+ (Merchandise Eligible)"
        color = discord.Color.gold()
        merch = "**Yes** — shipped to Ambassador as SPOC"
    else:
        tier = "Standard (< 300)"
        color = discord.Color.blue()
        merch = "No"

    embed = discord.Embed(title="Reward Tier Calculation", color=color)
    embed.add_field(name="Active Participants", value=str(participants), inline=True)
    embed.add_field(name="Tier", value=tier, inline=True)
    embed.add_field(
        name="Winner Package",
        value=(
            "- 1-Year HackerRank Infinity Plan\n"
            "- Mock Interview Credits\n"
            "- 6-Month Access to 1,500+ AI Tools"
        ),
        inline=False,
    )
    embed.add_field(name="Merchandise", value=merch, inline=True)
    embed.add_field(
        name="Certificates",
        value="Official participation certificates for **all** active code submitters.",
        inline=False,
    )
    embed.set_footer(
        text="Active = submitted code/answers. Registration alone does not count."
    )
    return embed

SOP_DATA: dict[str, dict[str, list[str]]] = {
    "contest": {
        "Pre-Event": [
            "Define objective (skill-building / competitive / visibility)",
            "Select format: DSA, MCQ, debugging, or role-based",
            "Prepare/select questions in HRW or HRC",
            "Configure time limits, scoring, and access settings",
            "Test every question yourself before publishing",
            "Set duration with 15-30 min buffer time",
            "Verify registration link in incognito mode",
            "Begin 14-day promotion timeline",
        ],
        "Live Event": [
            "Launch contest at scheduled time",
            "Monitor dashboard for submissions and anomalies",
            "Address candidate issues in real-time",
            "Report any platform errors immediately",
        ],
        "Post-Event": [
            "Finalize rankings from leaderboard",
            "Verify winner identities and HackerRank emails",
            "Submit winner list to Sanskruti (Program Manager)",
            "Track reward activation until confirmed",
            "Issue certificates via Canva Bulk Create",
            "Post results and recap on social media",
            "Document event with short report",
        ],
    },
    "hackathon": {
        "Pre-Event": [
            "Define theme, tracks, and problem statements",
            "Set eligibility rules and team formation policy",
            "Establish judging criteria (Tech, Creativity, Impact, Presentation)",
            "Request HackerRank engineer judge via Sanskruti (14-day notice)",
            "Publish timeline: registration → hacking → submission → judging",
            "Define submission format: repo link, write-up, demo video",
            "Promote across all channels",
        ],
        "Live Event": [
            "Open hacking window at announced time",
            "Run embedded 1-2 hour HackerRank contest segment",
            "Monitor for platform or technical issues",
            "Coordinate judge availability for demo slots",
        ],
        "Post-Event": [
            "Collect and organize all submissions",
            "Run judging panel and determine winners",
            "Submit winner details to Sanskruti",
            "Issue certificates and announce results",
            "Document event and publish recap",
        ],
    },
    "workshop": {
        "Pre-Event": [
            "Choose topic scoped to 60-120 minutes",
            "Confirm speaker (self, collaborator, or HackerRank engineer)",
            "Prepare curriculum with hands-on HackerRank challenge component",
            "Open registration to gauge turnout",
            "Promote using standard timeline",
        ],
        "Live Event": [
            "Run session with hands-on activity",
            "Include Q&A segment",
            "Monitor engagement and participation",
        ],
        "Post-Event": [
            "Collect feedback (form or quick poll)",
            "Share resources and session recap",
            "Issue certificates if applicable",
            "Document and report",
        ],
    },
}

class SOPSelectMenu(ui.Select):
    def __init__(self, event_type: str, sop: dict[str, list[str]]) -> None:
        self.sop = sop
        options = [
            discord.SelectOption(label=phase, description=f"{len(items)} items")
            for phase, items in sop.items()
        ]
        super().__init__(
            placeholder=f"Select {event_type.title()} phase...",
            options=options,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        phase = self.values[0]
        items = self.sop.get(phase, [])
        checklist = "\n".join(f"- [ ] {item}" for item in items)
        embed = discord.Embed(
            title=f"{phase} Checklist",
            description=checklist,
            color=discord.Color.teal(),
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

class SOPView(ui.View):
    def __init__(self, event_type: str) -> None:
        super().__init__(timeout=120)
        sop = SOP_DATA.get(event_type, SOP_DATA["contest"])
        self.add_item(SOPSelectMenu(event_type, sop))

def _certs_embed() -> discord.Embed:
    embed = discord.Embed(
        title="Certificate Generation Guide",
        color=discord.Color.purple(),
    )
    embed.add_field(
        name="Eligibility",
        value="Every participant who submitted code or answers.",
        inline=False,
    )
    embed.add_field(
        name="Template",
        value="Contact **Nitish (Design Lead)** for the official HackerRank certificate template.",
        inline=False,
    )
    embed.add_field(
        name="Canva Bulk Create Steps",
        value=(
            "1. Export participant roster from HRW/HRC\n"
            "2. Format CSV: `Full Name, Email Address, College Name, Event Name, Event Date, Rank, Score`\n"
            "3. Open Canva → template → Apps → Bulk Create → Upload CSV\n"
            "4. Connect data fields → Generate → Download as PDF"
        ),
        inline=False,
    )
    sample = "Full Name,Email Address,College Name,Event Name,Event Date,Rank,Score\nAlice Johnson,alice@example.com,St. Joseph's,CodeStorm 2026,2026-09-19,1,300"
    embed.add_field(name="Sample CSV", value=f"```csv\n{sample}\n```", inline=False)
    return embed

def _marketing_embeds(
    event_name: str, date: str, time: str, url: str
) -> list[discord.Embed]:
    discord_copy = (
        f"**GET READY FOR {event_name}!**\n"
        f"Organized by **HackerRank Campus Crew**\n\n"
        f"**Prizes & Rewards:**\n"
        f"- Top Winners: 1-Year HackerRank Infinity Plan + AI Tools + Mock Interviews\n"
        f"- Official Certificates for ALL active participants!\n"
        f"- Merchandise for top universities (300+ participants)!\n\n"
        f"**Date:** {date} | **Time:** {time}\n"
        f"**Register Now:** <{url}>"
    )

    whatsapp_copy = (
        f"*BIG ANNOUNCEMENT: {event_name}*\n"
        f"Calling all coders! Compete in the official HackerRank Campus Crew contest!\n\n"
        f"*Prizes:*\n"
        f"HackerRank Infinity Plans & Mock Interviews\n"
        f"6-Month Access to 1,500+ AI Tools\n"
        f"Official Certificates for all who submit code!\n\n"
        f"*Date:* {date} | *Time:* {time}\n"
        f"*Link:* {url}"
    )

    linkedin_copy = (
        f"Excited to announce {event_name}, powered by HackerRank Campus Crew!\n\n"
        f"Top performers win HackerRank Infinity Plans, Mock Interview Credits, "
        f"and 6-month access to 1,500+ AI tools.\n\n"
        f"Date: {date} | Time: {time}\n"
        f"Register: {url}\n\n"
        f"#HackerRankCampusCrew #CodingContest #CampusDevelopers"
    )

    return [
        discord.Embed(title="Discord Announcement", description=discord_copy, color=discord.Color.blurple()),
        discord.Embed(title="WhatsApp Broadcast", description=whatsapp_copy, color=discord.Color.green()),
        discord.Embed(title="LinkedIn Post", description=linkedin_copy, color=discord.Color.blue()),
    ]

def _ticket_status_embed(ticket_code: str, viewer_id: int) -> discord.Embed:
    ticket = get_ticket(ticket_code.strip().upper())
    # Same reply for "missing" and "not yours" so ticket codes can't be probed.
    if not ticket or not can_view_user_data(viewer_id, ticket["author_id"]):
        return discord.Embed(
            title="Ticket Not Found",
            description=f"No ticket `{ticket_code}` found on your account.",
            color=discord.Color.red(),
        )

    status_emoji = {"PENDING": "⏳", "ACKNOWLEDGED": "✅", "RESOLVED": "🔒"}
    color_map = {"PENDING": discord.Color.orange(), "ACKNOWLEDGED": discord.Color.green(), "RESOLVED": discord.Color.greyple()}

    embed = discord.Embed(
        title=f"Ticket {ticket['ticket_code']} — {ticket['urgency']}",
        color=color_map.get(ticket["status"], discord.Color.greyple()),
    )
    embed.add_field(name="Status", value=f"{status_emoji.get(ticket['status'], '?')} {ticket['status']}", inline=True)
    embed.add_field(name="Category", value=ticket["category"], inline=True)
    embed.add_field(name="Assigned To", value=ticket["poc_name"].title(), inline=True)
    embed.add_field(name="Reporter", value=ticket["author_name"], inline=True)
    embed.add_field(name="Description", value=ticket["description"][:512] or "—", inline=False)
    if ticket["resolution_notes"]:
        embed.add_field(name="Resolution", value=ticket["resolution_notes"][:512], inline=False)
    embed.set_footer(text=f"Created: {ticket['created_at']}")
    return embed

async def _dm_all_ambassadors(client: discord.Client, text: str) -> tuple[int, int]:
    """DM every HRW-linked ambassador; returns (delivered, total)."""
    from hrcc_bot.core.db import _fetchall
    links = _fetchall("SELECT discord_id FROM hrw_links")
    sent = 0
    for link in links:
        try:
            user = await client.fetch_user(link["discord_id"])
            await user.send(text)
            sent += 1
        except (discord.Forbidden, discord.HTTPException):
            pass
    return sent, len(links)


# Shared lookups (previously locals of register_commands)
LEAD_IDS = {
    int(x) for x in [
        settings.poc_discord_sanskruti,
        settings.poc_discord_sreesanth,
        settings.poc_discord_nitish,
    ] if x
}

INSTITUTIONAL_DOMAINS = {
    ".edu", ".ac.in", ".edu.in", ".ac.uk", ".edu.au", ".edu.cn",
    ".ac.jp", ".edu.sg", ".edu.my", ".ac.id",
}

AUDIENCE_LABELS = {
    "freshers_beginner": "Freshers / Beginners (1st-2nd year, intro to coding)",
    "intermediate_dsa": "Intermediate DSA (2nd-3rd year, data structures & algorithms)",
    "placement_final_year": "Placement-Ready Final Year (advanced DSA + system design)",
}

DURATION_LABELS = {
    "60_mins": "60 Minutes",
    "90_mins": "90 Minutes",
    "120_mins": "120 Minutes",
    "180_mins": "180 Minutes",
}

FOCUS_LABELS = {
    "dsa_algorithms": "DSA & Algorithms",
    "web_dev_frontend": "Web Development / Frontend",
    "python_sql": "Python & SQL",
    "fullstack_debugging": "Full-Stack Debugging",
}
