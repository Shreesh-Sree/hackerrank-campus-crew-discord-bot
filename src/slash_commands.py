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
    create_ticket,
    get_ambassador_events,
    get_ambassador_profile,
    get_ticket,
    get_ticket_stats,
    update_ambassador_stage,
    upsert_ambassador_profile,
)
from src.escalation import CATEGORY_MAP, POC_DISPLAY, _classify_urgency, _get_poc_id

log = logging.getLogger("hrcc.commands")


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
