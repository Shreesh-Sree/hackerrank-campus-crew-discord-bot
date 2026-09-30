"""Ambassador self-service commands (registration gate applies unless ALLOW_ALL_USERS)."""
from __future__ import annotations

import discord
from discord import app_commands, ui
import re
from hrcc_bot.config import settings
from hrcc_bot.services.csv_validator import build_canva_file, build_summary_embed, parse_contest_csv
from hrcc_bot.services.letter_service import generate_permission_letter_pdf
from hrcc_bot.bot.letter_views import LetterApprovalView
from hrcc_bot.bot.auth_gate import Role, get_user_role
from hrcc_bot.core.db import (
    ACHIEVEMENT_DEFS,
    TIER_BADGES,
    create_ticket,
    get_ambassador_achievements,
    get_ambassador_events,
    get_ambassador_points,
    get_ambassador_profile,
    get_global_leaderboard,
    get_hrw_link,
    resolve_region,
    update_ambassador_stage,
    upsert_ambassador_profile,
)
from hrcc_bot.services.escalation import _get_poc_id, _send_poc_dm, format_outcome, open_escalation
from hrcc_bot.bot.troubleshoot import (
    NODES,
    TroubleshootView,
    build_embed as build_troubleshoot_embed,
)
from hrcc_bot.services.verify_emails import run_full_verification
from hrcc_bot.bot.commands._common import (
    AUDIENCE_LABELS,
    DURATION_LABELS,
    FOCUS_LABELS,
    INSTITUTIONAL_DOMAINS,
    QUIZ_QUESTIONS,
    _marketing_embeds,
    _ticket_status_embed,
    log,
)


def register(tree: app_commands.CommandTree) -> None:
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
        await interaction.response.send_message(
            embed=_ticket_status_embed(ticket_code, interaction.user.id), ephemeral=True
        )

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

    @tree.command(name="troubleshoot", description="Step-by-step fixes for common HRW/HRC issues, with one-click escalation")
    async def troubleshoot_cmd(interaction: discord.Interaction) -> None:
        view = TroubleshootView(requester_id=interaction.user.id)
        await interaction.response.send_message(embed=build_troubleshoot_embed(NODES["root"]), view=view, ephemeral=True)

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
            await interaction.response.defer(ephemeral=True)
            outcome = await open_escalation(
                client=interaction.client,
                channel_id=interaction.channel_id or 0,
                message_id=0,
                author_id=interaction.user.id,
                author_name=str(interaction.user),
                lead_key=self.lead_key,
                description=self.issue_desc.value,
            )
            await interaction.followup.send(format_outcome(outcome), ephemeral=True)

    @tree.command(name="escalate", description="Escalate an issue to a program lead")
    @app_commands.describe(lead="Which lead to route this to")
    @app_commands.choices(lead=[
        app_commands.Choice(name="Sanskruti (Operations/Rewards)", value="sanskruti"),
        app_commands.Choice(name="Sreesanth (Technical/Platform)", value="sreesanth"),
        app_commands.Choice(name="Nitish (Design/Brand)", value="nitish"),
    ])
    async def escalate_cmd(interaction: discord.Interaction, lead: app_commands.Choice[str]) -> None:
        await interaction.response.send_modal(EscalateModal(lead.value))

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
                poc_name="sreesanth",
                poc_id=_get_poc_id("sreesanth") or _get_poc_id("sanskruti"),
                description=desc,
            )

            # Generate preview PDF draft
            pdf_path = f"/tmp/{ticket['ticket_code']}_permission_letter.pdf"
            generate_permission_letter_pdf(
                ambassador_name=self.ambassador_name.value.strip(),
                college_name=self.college_name.value.strip(),
                event_name=self.event_name.value.strip(),
                event_date=self.event_date.value.strip(),
                output_pdf=pdf_path,
            )

            # 1. Inform student that the letter is created and submitted for approval
            await interaction.response.send_message(
                f"📄 Permission Letter draft **{ticket['ticket_code']}** has been generated!\n"
                f"Your request has been forwarded to the **Program Administrators / Leads** for review and approval.\n"
                f"Once approved, your official signed letter will be dispatched to you directly here.",
                ephemeral=True,
            )

            # 2. Dispatch approval card + PDF to Home Support Channel or Lead POC
            details = {
                "ambassador_name": self.ambassador_name.value.strip(),
                "college_name": self.college_name.value.strip(),
                "event_name": self.event_name.value.strip(),
                "event_date": self.event_date.value.strip(),
                "author_id": interaction.user.id,
                "channel_id": interaction.channel_id,
            }

            approval_embed = discord.Embed(
                title=f"📋 New Permission Letter Request — {ticket['ticket_code']}",
                description=(
                    f"**Ambassador:** {self.ambassador_name.value} (<@{interaction.user.id}>)\n"
                    f"**College:** {self.college_name.value}\n"
                    f"**Event:** {self.event_name.value}\n"
                    f"**Event Date:** {self.event_date.value}\n"
                    f"**Notes:** {self.additional_info.value or 'None'}\n\n"
                    f"*Review the attached draft PDF below. You can approve, edit details, or reject this request.*"
                ),
                color=discord.Color.blue(),
            )
            approval_view = LetterApprovalView(ticket["ticket_code"], details)
            file = discord.File(pdf_path, filename=f"Draft_{ticket['ticket_code']}_Permission_Letter.pdf")

            # Send to home channel or dispatch to POC DM
            target_channel = None
            if settings.discord_home_channel:
                target_channel = interaction.client.get_channel(settings.discord_home_channel)
                if not target_channel:
                    try:
                        target_channel = await interaction.client.fetch_channel(settings.discord_home_channel)
                    except Exception:
                        pass

            if target_channel:
                await target_channel.send(embed=approval_embed, file=file, view=approval_view)
            else:
                # Fallback to current channel
                if interaction.channel:
                    await interaction.channel.send(embed=approval_embed, file=file, view=approval_view)

    @tree.command(name="request_letter", description="Request an institutional permission letter from HackerRank")
    async def request_letter_cmd(interaction: discord.Interaction) -> None:
        await interaction.response.send_modal(LetterRequestModal())

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
            if ticket["poc_id"] and settings.enable_dm_routing:
                await _send_poc_dm(interaction.client, ticket)

    @tree.command(name="request_speaker", description="Request a HackerRank engineer speaker or judge")
    async def request_speaker_cmd(interaction: discord.Interaction) -> None:
        await interaction.response.send_modal(SpeakerRequestModal())

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

        from hrcc_bot.pipeline.prompts.template_manager import get_template_manager
        from hrcc_bot.core.llm_client import get_llm

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

        from hrcc_bot.pipeline.rubrics import chunk_message
        chunks = chunk_message(blueprint, limit=1024)
        for i, chunk in enumerate(chunks[:4]):
            name = "Blueprint" if i == 0 else f"Blueprint (cont. {i+1})"
            embed.add_field(name=name, value=chunk, inline=False)

        embed.set_footer(text="Generated by HRCC Bot AI — review and customize before publishing on HRW.")
        await interaction.followup.send(embed=embed)

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

            from hrcc_bot.core.db import record_event_submission as _record, upsert_ambassador_profile as _upsert
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

            from hrcc_bot.pipeline.prompts.template_manager import get_template_manager
            from hrcc_bot.core.llm_client import get_llm
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

            from hrcc_bot.pipeline.rubrics import chunk_message as _chunk
            chunks = _chunk(plan_text, limit=1024)
            for i, chunk in enumerate(chunks[:3]):
                name = "Plan" if i == 0 else f"Plan (cont.)"
                embed.add_field(name=name, value=chunk, inline=False)

            embed.set_footer(text="Event reminders will be sent automatically at T-72h, T-24h, and T+24h.")
            await interaction.followup.send(embed=embed)

    @tree.command(name="create_event", description="Guided event creation wizard with AI-generated plan")
    async def create_event_cmd(interaction: discord.Interaction) -> None:
        await interaction.response.send_modal(CreateEventModal())

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

            from hrcc_bot.core.db import record_event_submission as _record, award_points as _award
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
                    from hrcc_bot.core.db import award_points as _award
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

    @tree.command(name="benchmark", description="Compare your event stats against the global average")
    async def benchmark_cmd(interaction: discord.Interaction) -> None:
        uid = interaction.user.id
        my_events = get_ambassador_events(uid)
        my_pts = get_ambassador_points(uid)

        from hrcc_bot.services.scheduler import _get_all_month_stats
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

    @tree.command(name="my_tests", description="View your HRW tests with live status")
    async def my_tests_cmd(interaction: discord.Interaction) -> None:
        link = get_hrw_link(interaction.user.id)
        if not link:
            await interaction.response.send_message("Run `/register` first.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)

        from hrcc_bot.services.hrw_api import get_tests_for_owner
        try:
            tests = await get_tests_for_owner(link["hrw_user_id"])
        except Exception:
            await interaction.followup.send("Could not connect to HRW API.", ephemeral=True)
            return

        if not tests:
            await interaction.followup.send("No tests found under your HRW account.", ephemeral=True)
            return

        embed = discord.Embed(title="Your HRW Tests", color=discord.Color.blue())

        for t in tests[:10]:
            state_emoji = {"active": "🟢", "draft": "📝"}.get(t.get("state", ""), "⚪")
            draft = " (DRAFT)" if t.get("draft") else ""
            locked = " 🔒" if t.get("locked") else ""
            q_count = len(t.get("questions", []))
            sections = len(t.get("sections", []))

            embed.add_field(
                name=f"{state_emoji} {t['name'][:50]}{draft}{locked}",
                value=(
                    f"**ID:** `{t['id']}` | **Duration:** {t['duration']}min\n"
                    f"**Questions:** {q_count} | **Sections:** {sections}\n"
                    f"**Created:** {t.get('created_at', '?')[:10]}"
                ),
                inline=False,
            )

        embed.set_footer(text=f"Showing {min(len(tests), 10)} of {len(tests)} tests. Use /test_status [id] for details.")
        await interaction.followup.send(embed=embed, ephemeral=True)

    @tree.command(name="test_status", description="Real-time contest monitoring for your test")
    @app_commands.describe(test_id="HRW Test ID (from /my_tests)")
    async def test_status_cmd(interaction: discord.Interaction, test_id: str) -> None:
        link = get_hrw_link(interaction.user.id)
        if not link:
            await interaction.response.send_message("Run `/register` first.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)

        from hrcc_bot.services.hrw_api import verify_test_ownership, get_test, get_test_candidates
        if not await verify_test_ownership(test_id, link["hrw_user_id"]):
            role = get_user_role(interaction.user.id)
            if role < Role.ADMIN:
                await interaction.followup.send("You don't have access to this test.", ephemeral=True)
                return

        try:
            test = await get_test(test_id)
            candidates = await get_test_candidates(test_id, limit=10)
        except Exception:
            await interaction.followup.send("Could not fetch test data from HRW.", ephemeral=True)
            return

        total_candidates = candidates.get("total", 0)
        status_counts = candidates.get("status_counts", {})

        embed = discord.Embed(
            title=f"Test Status — {test.get('name', test_id)[:50]}",
            color=discord.Color.green() if total_candidates > 0 else discord.Color.orange(),
        )
        embed.add_field(name="Duration", value=f"{test.get('duration', '?')} min", inline=True)
        embed.add_field(name="Questions", value=str(len(test.get("questions", []))), inline=True)
        embed.add_field(name="State", value=test.get("state", "?"), inline=True)
        embed.add_field(name="Total Candidates", value=str(total_candidates), inline=True)

        if status_counts:
            sc_text = "\n".join(f"**{k}:** {v}" for k, v in status_counts.items())
            embed.add_field(name="Status Breakdown", value=sc_text, inline=False)

        cand_list = candidates.get("data", [])
        if cand_list:
            lines = []
            for c in cand_list[:5]:
                name = c.get("full_name", c.get("email", "?"))
                score = c.get("percentage_score", c.get("score", "?"))
                status = c.get("status", "?")
                lines.append(f"- **{name}** — Score: {score} | {status}")
            embed.add_field(name="Recent Candidates", value="\n".join(lines), inline=False)

        embed.set_footer(text="Data from HRW API. Refresh by running the command again.")
        await interaction.followup.send(embed=embed, ephemeral=True)

    @tree.command(name="preflight", description="Deep test configuration validator via HRW API")
    @app_commands.describe(test_id="HRW Test ID to validate")
    async def preflight_cmd(interaction: discord.Interaction, test_id: str) -> None:
        link = get_hrw_link(interaction.user.id)
        if not link:
            await interaction.response.send_message("Run `/register` first.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)

        from hrcc_bot.services.hrw_api import verify_test_ownership, get_test
        if not await verify_test_ownership(test_id, link["hrw_user_id"]):
            role = get_user_role(interaction.user.id)
            if role < Role.ADMIN:
                await interaction.followup.send("You don't have access to this test.", ephemeral=True)
                return

        try:
            test = await get_test(test_id)
        except Exception:
            await interaction.followup.send("Could not fetch test from HRW.", ephemeral=True)
            return

        checks: list[str] = []
        issues: list[str] = []

        q_count = len(test.get("questions", []))
        if q_count > 0:
            checks.append(f"Questions added: {q_count}")
        else:
            issues.append("No questions added to the test!")

        if test.get("locked"):
            checks.append("Test is locked (private)")
        else:
            issues.append("Test is NOT locked — other workspace users can see/edit it")

        if test.get("draft"):
            issues.append("Test is still in DRAFT — candidates cannot access it")
        else:
            checks.append("Test is published (not draft)")

        duration = test.get("duration", 0)
        if duration > 0:
            checks.append(f"Duration set: {duration} minutes")
            if duration < 30:
                issues.append("Duration is very short (<30min) — consider adding buffer")
        else:
            issues.append("No duration set!")

        if test.get("start_time"):
            checks.append(f"Start time: {test['start_time']}")
        if test.get("end_time"):
            checks.append(f"End time: {test['end_time']}")

        sections = test.get("sections", [])
        if sections:
            checks.append(f"Sections: {len(sections)}")

        color = discord.Color.green() if not issues else discord.Color.red()
        embed = discord.Embed(
            title=f"Pre-Flight Check — {test.get('name', test_id)[:50]}",
            color=color,
        )

        if checks:
            embed.add_field(name="Passed", value="\n".join(f"- {c}" for c in checks), inline=False)
        if issues:
            embed.add_field(name="Issues Found", value="\n".join(f"- {i}" for i in issues), inline=False)

        embed.add_field(
            name="Reminder",
            value="Contests that reach end time CANNOT be reopened. Always add 15-30 min buffer.",
            inline=False,
        )
        embed.set_footer(text=f"Test ID: {test_id}")
        await interaction.followup.send(embed=embed, ephemeral=True)

    @tree.command(name="impact_report", description="Generate your personal impact summary (shareable)")
    async def impact_report_cmd(interaction: discord.Interaction) -> None:
        uid = interaction.user.id
        events = get_ambassador_events(uid)
        pts = get_ambassador_points(uid)
        profile = get_ambassador_profile(uid)
        achievements = get_ambassador_achievements(uid)

        total_participants = sum(e["participant_count"] for e in events) if events else 0
        merch_events = sum(1 for e in events if e.get("merch_eligible")) if events else 0
        contests = pts["contests_hosted"] if pts else 0
        tier = pts["tier_name"] if pts else "Apprentice Ambassador"
        points = pts["total_points"] if pts else 0
        badge = TIER_BADGES.get(tier, "🎖️")
        country = profile.get("country", "") if profile else ""
        college = profile.get("college_name", "") if profile else ""

        badge_display = " ".join(
            str(ACHIEVEMENT_DEFS[b]["emoji"]) for b in achievements if b in ACHIEVEMENT_DEFS
        )

        embed = discord.Embed(
            title=f"Impact Report — {interaction.user.display_name}",
            color=discord.Color.gold(),
        )
        embed.set_thumbnail(url=interaction.user.display_avatar.url)

        embed.description = (
            f"**{interaction.user.display_name}** | {badge} {tier}\n"
            f"{college}{(' | ' + country) if country else ''}\n\n"
            f"**{contests}** events hosted | **{total_participants}** students engaged\n"
            f"**{merch_events}** merch-tier events | **{points}** points earned"
        )

        if badge_display:
            embed.add_field(name="Achievements", value=badge_display, inline=False)

        embed.add_field(
            name="Share This!",
            value=(
                f"Copy for LinkedIn:\n"
                f"```\n"
                f"Proud to be a HackerRank Campus Crew Ambassador! "
                f"Hosted {contests} coding events engaging {total_participants} students. "
                f"Currently ranked as {tier}. "
                f"#HackerRankCampusCrew #CodingCommunity #TechLeadership\n"
                f"```"
            ),
            inline=False,
        )

        embed.set_footer(text="Generated by HackerRank Campus Crew Bot")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @tree.command(name="bulk_verify_emails", description="Bulk verify winner emails against HRW accounts")
    @app_commands.describe(
        csv_file="Contest CSV file with participant emails",
        event_name="Name of the event (for context)",
    )
    async def bulk_verify_emails_cmd(interaction: discord.Interaction, csv_file: discord.Attachment, event_name: str = "Event") -> None:
        await interaction.response.defer(thinking=True)

        try:
            raw = await csv_file.read()
            result = await run_full_verification(raw, event_name)

            embed = discord.Embed(title="Email Verification Results", color=discord.Color.green())
            embed.add_field(
                name="Summary",
                value=(
                    f"**Event:** {event_name}\n"
                    f"**Total Emails:** {result['total_participants']}\n"
                    f"**Valid (HRW Match):** {result['valid_emails']}\n"
                    f"**Invalid/Mismatched:** {result['invalid_emails']}\n\n"
                    f"**Can Submit to Sanskruti:** {'✅ YES' if result['can_submit_to_sanskruti'] else '❌ NO — Fix mismatches first'}"
                ),
                inline=False,
            )

            if result['warnings']:
                embed.add_field(
                    name="⚠️ Issues Found",
                    value="\n".join(f"- {w[:200]}" for w in result['warnings'][:10]),
                    inline=False,
                )
                if len(result['warnings']) > 10:
                    embed.add_field(
                        name="...",
                        value=f"...and {len(result['warnings']) - 10} more warnings",
                        inline=True,
                    )

            embed.set_footer(text="Do NOT submit mismatched emails — they will cause reward failures!")
            await interaction.followup.send(embed=embed)

        except Exception as e:
            log.exception("Email verification failed")
            await interaction.followup.send(
                f"Failed to verify emails: {str(e)[:200]}", ephemeral=True
            )
