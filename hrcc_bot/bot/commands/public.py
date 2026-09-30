"""Commands open to everyone, registered or not (see UNGATED_COMMANDS)."""
from __future__ import annotations

import discord
from discord import app_commands, ui
from hrcc_bot.core.db import (
    create_hrw_link,
    get_hrw_link,
    log_audit,
    resolve_region,
    upsert_ambassador_profile,
)
from hrcc_bot.bot.privacy_views import ConfirmDeleteView, build_export_file
from hrcc_bot.bot.commands._common import (
    SOPView,
    _certs_embed,
    _rewards_embed,
)


def register(tree: app_commands.CommandTree) -> None:
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

    @tree.command(name="my_data", description="Download or delete the data the bot stores about you")
    @app_commands.describe(action="Export a copy, or permanently delete it")
    @app_commands.choices(action=[
        app_commands.Choice(name="Export (download a JSON copy)", value="export"),
        app_commands.Choice(name="Delete (permanent)", value="delete"),
    ])
    async def my_data_cmd(interaction: discord.Interaction, action: app_commands.Choice[str]) -> None:
        if action.value == "export":
            await interaction.response.defer(ephemeral=True)
            file, rows = build_export_file(interaction.user.id)
            if file is None:
                await interaction.followup.send("The bot has no stored data about you.", ephemeral=True)
                return
            await interaction.followup.send(f"Here is everything stored about you ({rows} records).", file=file, ephemeral=True)
            return

        view = ConfirmDeleteView(requester_id=interaction.user.id, subject_id=interaction.user.id, subject_label="you")
        await interaction.response.send_message(
            "This permanently deletes your tickets, events, points, profile, HRW link and chat history. "
            "Audit entries are kept but anonymised. **This cannot be undone.**",
            view=view,
            ephemeral=True,
        )

    @tree.command(name="rules", description="Platform rules and restrictions")
    @app_commands.describe(platform="Which platform")
    @app_commands.choices(platform=[
        app_commands.Choice(name="HackerRank for Work (HRW)", value="hrw"),
        app_commands.Choice(name="HackerRank Community (HRC)", value="hrc"),
        app_commands.Choice(name="HackerRank SkillUp", value="skillup"),
    ])
    async def rules_cmd(interaction: discord.Interaction, platform: app_commands.Choice[str]) -> None:
        from hrcc_bot.pipeline.knowledge import get_platform_info
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

    class RegisterConfirmView(ui.View):
        def __init__(self, user_id: int, hrw_user: dict) -> None:
            super().__init__(timeout=120)
            self.user_id = user_id
            self.hrw_user = hrw_user

        @ui.button(label="Yes, that's me", style=discord.ButtonStyle.success)
        async def confirm(self, interaction: discord.Interaction, button: ui.Button) -> None:
            if interaction.user.id != self.user_id:
                await interaction.response.send_message("Not your verification.", ephemeral=True)
                return

            u = self.hrw_user
            hrw_id = str(u.get("id", ""))
            email = u.get("email", "")
            name = f"{u.get('firstname', '')} {u.get('lastname', '')}".strip()
            country = u.get("country", "")
            region = resolve_region(country) if country else ""

            create_hrw_link(discord_id=self.user_id, hrw_user_id=hrw_id, hrw_email=email, hrw_name=name)
            upsert_ambassador_profile(
                ambassador_id=self.user_id, ambassador_name=name,
                country=country, region=region,
            )
            log_audit(actor_id=self.user_id, actor_name=name, action="REGISTER", details=f"HRW: {email}")

            self.clear_items()
            await interaction.response.edit_message(
                content=(
                    f"**Registration complete!**\n\n"
                    f"**Name:** {name}\n"
                    f"**HRW Email:** {email}\n"
                    f"**Country:** {country or 'Not set'} | **Region:** {region or 'N/A'}\n\n"
                    f"You now have access to all ambassador commands.\n"
                    f"Run `/my_status` to see your dashboard, or `/set_profile` to complete your profile."
                ),
                view=self,
            )

        @ui.button(label="Not me", style=discord.ButtonStyle.danger)
        async def deny(self, interaction: discord.Interaction, button: ui.Button) -> None:
            self.clear_items()
            await interaction.response.edit_message(
                content="Verification cancelled. Please try `/register` again with the correct HRW email.",
                view=self,
            )

    class RegisterModal(ui.Modal, title="Ambassador Registration"):
        hrw_email_input = ui.TextInput(
            label="Your HackerRank for Work Email",
            placeholder="The email you registered with on HRW",
            required=True, max_length=200,
        )

        async def on_submit(self, interaction: discord.Interaction) -> None:
            await interaction.response.defer(ephemeral=True)

            email = self.hrw_email_input.value.strip()

            existing = get_hrw_link(interaction.user.id)
            if existing:
                await interaction.followup.send(
                    f"You're already registered as **{existing['hrw_name']}** ({existing['hrw_email']}).",
                    ephemeral=True,
                )
                return

            from hrcc_bot.services.hrw_api import find_hrw_user_by_email
            try:
                hrw_user = await find_hrw_user_by_email(email)
            except Exception:
                await interaction.followup.send(
                    "Could not connect to HRW API. Please try again later.",
                    ephemeral=True,
                )
                return

            if not hrw_user:
                await interaction.followup.send(
                    f"No HRW account found for `{email}`.\n\n"
                    f"**Check:**\n"
                    f"1. Are you using the email you registered with on HRW?\n"
                    f"2. Has your HRW account been activated?\n"
                    f"3. Contact the Technical Lead if your activation is pending.",
                    ephemeral=True,
                )
                return

            name = f"{hrw_user.get('firstname', '')} {hrw_user.get('lastname', '')}".strip()
            team_info = hrw_user.get("teams", [])
            team_str = f" (Team: {', '.join(str(t) for t in team_info[:2])})" if team_info else ""

            view = RegisterConfirmView(interaction.user.id, hrw_user)
            await interaction.followup.send(
                f"**Found HRW account:**\n"
                f"**Name:** {name}\n"
                f"**Email:** {email}\n"
                f"**Role:** {hrw_user.get('role', '?')}{team_str}\n\n"
                f"Is this you?",
                view=view,
                ephemeral=True,
            )

    @tree.command(name="register", description="Verify your HRW identity to unlock all bot commands")
    async def register_cmd(interaction: discord.Interaction) -> None:
        existing = get_hrw_link(interaction.user.id)
        if existing:
            await interaction.response.send_message(
                f"You're already registered as **{existing['hrw_name']}** ({existing['hrw_email']}).",
                ephemeral=True,
            )
            return
        await interaction.response.send_modal(RegisterModal())

    @tree.command(name="question_bank", description="Browse the HRW question library")
    @app_commands.describe(question_type="Filter by question type", page="Page number (20 per page)")
    @app_commands.choices(question_type=[
        app_commands.Choice(name="Code (DSA/Algorithms)", value="code"),
        app_commands.Choice(name="Multiple Choice (MCQ)", value="mcq"),
        app_commands.Choice(name="Full-Stack Projects", value="fullstack"),
        app_commands.Choice(name="All Types", value=""),
    ])
    async def question_bank_cmd(
        interaction: discord.Interaction,
        question_type: app_commands.Choice[str] = None,
        page: int = 1,
    ) -> None:
        await interaction.response.defer()

        from hrcc_bot.services.hrw_api import get_questions
        q_type = question_type.value if question_type else ""
        offset = (max(page, 1) - 1) * 20

        try:
            data = await get_questions(limit=20, offset=offset, q_type=q_type)
        except Exception:
            await interaction.followup.send("Could not connect to HRW API.")
            return

        questions = data.get("data", [])
        total = data.get("total", 0)

        if not questions:
            await interaction.followup.send("No questions found for this filter.")
            return

        type_label = question_type.name if question_type and question_type.value else "All"
        embed = discord.Embed(
            title=f"HRW Question Bank — {type_label}",
            color=discord.Color.purple(),
        )

        for q in questions[:10]:
            name = q.get("name", "Untitled")[:45]
            qtype = q.get("type", "?")
            score = q.get("max_score", "?")
            duration = q.get("recommended_duration", "?")
            embed.add_field(
                name=f"{name}",
                value=f"Type: `{qtype}` | Score: {score} | ~{duration}min",
                inline=False,
            )

        embed.set_footer(text=f"Page {page} | {total} total questions | /question_bank page:{page+1}")
        await interaction.followup.send(embed=embed)
