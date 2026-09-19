from __future__ import annotations

import asyncio
import logging
import signal
import sys
import time
from collections import defaultdict

import discord
from discord.ext import commands, tasks

from src.config import settings
from src.context import memory
from src.cert_generator import build_cert_preview_file
from src.csv_validator import build_canva_file, build_summary_embed, parse_contest_csv
from src.db import close_db, init_db, record_event_submission
from src.escalation_views import PersistentTicketView
from src.graph import PipelineState, get_pipeline
from src.knowledge import check_and_reload, load_knowledge, load_references
from src.llm_client import get_llm
from src.scheduler import setup_scheduler
from src.slash_commands import register_commands

logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("hrcc.bot")

intents = discord.Intents.default()
intents.message_content = True
intents.dm_messages = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)

_rate_buckets: dict[int, list[float]] = defaultdict(list)
_user_locks: dict[int, asyncio.Lock] = defaultdict(asyncio.Lock)


def _check_rate_limit(user_id: int) -> bool:
    now = time.monotonic()
    bucket = _rate_buckets[user_id]
    bucket[:] = [t for t in bucket if now - t < 60.0]
    if len(bucket) >= settings.rate_limit_per_minute:
        return False
    bucket.append(now)
    return True


# ── Lifecycle ─────────────────────────────────────────────────────────────


@bot.event
async def on_ready() -> None:
    init_db()
    load_knowledge()
    load_references()

    bot.add_view(PersistentTicketView())

    register_commands(bot.tree)
    try:
        synced = await bot.tree.sync()
        log.info("Synced %d slash commands", len(synced))
    except Exception:
        log.exception("Failed to sync slash commands")

    if not health_loop.is_running():
        health_loop.start()
    if not knowledge_reload_loop.is_running():
        knowledge_reload_loop.start()

    await setup_scheduler(bot)

    log.info(
        "HRCC Bot online as %s (id=%s) | guilds=%d",
        bot.user,
        bot.user.id if bot.user else "?",
        len(bot.guilds),
    )


# ── Background tasks ─────────────────────────────────────────────────────


@tasks.loop(seconds=settings.health_check_interval)
async def health_loop() -> None:
    try:
        llm = get_llm()
        result = await llm.ainvoke([
            {"role": "user", "content": "ping"},
        ])
        log.debug("Health probe OK: %s", result.content[:20] if result.content else "empty")
    except Exception:
        log.warning("vLLM health probe failed — inference engine may be down")


@health_loop.before_loop
async def _wait_for_bot() -> None:
    await bot.wait_until_ready()


@tasks.loop(seconds=settings.knowledge_reload_interval)
async def knowledge_reload_loop() -> None:
    reloaded = check_and_reload()
    if reloaded:
        log.info("Knowledge base hot-reloaded successfully")


@knowledge_reload_loop.before_loop
async def _wait_for_bot_kr() -> None:
    await bot.wait_until_ready()


# ── Message handling ──────────────────────────────────────────────────────


@bot.event
async def on_message(message: discord.Message) -> None:
    if message.author == bot.user:
        return
    if message.author.bot:
        return

    # CSV attachment auto-detection
    if message.attachments:
        for attachment in message.attachments:
            if attachment.filename.lower().endswith((".csv", ".xlsx")):
                await _handle_csv_upload(message, attachment)
                return

    # Process prefix commands first
    await bot.process_commands(message)

    # Per-user rate limit
    if not _check_rate_limit(message.author.id):
        return

    is_dm = isinstance(message.channel, discord.DMChannel)
    is_mention = bot.user is not None and bot.user.mentioned_in(message)

    history = memory.get_history(message.author.id)

    state: PipelineState = {
        "message_content": message.content,
        "author_name": str(message.author),
        "author_id": message.author.id,
        "channel_id": message.channel.id,
        "is_dm": is_dm,
        "is_mention": is_mention,
        "is_bot": False,
        "conversation_history": history,
    }

    pipeline = get_pipeline()
    lock = _user_locks[message.author.id]

    async with lock:
        # Run sentinel classification first WITHOUT typing indicator
        from src.graph import sentinel_node
        sentinel_result = await sentinel_node(state)
        if sentinel_result.get("verdict") == "DISMISS":
            return

        # Only show typing for messages we'll actually respond to
        try:
            async with message.channel.typing():
                state.update(sentinel_result)  # type: ignore[arg-type]
                result = await pipeline.ainvoke(state)
        except Exception:
            log.exception("Pipeline error for message from %s", message.author)
            return

    if result.get("verdict") == "DISMISS":
        return

    chunks: list[str] = result.get("final_chunks", [])
    if not chunks:
        return

    # Store conversation turns
    memory.add_user_message(message.author.id, message.content)
    memory.add_assistant_message(message.author.id, chunks[0])

    for i, chunk in enumerate(chunks):
        try:
            if i == 0:
                await message.reply(chunk, mention_author=False)
            else:
                await message.channel.send(chunk)
        except discord.HTTPException:
            log.exception("Failed to send chunk %d for message %s", i, message.id)
            break


async def _handle_csv_upload(
    message: discord.Message, attachment: discord.Attachment
) -> None:
    async with message.channel.typing():
        try:
            raw = await attachment.read()
        except discord.HTTPException:
            await message.reply("Could not download the attachment.", mention_author=False)
            return

        event_name = attachment.filename.rsplit(".", 1)[0]
        result = parse_contest_csv(raw, event_name=event_name, filename=attachment.filename)

        if result.warnings and result.active_participants == 0:
            await message.reply(
                "Could not parse the CSV. " + " ".join(result.warnings),
                mention_author=False,
            )
            return

        embed = build_summary_embed(result)
        canva_file = build_canva_file(result)

        files = [canva_file]
        if result.winners:
            w = result.winners[0]
            try:
                cert_preview = build_cert_preview_file(
                    name=w["name"],
                    college_name=result.college_name,
                    event_name=result.event_name,
                    rank=w.get("rank", 1),
                    date=result.canva_csv.split("\n")[1].split(",")[4] if result.canva_csv else "",
                )
                files.append(cert_preview)
            except Exception:
                log.warning("Certificate preview generation failed, skipping")

        try:
            await message.reply(embed=embed, files=files, mention_author=False)
        except discord.HTTPException:
            log.exception("Failed to send CSV validation result")
            await message.reply(
                "Processed the CSV but could not send the result. Please try again.",
                mention_author=False,
            )
            return

        # Record the event submission in the database
        record_event_submission(
            ambassador_id=message.author.id,
            ambassador_name=str(message.author),
            event_name=event_name,
            participant_count=result.active_participants,
            reward_tier=result.reward_tier,
            merch_eligible=result.merch_eligible,
            csv_sha256=result.csv_sha256,
        )


# ── Error handlers ────────────────────────────────────────────────────────


@bot.event
async def on_error(event: str, *args: object, **kwargs: object) -> None:
    log.exception("Unhandled error in event %s", event)


@bot.tree.error
async def on_app_command_error(
    interaction: discord.Interaction, error: discord.app_commands.AppCommandError
) -> None:
    log.exception("Slash command error: %s", error)
    try:
        if interaction.response.is_done():
            await interaction.followup.send(
                "An error occurred while processing your command. Please try again.",
                ephemeral=True,
            )
        else:
            await interaction.response.send_message(
                "An error occurred while processing your command. Please try again.",
                ephemeral=True,
            )
    except discord.HTTPException:
        pass


# ── Shutdown ──────────────────────────────────────────────────────────────


async def _shutdown(sig: signal.Signals) -> None:
    log.info("Received %s, shutting down...", sig.name)
    health_loop.cancel()
    knowledge_reload_loop.cancel()
    close_db()
    await bot.close()


def main() -> None:
    token = settings.discord_bot_token
    if not token:
        log.critical("DISCORD_BOT_TOKEN is not set")
        sys.exit(1)

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, lambda s=sig: asyncio.ensure_future(_shutdown(s)))

    try:
        loop.run_until_complete(bot.start(token))
    except KeyboardInterrupt:
        log.info("KeyboardInterrupt received")
    finally:
        health_loop.cancel()
        knowledge_reload_loop.cancel()
        close_db()
        if not bot.is_closed():
            loop.run_until_complete(bot.close())
        loop.close()


if __name__ == "__main__":
    main()
