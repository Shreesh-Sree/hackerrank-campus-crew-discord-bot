from __future__ import annotations

import io
import logging
from typing import Any

import discord
from discord import app_commands, ui

import re

from src.config import settings
from src.csv_validator import build_canva_file, build_summary_embed, parse_contest_csv
from src.db import (
    ACHIEVEMENT_DEFS,
    REGIONS,
    TIER_BADGES,
    create_collab_request,
    create_ticket,
    find_ambassadors_by_country,
    find_ambassadors_by_region,
    get_ambassador_achievements,
    get_ambassador_events,
    get_ambassador_points,
    get_ambassador_profile,
    get_country_leaderboard,
    get_global_leaderboard,
    get_open_collab_requests,
    get_region_leaderboard,
    get_ticket,
    get_ticket_stats,
    resolve_region,
    update_ambassador_stage,
    update_collab_status,
    upsert_ambassador_profile,
)
from src.escalation import CATEGORY_MAP, POC_DISPLAY, _classify_urgency, _get_poc_id

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


# ── /rewards ──────────────────────────────────────────────────────────────


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


# ── /sop ──────────────────────────────────────────────────────────────────


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


# ── /certs ────────────────────────────────────────────────────────────────


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


# ── /marketing ────────────────────────────────────────────────────────────


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


# ── /ticket_status ────────────────────────────────────────────────────────


def _ticket_status_embed(ticket_code: str) -> discord.Embed:
    ticket = get_ticket(ticket_code.upper())
    if not ticket:
        return discord.Embed(
            title="Ticket Not Found",
            description=f"No ticket found with code `{ticket_code}`.",
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


# ── Register all commands ─────────────────────────────────────────────────


def register_commands(tree: app_commands.CommandTree) -> None:

    @tree.command(name="rewards", description="Calculate reward tier based on participant count")
    @app_commands.describe(participants="Number of active participants who submitted code")
    async def rewards_cmd(interaction: discord.Interaction, participants: int) -> None:
        await interaction.response.send_message(embed=_rewards_embed(participants))

    @tree.command(name="sop", description="Event SOP checklists with interactive dropdown")
    @app_commands.describe(event_type="Type of event")
    @app_commands.choices(event_type=[
        app_commands.Choice(name="Coding Contest", value="contest"),
        app_commands.Choice(name="Hackathon", value="hackathon"),
        app_commands.Choice(name="Workshop", value="workshop"),
    ])
    async def sop_cmd(interaction: discord.Interaction, event_type: app_commands.Choice[str]) -> None:
        view = SOPView(event_type.value)
        await interaction.response.send_message(
            f"Select a phase from the **{event_type.name}** SOP:",
            view=view,
        )

    @tree.command(name="certs", description="Certificate generation guide and Canva CSV template")
    async def certs_cmd(interaction: discord.Interaction) -> None:
        await interaction.response.send_message(embed=_certs_embed())

    @tree.command(name="marketing", description="Generate multi-platform promotional copy")
    @app_commands.describe(
        event_name="Name of the event",
        date="Event date (e.g. 19 September 2026)",
        time="Event time (e.g. 3:00 PM IST)",
        url="Registration or contest URL",
    )
    async def marketing_cmd(
        interaction: discord.Interaction,
        event_name: str,
        date: str,
        time: str,
        url: str,
    ) -> None:
        embeds = _marketing_embeds(event_name, date, time, url)
        await interaction.response.send_message(embeds=embeds)

    @tree.command(name="ticket_status", description="Check the status of an escalation ticket")
    @app_commands.describe(ticket_code="Ticket code (e.g. HRCC-101)")
    async def ticket_status_cmd(interaction: discord.Interaction, ticket_code: str) -> None:
        await interaction.response.send_message(embed=_ticket_status_embed(ticket_code))

    @tree.command(name="validate_contest", description="Validate a contest CSV and generate Canva certificate CSV")
    @app_commands.describe(
        csv_file="The contest results CSV file",
        event_name="Name of the event",
        event_date="Event date (e.g. 2026-09-19)",
        college_name="College or institution name",
    )
    async def validate_contest_cmd(
        interaction: discord.Interaction,
        csv_file: discord.Attachment,
        event_name: str = "Campus Event",
        event_date: str = "",
        college_name: str = "",
    ) -> None:
        await interaction.response.defer()

        raw = await csv_file.read()
        result = parse_contest_csv(
            raw, event_name=event_name, event_date=event_date, college_name=college_name
        )

        embed = build_summary_embed(result)
        canva_file = build_canva_file(result)
        await interaction.followup.send(embed=embed, file=canva_file)

    # ── /admin_stats (Lead-restricted) ────────────────────────────────────

    LEAD_IDS = {
        int(x) for x in [
            settings.poc_discord_sanskruti,
            settings.poc_discord_sreesanth,
            settings.poc_discord_nitish,
        ] if x
    }

    @tree.command(name="admin_stats", description="Monthly operations dashboard (leads only)")
    async def admin_stats_cmd(interaction: discord.Interaction) -> None:
        if not LEAD_IDS or interaction.user.id not in LEAD_IDS:
            await interaction.response.send_message(
                "This command is restricted to program leads.", ephemeral=True
            )
            return

        await interaction.response.defer()
        from src.scheduler import _get_all_month_stats
        stats = _get_all_month_stats()

        from datetime import datetime, timezone
        month_name = datetime.now(timezone.utc).strftime("%B %Y")

        embed = discord.Embed(title=f"Admin Dashboard — {month_name}", color=discord.Color.dark_gold())
        embed.add_field(
            name="Events",
            value=(
                f"**Total:** {stats['total_events']}\n"
                f"**Participants:** {stats['total_participants']}\n"
                f"**Merch Tier (300+):** {stats['merch_events']}"
            ),
            inline=True,
        )
        embed.add_field(
            name="Tickets",
            value=(
                f"**Pending:** {stats['tickets']['PENDING']}\n"
                f"**Acknowledged:** {stats['tickets']['ACKNOWLEDGED']}\n"
                f"**Resolved:** {stats['tickets']['RESOLVED']}\n"
                f"**MTTR:** {stats['avg_resolution_hours']}h"
            ),
            inline=True,
        )
        await interaction.followup.send(embed=embed)

    # ── /ambassador [user] ────────────────────────────────────────────────

    @tree.command(name="ambassador", description="View an ambassador's profile and event history")
    @app_commands.describe(user="The ambassador to look up")
    async def ambassador_cmd(interaction: discord.Interaction, user: discord.User) -> None:
        profile = get_ambassador_profile(user.id)
        events = get_ambassador_events(user.id)

        embed = discord.Embed(title=f"Ambassador — {user.display_name}", color=discord.Color.teal())

        pts = get_ambassador_points(user.id)
        if pts:
            badge = TIER_BADGES.get(pts["tier_name"], "🎖️")
            embed.add_field(name="Tier", value=f"{badge} {pts['tier_name']}", inline=True)
            embed.add_field(name="Points", value=str(pts["total_points"]), inline=True)
            embed.add_field(name="Contests", value=str(pts["contests_hosted"]), inline=True)

        if profile:
            embed.add_field(name="College", value=profile["college_name"] or "Not set", inline=True)
            embed.add_field(name="Stage", value=profile["current_stage"], inline=True)
            if profile["notes"]:
                embed.add_field(name="Notes", value=profile["notes"][:256], inline=False)
        else:
            embed.add_field(name="Profile", value="No profile registered yet.", inline=False)

        if events:
            total_p = sum(e["participant_count"] for e in events)
            event_lines = "\n".join(
                f"- **{e['event_name']}** ({e['event_date'] or '—'}) — {e['participant_count']} participants"
                for e in events[:5]
            )
            embed.add_field(name=f"Events ({len(events)} total, {total_p} participants)", value=event_lines, inline=False)
        else:
            embed.add_field(name="Events", value="No events recorded.", inline=False)

        await interaction.response.send_message(embed=embed)

    # ── /set_stage ────────────────────────────────────────────────────────

    @tree.command(name="set_stage", description="Update your active event lifecycle stage")
    @app_commands.describe(stage="Your current event stage")
    @app_commands.choices(stage=[
        app_commands.Choice(name="Planning", value="PLANNING"),
        app_commands.Choice(name="Setup", value="SETUP"),
        app_commands.Choice(name="Outreach", value="OUTREACH"),
        app_commands.Choice(name="Live", value="LIVE"),
        app_commands.Choice(name="Rewards", value="REWARDS"),
    ])
    async def set_stage_cmd(interaction: discord.Interaction, stage: app_commands.Choice[str]) -> None:
        upsert_ambassador_profile(
            ambassador_id=interaction.user.id,
            ambassador_name=interaction.user.display_name,
        )
        updated = update_ambassador_stage(interaction.user.id, stage.value)
        if updated:
            await interaction.response.send_message(
                f"Your event stage has been updated to **{stage.name}**.",
                ephemeral=True,
            )
        else:
            await interaction.response.send_message("Could not update your stage.", ephemeral=True)

    # ── /escalate ─────────────────────────────────────────────────────────

    class EscalateModal(ui.Modal, title="Escalate Issue"):
        issue_desc = ui.TextInput(
            label="Describe the issue",
            style=discord.TextStyle.paragraph,
            placeholder="What happened? Include any error messages or context...",
            required=True,
            max_length=1000,
        )

        def __init__(self, lead_key: str) -> None:
            super().__init__()
            self.lead_key = lead_key

        async def on_submit(self, interaction: discord.Interaction) -> None:
            category = CATEGORY_MAP.get(self.lead_key, "OPS")
            urgency = _classify_urgency(self.issue_desc.value)
            poc_id = _get_poc_id(self.lead_key)

            ticket = create_ticket(
                channel_id=interaction.channel_id or 0,
                message_id=0,
                author_id=interaction.user.id,
                author_name=str(interaction.user),
                category=category,
                urgency=urgency,
                poc_name=self.lead_key,
                poc_id=poc_id,
                description=self.issue_desc.value,
            )

            await interaction.response.send_message(
                f"Ticket **{ticket['ticket_code']}** ({urgency}) dispatched to "
                f"**{POC_DISPLAY.get(self.lead_key, self.lead_key)}**. "
                f"You will be notified upon review.",
                ephemeral=True,
            )

    @tree.command(name="escalate", description="Escalate an issue to a program lead")
    @app_commands.describe(lead="Which lead to route this to")
    @app_commands.choices(lead=[
        app_commands.Choice(name="Sanskruti (Operations/Rewards)", value="sanskruti"),
        app_commands.Choice(name="Sreesanth (Technical/Platform)", value="sreesanth"),
        app_commands.Choice(name="Nitish (Design/Brand)", value="nitish"),
    ])
    async def escalate_cmd(interaction: discord.Interaction, lead: app_commands.Choice[str]) -> None:
        await interaction.response.send_modal(EscalateModal(lead.value))

    # ── /rules ────────────────────────────────────────────────────────────

    @tree.command(name="rules", description="Platform rules and restrictions")
    @app_commands.describe(platform="Which platform")
    @app_commands.choices(platform=[
        app_commands.Choice(name="HackerRank for Work (HRW)", value="hrw"),
        app_commands.Choice(name="HackerRank Community (HRC)", value="hrc"),
        app_commands.Choice(name="HackerRank SkillUp", value="skillup"),
    ])
    async def rules_cmd(interaction: discord.Interaction, platform: app_commands.Choice[str]) -> None:
        from src.knowledge import get_platform_info
        info = get_platform_info(platform.value)
        name = info.get("name", platform.name)
        url = info.get("url", "")
        use = info.get("primary_use", "")
        rules = info.get("rules", {})

        embed = discord.Embed(title=f"Rules — {name}", color=discord.Color.dark_blue())
        embed.add_field(name="URL", value=url or "N/A", inline=True)
        embed.add_field(name="Purpose", value=use or "N/A", inline=False)

        if isinstance(rules, dict):
            for k, v in rules.items():
                embed.add_field(name=k.replace("_", " ").title(), value=str(v), inline=False)
        elif isinstance(rules, str):
            embed.add_field(name="Rule", value=rules, inline=False)

        sec = info.get("security_warning")
        if sec:
            embed.add_field(
                name=f"SECURITY — {sec['tab_name']}",
                value=sec["policy"],
                inline=False,
            )

        features = info.get("features", [])
        if features:
            embed.add_field(
                name="Features",
                value="\n".join(f"- {f}" for f in features[:6]),
                inline=False,
            )

        await interaction.response.send_message(embed=embed)

    # ── /event_check ──────────────────────────────────────────────────────

    @tree.command(name="event_check", description="Pre-flight validation for a contest URL")
    @app_commands.describe(url="The HackerRank contest or test URL to validate")
    async def event_check_cmd(interaction: discord.Interaction, url: str) -> None:
        url_lower = url.lower()

        if "chakra" in url_lower:
            embed = discord.Embed(
                title="CRITICAL SECURITY ALERT",
                description=(
                    "**Chakra tab link detected.** Do NOT share this link with participants.\n\n"
                    "The Chakra tab is strictly internal to HackerRank staff. "
                    "Use the standard HRW test link from your dashboard instead."
                ),
                color=discord.Color.red(),
            )
            await interaction.response.send_message(embed=embed)
            return

        if "skillup" in url_lower:
            embed = discord.Embed(
                title="Invalid Platform",
                description=(
                    "**SkillUp URL detected.** SkillUp cannot be used for hosting campus events.\n\n"
                    "Use **HackerRank for Work (HRW)** or **HackerRank Community (HRC)** instead."
                ),
                color=discord.Color.red(),
            )
            await interaction.response.send_message(embed=embed)
            return

        if "hackerrank.com/work" in url_lower:
            platform = "HackerRank for Work (HRW)"
            color = discord.Color.green()
        elif "hackerrank.com" in url_lower:
            platform = "HackerRank Community (HRC)"
            color = discord.Color.blue()
        else:
            embed = discord.Embed(
                title="Unrecognized URL",
                description="This doesn't appear to be a HackerRank URL. Please check the link.",
                color=discord.Color.orange(),
            )
            await interaction.response.send_message(embed=embed)
            return

        checklist = (
            f"**Platform:** {platform}\n"
            f"**URL:** `{url}`\n\n"
            f"**Pre-Event Checklist:**\n"
            f"- [ ] Contest is published and link is accessible\n"
            f"- [ ] 15-30 minute buffer time configured\n"
            f"- [ ] Public link enabled (test in incognito mode)\n"
            f"- [ ] Proctoring settings reviewed (webcam, tab-switch)\n"
            f"- [ ] All questions tested and locked\n"
            f"- [ ] Registration link shared on promotion channels\n"
            f"- [ ] Emergency POC noted: **Sreesanth** (Tech), **Sanskruti** (Ops)"
        )
        embed = discord.Embed(title="Event Pre-Flight Check", description=checklist, color=color)
        embed.set_footer(text="Run this check 24-48 hours before your event.")
        await interaction.response.send_message(embed=embed)

    # ── /onboard ──────────────────────────────────────────────────────────

    @tree.command(name="onboard", description="Interactive onboarding walkthrough for new ambassadors")
    async def onboard_cmd(interaction: discord.Interaction) -> None:
        upsert_ambassador_profile(
            ambassador_id=interaction.user.id,
            ambassador_name=interaction.user.display_name,
        )
        embed = discord.Embed(
            title="Welcome to HackerRank Campus Crew!",
            description="Let's get you set up. Complete each step below to be fully onboarded.",
            color=discord.Color.green(),
        )
        embed.add_field(
            name="Step 1: Platform Access",
            value=(
                "- [ ] Check email (incl. spam) for HRW activation invite\n"
                "- [ ] Log in at `hackerrank.com/work/login`\n"
                "- [ ] If HRW not yet active, use **HRC** (`hackerrank.com`) to host your first event"
            ),
            inline=False,
        )
        embed.add_field(
            name="Step 2: Golden Rules",
            value=(
                "- **NEVER** access the Chakra tab in HRW (internal only)\n"
                "- **NEVER** use SkillUp to host events\n"
                "- Always set 15-30 min buffer time on contests\n"
                "- Active participant = submitted code, not just registered"
            ),
            inline=False,
        )
        embed.add_field(
            name="Step 3: Your First Event",
            value=(
                "- Use `/sop contest` for a step-by-step checklist\n"
                "- Use `/rewards` to check reward tiers\n"
                "- Use `/marketing` to generate promo copy"
            ),
            inline=False,
        )
        embed.add_field(
            name="Step 4: Know Your Leads",
            value=(
                "- **Sanskruti** (Program Manager): rewards, kits, speakers\n"
                "- **Sreesanth** (Technical Lead): HRW bugs, platform access\n"
                "- **Nitish** (Design Lead): logos, cert templates, brand assets\n"
                "- Use `/escalate` for urgent issues"
            ),
            inline=False,
        )
        embed.set_footer(text="Use /set_stage to track your event lifecycle progress.")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    # ── /resources ────────────────────────────────────────────────────────

    @tree.command(name="resources", description="Ambassador resource hub — brand kit, templates, docs")
    async def resources_cmd(interaction: discord.Interaction) -> None:
        embed = discord.Embed(
            title="Ambassador Resource Hub",
            color=discord.Color.purple(),
        )
        embed.add_field(
            name="Brand Assets",
            value=(
                "Contact **Nitish (Design Lead)** for:\n"
                "- Official HackerRank logo pack (PNG, SVG)\n"
                "- Certificate Canva templates\n"
                "- Event poster templates\n"
                "- Brand guideline document"
            ),
            inline=False,
        )
        embed.add_field(
            name="Templates & SOPs",
            value=(
                "- `/sop contest` — Coding contest checklist\n"
                "- `/sop hackathon` — Hackathon SOP\n"
                "- `/sop workshop` — Workshop SOP\n"
                "- `/certs` — Certificate generation guide\n"
                "- `/marketing` — Promo copy generator"
            ),
            inline=False,
        )
        embed.add_field(
            name="Official Handbook",
            value="handbook.hackerrankcampuscrew.xyz",
            inline=False,
        )
        embed.add_field(
            name="Quick Reference",
            value=(
                "- `/rules hrw` — HRW platform rules\n"
                "- `/rewards` — Reward tier calculator\n"
                "- `/event_check` — Pre-flight URL validator\n"
                "- `/escalate` — Escalate to a lead"
            ),
            inline=False,
        )
        await interaction.response.send_message(embed=embed)

    # ── /request_letter ───────────────────────────────────────────────────

    class LetterRequestModal(ui.Modal, title="Request Permission Letter"):
        ambassador_name = ui.TextInput(label="Your Full Name", required=True, max_length=100)
        college_name = ui.TextInput(label="College / Institution Name", required=True, max_length=200)
        event_name = ui.TextInput(label="Event Name", required=True, max_length=200)
        event_date = ui.TextInput(label="Event Date (e.g. 25 October 2026)", required=True, max_length=50)
        additional_info = ui.TextInput(
            label="Additional Details",
            style=discord.TextStyle.paragraph,
            required=False,
            max_length=500,
            placeholder="Any specific requirements for the letter...",
        )

        async def on_submit(self, interaction: discord.Interaction) -> None:
            category = "OPS"
            urgency = "P2"
            desc = (
                f"Permission Letter Request\n"
                f"Ambassador: {self.ambassador_name.value}\n"
                f"College: {self.college_name.value}\n"
                f"Event: {self.event_name.value}\n"
                f"Date: {self.event_date.value}\n"
                f"Notes: {self.additional_info.value or 'None'}"
            )
            ticket = create_ticket(
                channel_id=interaction.channel_id or 0,
                message_id=0,
                author_id=interaction.user.id,
                author_name=str(interaction.user),
                category=category,
                urgency=urgency,
                poc_name="sanskruti",
                poc_id=_get_poc_id("sanskruti"),
                description=desc,
            )
            await interaction.response.send_message(
                f"Letter request **{ticket['ticket_code']}** submitted to **Sanskruti (Program Manager)**. "
                f"Please allow 7 business days for processing.",
                ephemeral=True,
            )

    @tree.command(name="request_letter", description="Request an institutional permission letter from HackerRank")
    async def request_letter_cmd(interaction: discord.Interaction) -> None:
        await interaction.response.send_modal(LetterRequestModal())

    # ── /request_speaker ──────────────────────────────────────────────────

    class SpeakerRequestModal(ui.Modal, title="Request Speaker / Judge"):
        event_name = ui.TextInput(label="Event Name", required=True, max_length=200)
        event_date = ui.TextInput(label="Event Date (e.g. 15 November 2026)", required=True, max_length=50)
        role_type = ui.TextInput(label="Role Needed (Speaker / Judge / Both)", required=True, max_length=50)
        topic = ui.TextInput(label="Topic or Track", required=False, max_length=200)
        audience_size = ui.TextInput(label="Expected Audience Size", required=True, max_length=20)

        async def on_submit(self, interaction: discord.Interaction) -> None:
            desc = (
                f"Speaker/Judge Request\n"
                f"Event: {self.event_name.value}\n"
                f"Date: {self.event_date.value}\n"
                f"Role: {self.role_type.value}\n"
                f"Topic: {self.topic.value or 'Open'}\n"
                f"Audience: {self.audience_size.value}"
            )

            from datetime import datetime
            try:
                evt_date = datetime.strptime(self.event_date.value.strip(), "%d %B %Y")
                days_ahead = (evt_date - datetime.now()).days
                if days_ahead < 14:
                    await interaction.response.send_message(
                        f"Speaker/judge requests require **14 days advance notice**. "
                        f"Your event is only {days_ahead} days away. "
                        f"Please plan earlier for future events.",
                        ephemeral=True,
                    )
                    return
            except ValueError:
                pass

            ticket = create_ticket(
                channel_id=interaction.channel_id or 0,
                message_id=0,
                author_id=interaction.user.id,
                author_name=str(interaction.user),
                category="OPS",
                urgency="P1",
                poc_name="sanskruti",
                poc_id=_get_poc_id("sanskruti"),
                description=desc,
            )
            await interaction.response.send_message(
                f"Speaker/judge request **{ticket['ticket_code']}** submitted to "
                f"**Sanskruti (Program Manager)**. "
                f"You will be notified once availability is confirmed.\n\n"
                f"**Important:** Do not announce a HackerRank speaker publicly until confirmed.",
                ephemeral=True,
            )

    @tree.command(name="request_speaker", description="Request a HackerRank engineer speaker or judge")
    async def request_speaker_cmd(interaction: discord.Interaction) -> None:
        await interaction.response.send_modal(SpeakerRequestModal())

    # ── /verify_emails ────────────────────────────────────────────────────

    INSTITUTIONAL_DOMAINS = {
        ".edu", ".ac.in", ".edu.in", ".ac.uk", ".edu.au", ".edu.cn",
        ".ac.jp", ".edu.sg", ".edu.my", ".ac.id",
    }

    @tree.command(name="verify_emails", description="Check winner emails before reward submission")
    @app_commands.describe(emails="Comma-separated list of winner emails")
    async def verify_emails_cmd(interaction: discord.Interaction, emails: str) -> None:
        email_list = [e.strip() for e in emails.split(",") if e.strip()]
        if not email_list:
            await interaction.response.send_message("Please provide at least one email.", ephemeral=True)
            return

        email_re = re.compile(r"^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$")
        warnings: list[str] = []
        valid_count = 0

        for email in email_list:
            if not email_re.match(email):
                warnings.append(f"**{email}** — invalid format")
                continue
            domain = email[email.index("@"):]
            is_institutional = any(domain.endswith(d) for d in INSTITUTIONAL_DOMAINS)
            if is_institutional:
                warnings.append(f"**{email}** — institutional domain detected, may not match HackerRank profile")
            else:
                valid_count += 1

        embed = discord.Embed(title="Email Verification Results", color=discord.Color.teal())
        embed.add_field(name="Checked", value=str(len(email_list)), inline=True)
        embed.add_field(name="Likely OK", value=str(valid_count), inline=True)
        embed.add_field(name="Warnings", value=str(len(warnings)), inline=True)

        if warnings:
            embed.add_field(name="Issues Found", value="\n".join(warnings[:10]), inline=False)

        embed.add_field(
            name="Reminder",
            value=(
                "Rewards are activated on HackerRank user profiles. "
                "Confirm that each winner's email matches their **registered HackerRank account email**, "
                "not a college roll-number address."
            ),
            inline=False,
        )
        await interaction.response.send_message(embed=embed)

    # ── /my_status ────────────────────────────────────────────────────────

    @tree.command(name="my_status", description="Your monthly compliance dashboard and event history")
    async def my_status_cmd(interaction: discord.Interaction) -> None:
        uid = interaction.user.id
        profile = get_ambassador_profile(uid)
        events = get_ambassador_events(uid)

        from datetime import datetime, timezone
        month_name = datetime.now(timezone.utc).strftime("%B %Y")

        embed = discord.Embed(
            title=f"Ambassador Status — {month_name}",
            color=discord.Color.teal(),
        )
        embed.set_thumbnail(url=interaction.user.display_avatar.url)

        embed.add_field(
            name="Ambassador",
            value=interaction.user.display_name,
            inline=True,
        )

        college = (profile["college_name"] if profile and profile["college_name"] else "Not set")
        embed.add_field(name="Institution", value=college, inline=True)

        pts = get_ambassador_points(uid)
        if pts:
            badge = TIER_BADGES.get(pts["tier_name"], "🎖️")
            embed.add_field(name="Tier", value=f"{badge} {pts['tier_name']} ({pts['total_points']} pts)", inline=True)
        else:
            embed.add_field(name="Tier", value="🎖️ Apprentice Ambassador (0 pts)", inline=True)

        stage = profile["current_stage"] if profile else "PLANNING"
        stage_emoji = {
            "PLANNING": "📋", "SETUP": "🔧", "OUTREACH": "📢", "LIVE": "🔴", "REWARDS": "🏆"
        }
        embed.add_field(
            name="Current Stage",
            value=f"{stage_emoji.get(stage, '?')} {stage}",
            inline=True,
        )

        now = datetime.now(timezone.utc)
        month_start = now.replace(day=1).strftime("%Y-%m")
        monthly_events = [e for e in events if e["created_at"].startswith(month_start)]

        if monthly_events:
            total_p = sum(e["participant_count"] for e in monthly_events)
            has_merch = any(e["merch_eligible"] for e in monthly_events)
            embed.add_field(
                name=f"Monthly Events ({len(monthly_events)})",
                value=(
                    f"**Participants:** {total_p}\n"
                    f"**Merch Tier:** {'Yes' if has_merch else 'No'}"
                ),
                inline=True,
            )
            compliance = "ACTIVE & COMPLIANT"
            comp_color = discord.Color.green()
        else:
            embed.add_field(name="Monthly Events", value="No events this month yet.", inline=True)
            compliance = "PENDING — no event recorded this month"
            comp_color = discord.Color.orange()

        embed.add_field(name="Standing", value=f"**{compliance}**", inline=False)

        if events:
            recent = events[:3]
            history = "\n".join(
                f"- **{e['event_name']}** ({e['event_date'] or '—'}) — {e['participant_count']}p"
                for e in recent
            )
            embed.add_field(name="Recent Events", value=history, inline=False)

        badges = get_ambassador_achievements(uid)
        if badges:
            badge_display = " ".join(
                str(ACHIEVEMENT_DEFS[b]["emoji"]) for b in badges if b in ACHIEVEMENT_DEFS
            )
            embed.add_field(name="Achievements", value=badge_display, inline=False)

        embed.set_footer(text="Use /set_stage to update your lifecycle. Run at least 1 event/month.")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    # ── /leaderboard ──────────────────────────────────────────────────────

    @tree.command(name="leaderboard", description="Global, regional, or country ambassador leaderboard")
    @app_commands.describe(scope="Leaderboard scope")
    @app_commands.choices(scope=[
        app_commands.Choice(name="Global (Top 10)", value="global"),
        app_commands.Choice(name="My Region", value="my_region"),
        app_commands.Choice(name="My Country", value="my_country"),
    ])
    async def leaderboard_cmd(interaction: discord.Interaction, scope: app_commands.Choice[str]) -> None:
        profile = get_ambassador_profile(interaction.user.id)

        if scope.value == "my_country":
            country = profile["country"] if profile and profile.get("country") else ""
            if not country:
                await interaction.response.send_message("Set your country first with `/set_profile`.", ephemeral=True)
                return
            rows = get_country_leaderboard(country, limit=10)
            title = f"Country Leaderboard — {country}"
        elif scope.value == "my_region":
            region = profile["region"] if profile and profile.get("region") else ""
            if not region:
                await interaction.response.send_message("Set your country first with `/set_profile`.", ephemeral=True)
                return
            rows = get_region_leaderboard(region, limit=10)
            title = f"Region Leaderboard — {region}"
        else:
            rows = get_global_leaderboard(limit=10)
            title = "Global Ambassador Leaderboard"

        if not rows:
            await interaction.response.send_message("No ambassadors on the leaderboard yet.", ephemeral=True)
            return

        embed = discord.Embed(title=title, color=discord.Color.gold())

        lines: list[str] = []
        for i, r in enumerate(rows, start=1):
            badge = TIER_BADGES.get(r["tier_name"], "🎖️")
            medal = {1: "🥇", 2: "🥈", 3: "🥉"}.get(i, f"`#{i}`")
            country_flag = r.get("country", "")
            loc = f" ({country_flag})" if country_flag else ""
            lines.append(
                f"{medal} **{r['ambassador_name']}**{loc} — {r['total_points']} pts "
                f"{badge} | {r['contests_hosted']} contests"
            )

        embed.description = "\n".join(lines)
        embed.set_footer(text="Points: +100/contest, +150/300+ participants | /set_profile to set your country")
        await interaction.response.send_message(embed=embed)

    # ── /set_profile ──────────────────────────────────────────────────────

    class SetProfileModal(ui.Modal, title="Set Your Ambassador Profile"):
        college_input = ui.TextInput(label="College / University", required=True, max_length=200)
        country_input = ui.TextInput(label="Country (e.g. India, United States, Brazil)", required=True, max_length=100)
        timezone_input = ui.TextInput(
            label="Timezone (e.g. Asia/Kolkata, US/Eastern, UTC)",
            required=False, max_length=50, placeholder="UTC",
        )

        async def on_submit(self, interaction: discord.Interaction) -> None:
            country = self.country_input.value.strip()
            region = resolve_region(country)
            tz = self.timezone_input.value.strip() or "UTC"

            upsert_ambassador_profile(
                ambassador_id=interaction.user.id,
                ambassador_name=interaction.user.display_name,
                college_name=self.college_input.value.strip(),
                country=country,
                region=region,
                timezone_str=tz,
            )
            await interaction.response.send_message(
                f"Profile updated!\n"
                f"**College:** {self.college_input.value.strip()}\n"
                f"**Country:** {country}\n"
                f"**Region:** {region}\n"
                f"**Timezone:** {tz}",
                ephemeral=True,
            )

    @tree.command(name="set_profile", description="Set your college, country, and timezone")
    async def set_profile_cmd(interaction: discord.Interaction) -> None:
        await interaction.response.send_modal(SetProfileModal())

    # ── /find_ambassador ──────────────────────────────────────────────────

    @tree.command(name="find_ambassador", description="Find ambassadors in a country or region")
    @app_commands.describe(
        scope="Search by country or region",
        query="Country name (e.g. Brazil) or region (e.g. Asia-Pacific)",
    )
    @app_commands.choices(scope=[
        app_commands.Choice(name="Country", value="country"),
        app_commands.Choice(name="Region", value="region"),
    ])
    async def find_ambassador_cmd(
        interaction: discord.Interaction,
        scope: app_commands.Choice[str],
        query: str,
    ) -> None:
        if scope.value == "region":
            rows = find_ambassadors_by_region(query.strip(), limit=20)
            title = f"Ambassadors in {query.strip()}"
        else:
            rows = find_ambassadors_by_country(query.strip(), limit=20)
            title = f"Ambassadors in {query.strip()}"

        if not rows:
            await interaction.response.send_message(
                f"No ambassadors found in {query.strip()}.", ephemeral=True
            )
            return

        embed = discord.Embed(title=title, color=discord.Color.teal())
        lines = []
        for r in rows[:15]:
            college = r.get("college_name", "")
            country = r.get("country", "")
            stage = r.get("current_stage", "")
            lines.append(f"- **{r['ambassador_name']}** — {college}, {country} ({stage})")
        embed.description = "\n".join(lines)
        if len(rows) > 15:
            embed.set_footer(text=f"Showing 15 of {len(rows)} ambassadors")
        await interaction.response.send_message(embed=embed)

    # ── /collab_request ───────────────────────────────────────────────────

    class CollabModal(ui.Modal, title="Cross-Campus Collaboration Request"):
        event_name_input = ui.TextInput(label="Event Name", required=True, max_length=200)
        event_format_input = ui.TextInput(
            label="Format (contest / hackathon / workshop / joint)",
            required=True, max_length=50,
        )
        proposed_date_input = ui.TextInput(label="Proposed Date (e.g. 15 November 2026)", required=True, max_length=50)
        target_country_input = ui.TextInput(
            label="Target Country or Region (or 'any')",
            required=False, max_length=100, placeholder="any",
        )
        message_input = ui.TextInput(
            label="Message to potential collaborators",
            style=discord.TextStyle.paragraph,
            required=False, max_length=500,
        )

        async def on_submit(self, interaction: discord.Interaction) -> None:
            req = create_collab_request(
                requester_id=interaction.user.id,
                requester_name=interaction.user.display_name,
                target_country=self.target_country_input.value.strip() or "any",
                event_name=self.event_name_input.value.strip(),
                event_format=self.event_format_input.value.strip(),
                proposed_date=self.proposed_date_input.value.strip(),
                message=self.message_input.value.strip(),
            )
            await interaction.response.send_message(
                f"Collaboration request **#{req.get('id', '?')}** posted!\n"
                f"**Event:** {self.event_name_input.value}\n"
                f"**Target:** {self.target_country_input.value or 'Open to all'}\n"
                f"Other ambassadors can find this via `/collab_browse`.",
                ephemeral=True,
            )

    @tree.command(name="collab_request", description="Post a cross-campus collaboration request")
    async def collab_request_cmd(interaction: discord.Interaction) -> None:
        await interaction.response.send_modal(CollabModal())

    # ── /collab_browse ────────────────────────────────────────────────────

    @tree.command(name="collab_browse", description="Browse open collaboration requests from ambassadors worldwide")
    async def collab_browse_cmd(interaction: discord.Interaction) -> None:
        requests = get_open_collab_requests(limit=10)
        if not requests:
            await interaction.response.send_message("No open collaboration requests right now.", ephemeral=True)
            return

        embed = discord.Embed(title="Open Collaboration Requests", color=discord.Color.purple())
        for req in requests:
            target = req.get("target_country", "any")
            embed.add_field(
                name=f"#{req['id']} — {req['event_name']}",
                value=(
                    f"**By:** {req['requester_name']} | **Format:** {req.get('event_format', '—')}\n"
                    f"**Date:** {req.get('proposed_date', '—')} | **Target:** {target}\n"
                    f"{req.get('message', '')[:100]}"
                ),
                inline=False,
            )
        embed.set_footer(text="DM the requester to discuss, or use /collab_request to post your own!")
        await interaction.response.send_message(embed=embed)

    # ── /curate_contest ───────────────────────────────────────────────────

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

    @tree.command(name="curate_contest", description="AI-powered contest blueprint generator for HRW")
    @app_commands.describe(
        audience="Target audience level",
        duration="Contest duration",
        focus="Primary focus area",
        college_name="College or institution name (optional)",
    )
    @app_commands.choices(
        audience=[
            app_commands.Choice(name="Freshers / Beginners", value="freshers_beginner"),
            app_commands.Choice(name="Intermediate DSA", value="intermediate_dsa"),
            app_commands.Choice(name="Placement Final Year", value="placement_final_year"),
        ],
        duration=[
            app_commands.Choice(name="60 Minutes", value="60_mins"),
            app_commands.Choice(name="90 Minutes", value="90_mins"),
            app_commands.Choice(name="120 Minutes", value="120_mins"),
            app_commands.Choice(name="180 Minutes", value="180_mins"),
        ],
        focus=[
            app_commands.Choice(name="DSA & Algorithms", value="dsa_algorithms"),
            app_commands.Choice(name="Web Dev / Frontend", value="web_dev_frontend"),
            app_commands.Choice(name="Python & SQL", value="python_sql"),
            app_commands.Choice(name="Full-Stack Debugging", value="fullstack_debugging"),
        ],
    )
    async def curate_contest_cmd(
        interaction: discord.Interaction,
        audience: app_commands.Choice[str],
        duration: app_commands.Choice[str],
        focus: app_commands.Choice[str],
        college_name: str = "",
    ) -> None:
        await interaction.response.defer()

        from src.prompts.template_manager import get_template_manager
        from src.llm_client import get_llm

        tm = get_template_manager()
        prompt = tm.render_template(
            "contest_curator",
            audience_label=AUDIENCE_LABELS.get(audience.value, audience.name),
            duration_label=DURATION_LABELS.get(duration.value, duration.name),
            focus_label=FOCUS_LABELS.get(focus.value, focus.name),
            college_name=college_name,
        )

        try:
            from langchain_core.messages import HumanMessage as HM, SystemMessage as SM
            llm = get_llm()
            result = await llm.ainvoke([SM(content=prompt), HM(content="Generate the contest blueprint now.")])
            blueprint = result.content.strip()
        except Exception:
            log.exception("Contest curator LLM call failed")
            await interaction.followup.send(
                "Could not generate the contest blueprint right now. Please try again later.",
                ephemeral=True,
            )
            return

        embed = discord.Embed(
            title=f"Contest Blueprint — {focus.name}",
            color=discord.Color.dark_purple(),
        )
        embed.add_field(name="Audience", value=audience.name, inline=True)
        embed.add_field(name="Duration", value=duration.name, inline=True)
        embed.add_field(name="Focus", value=focus.name, inline=True)
        if college_name:
            embed.add_field(name="College", value=college_name, inline=True)

        from src.rubrics import chunk_message
        chunks = chunk_message(blueprint, limit=1024)
        for i, chunk in enumerate(chunks[:4]):
            name = "Blueprint" if i == 0 else f"Blueprint (cont. {i+1})"
            embed.add_field(name=name, value=chunk, inline=False)

        embed.set_footer(text="Generated by HRCC Bot AI — review and customize before publishing on HRW.")
        await interaction.followup.send(embed=embed)

    # ── /create_event wizard ──────────────────────────────────────────────

    class CreateEventModal(ui.Modal, title="Create New Event"):
        event_name_input = ui.TextInput(label="Event Name", required=True, max_length=200)
        event_format_input = ui.TextInput(
            label="Format (contest / hackathon / workshop / tech talk)",
            required=True, max_length=50,
        )
        event_date_input = ui.TextInput(label="Event Date (e.g. 15 November 2026)", required=True, max_length=50)
        platform_input = ui.TextInput(label="Platform (HRW / HRC)", required=True, max_length=10, placeholder="HRW")
        expected_input = ui.TextInput(label="Expected Participants", required=False, max_length=10, placeholder="200")

        async def on_submit(self, interaction: discord.Interaction) -> None:
            await interaction.response.defer()

            from src.db import record_event_submission as _record, upsert_ambassador_profile as _upsert
            _upsert(
                ambassador_id=interaction.user.id,
                ambassador_name=interaction.user.display_name,
            )

            event_name = self.event_name_input.value.strip()
            event_format = self.event_format_input.value.strip()
            event_date = self.event_date_input.value.strip()
            platform = self.platform_input.value.strip().upper()
            expected = self.expected_input.value.strip() or ""

            profile = get_ambassador_profile(interaction.user.id)
            college = profile["college_name"] if profile and profile.get("college_name") else ""

            from src.prompts.template_manager import get_template_manager
            from src.llm_client import get_llm
            tm = get_template_manager()
            prompt = tm.render_template(
                "event_wizard",
                event_name=event_name,
                event_format=event_format,
                event_date=event_date,
                platform=platform,
                college_name=college,
                expected_participants=expected,
            )

            try:
                from langchain_core.messages import HumanMessage as HM, SystemMessage as SM
                llm = get_llm()
                result = await llm.ainvoke([SM(content=prompt), HM(content="Generate the event plan.")])
                plan_text = result.content.strip()
            except Exception:
                plan_text = (
                    f"**{event_name}** — {event_format} on {platform}\n"
                    f"Date: {event_date}\n\n"
                    f"Use `/sop {event_format}` for the detailed checklist."
                )

            embed = discord.Embed(
                title=f"Event Plan — {event_name}",
                color=discord.Color.green(),
            )
            embed.add_field(name="Format", value=event_format, inline=True)
            embed.add_field(name="Date", value=event_date, inline=True)
            embed.add_field(name="Platform", value=platform, inline=True)
            if expected:
                embed.add_field(name="Expected", value=expected, inline=True)

            from src.rubrics import chunk_message as _chunk
            chunks = _chunk(plan_text, limit=1024)
            for i, chunk in enumerate(chunks[:3]):
                name = "Plan" if i == 0 else f"Plan (cont.)"
                embed.add_field(name=name, value=chunk, inline=False)

            embed.set_footer(text="Event reminders will be sent automatically at T-72h, T-24h, and T+24h.")
            await interaction.followup.send(embed=embed)

    @tree.command(name="create_event", description="Guided event creation wizard with AI-generated plan")
    async def create_event_cmd(interaction: discord.Interaction) -> None:
        await interaction.response.send_modal(CreateEventModal())

    # ── /submit_report ────────────────────────────────────────────────────

    class SubmitReportModal(ui.Modal, title="Submit Post-Event Report"):
        event_name_input = ui.TextInput(label="Event Name", required=True, max_length=200)
        contest_link_input = ui.TextInput(label="Contest Link (HRW/HRC URL)", required=True, max_length=300)
        participant_count_input = ui.TextInput(label="Active Participants (submitted code)", required=True, max_length=10)
        winners_input = ui.TextInput(
            label="Winners (Name | Email, one per line)",
            style=discord.TextStyle.paragraph,
            required=True,
            max_length=1000,
        )
        notes_input = ui.TextInput(
            label="Event Notes / Feedback",
            style=discord.TextStyle.paragraph,
            required=False,
            max_length=500,
        )

        async def on_submit(self, interaction: discord.Interaction) -> None:
            try:
                pcount = int(self.participant_count_input.value.strip())
            except ValueError:
                pcount = 0

            merch = pcount >= 300
            tier = "Tier 300+" if merch else "Standard (< 300)"

            from src.db import record_event_submission as _record, award_points as _award
            _record(
                ambassador_id=interaction.user.id,
                ambassador_name=interaction.user.display_name,
                event_name=self.event_name_input.value.strip(),
                participant_count=pcount,
                reward_tier=tier,
                merch_eligible=merch,
            )

            _award(
                ambassador_id=interaction.user.id,
                ambassador_name=interaction.user.display_name,
                points_delta=100,
                action_type="CONTEST_HOSTED",
                description=self.event_name_input.value.strip(),
            )
            _award(
                ambassador_id=interaction.user.id,
                ambassador_name=interaction.user.display_name,
                points_delta=50,
                action_type="ON_TIME_REPORT",
                description=f"Submitted report for {self.event_name_input.value.strip()}",
            )
            if merch:
                _award(
                    ambassador_id=interaction.user.id,
                    ambassador_name=interaction.user.display_name,
                    points_delta=150,
                    action_type="PARTICIPANTS_300_PLUS",
                    description=f"{pcount} participants",
                )

            report = (
                f"**Post-Event Report Submitted**\n\n"
                f"**Event:** {self.event_name_input.value}\n"
                f"**Contest Link:** {self.contest_link_input.value}\n"
                f"**Active Participants:** {pcount}\n"
                f"**Reward Tier:** {tier}\n"
                f"**Merch Eligible:** {'Yes' if merch else 'No'}\n\n"
                f"**Winners:**\n{self.winners_input.value}\n"
            )
            if self.notes_input.value:
                report += f"\n**Notes:** {self.notes_input.value}\n"

            report += "\n*+100 pts (contest) + 50 pts (on-time report) awarded.*"

            await interaction.response.send_message(report, ephemeral=True)

            try:
                await interaction.user.send(
                    f"**Your full report (DM the winner details to the Program Manager):**\n\n{report}"
                )
            except discord.Forbidden:
                pass

    @tree.command(name="submit_report", description="Submit your post-event report with winners")
    async def submit_report_cmd(interaction: discord.Interaction) -> None:
        await interaction.response.send_modal(SubmitReportModal())

    # ── /onboard_quiz ─────────────────────────────────────────────────────

    class QuizView(ui.View):
        def __init__(self, user_id: int) -> None:
            super().__init__(timeout=300)
            self.user_id = user_id
            self.current_q = 0
            self.score = 0

        async def _send_question(self, interaction: discord.Interaction) -> None:
            if self.current_q >= len(QUIZ_QUESTIONS):
                passed = self.score >= 4
                result_text = (
                    f"**Quiz Complete!** Score: {self.score}/{len(QUIZ_QUESTIONS)}\n\n"
                )
                if passed:
                    result_text += "**Passed!** +50 points awarded."
                    from src.db import award_points as _award
                    _award(
                        ambassador_id=self.user_id,
                        ambassador_name="",
                        points_delta=50,
                        action_type="QUIZ_PASSED",
                        description="Onboarding handbook quiz",
                    )
                else:
                    result_text += "You need 4/5 to pass. Review `/rules` and try again."
                self.clear_items()
                await interaction.response.edit_message(content=result_text, view=self)
                return

            q = QUIZ_QUESTIONS[self.current_q]
            text = f"**Question {self.current_q + 1}/5:** {q['q']}\n\n"
            for i, opt in enumerate(q["options"]):
                text += f"**{i + 1}.** {opt}\n"

            self.clear_items()
            for i in range(len(q["options"])):
                btn = ui.Button(label=str(i + 1), style=discord.ButtonStyle.secondary)
                btn.callback = self._make_callback(i)
                self.add_item(btn)

            await interaction.response.edit_message(content=text, view=self)

        def _make_callback(self, choice: int):
            async def callback(interaction: discord.Interaction) -> None:
                if interaction.user.id != self.user_id:
                    await interaction.response.send_message("This quiz isn't yours.", ephemeral=True)
                    return
                q = QUIZ_QUESTIONS[self.current_q]
                if choice == q["answer"]:
                    self.score += 1
                self.current_q += 1
                await self._send_question(interaction)
            return callback

    @tree.command(name="onboard_quiz", description="Test your handbook knowledge (5 questions, +50 pts on pass)")
    async def onboard_quiz_cmd(interaction: discord.Interaction) -> None:
        view = QuizView(interaction.user.id)
        q = QUIZ_QUESTIONS[0]
        text = f"**Handbook Knowledge Quiz**\n\n**Question 1/5:** {q['q']}\n\n"
        for i, opt in enumerate(q["options"]):
            text += f"**{i + 1}.** {opt}\n"

        for i in range(len(q["options"])):
            btn = ui.Button(label=str(i + 1), style=discord.ButtonStyle.secondary)
            btn.callback = view._make_callback(i)
            view.add_item(btn)

        await interaction.response.send_message(content=text, view=view, ephemeral=True)

    # ── /benchmark ────────────────────────────────────────────────────────

    @tree.command(name="benchmark", description="Compare your event stats against the global average")
    async def benchmark_cmd(interaction: discord.Interaction) -> None:
        uid = interaction.user.id
        my_events = get_ambassador_events(uid)
        my_pts = get_ambassador_points(uid)

        from src.scheduler import _get_all_month_stats
        global_stats = _get_all_month_stats()

        all_ambassadors = get_global_leaderboard(limit=1000)
        total_amb = len(all_ambassadors) or 1
        avg_points = sum(a["total_points"] for a in all_ambassadors) / total_amb if all_ambassadors else 0
        avg_contests = sum(a["contests_hosted"] for a in all_ambassadors) / total_amb if all_ambassadors else 0

        my_total_p = sum(e["participant_count"] for e in my_events) if my_events else 0
        my_contests = my_pts["contests_hosted"] if my_pts else 0
        my_points = my_pts["total_points"] if my_pts else 0

        embed = discord.Embed(title="Your Performance vs Global Average", color=discord.Color.dark_purple())

        def _bar(my: float, avg: float) -> str:
            if avg == 0:
                return "N/A"
            pct = my / avg * 100
            filled = min(int(pct / 10), 10)
            bar = "█" * filled + "░" * (10 - filled)
            return f"`{bar}` {pct:.0f}% of avg"

        embed.add_field(name="Points", value=f"**You:** {my_points} | **Avg:** {avg_points:.0f}\n{_bar(my_points, avg_points)}", inline=False)
        embed.add_field(name="Contests", value=f"**You:** {my_contests} | **Avg:** {avg_contests:.1f}\n{_bar(my_contests, avg_contests)}", inline=False)
        embed.add_field(name="Total Participants", value=f"**You:** {my_total_p} | **Global:** {global_stats['total_participants']}", inline=False)
        embed.add_field(name="Ambassadors Tracked", value=str(total_amb), inline=True)

        embed.set_footer(text="Keep hosting events to climb the leaderboard!")
        await interaction.response.send_message(embed=embed, ephemeral=True)
