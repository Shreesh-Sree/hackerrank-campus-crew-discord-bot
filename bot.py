from __future__ import annotations

import asyncio
import logging
import signal
import sys

import discord
from discord.ext import commands

from src.config import settings
from src.csv_validator import build_canva_file, build_summary_embed, parse_contest_csv
from src.db import close_db, init_db
from src.escalation_views import PersistentTicketView
from src.graph import PipelineState, get_pipeline
from src.knowledge import load_knowledge, load_references
from src.slash_commands import register_commands

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("hrcc.bot")

intents = discord.Intents.default()
intents.message_content = True
intents.dm_messages = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)


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

    log.info(
        "HRCC Bot online as %s (id=%s)",
        bot.user,
        bot.user.id if bot.user else "?",
    )


@bot.event
async def on_message(message: discord.Message) -> None:
    if message.author == bot.user:
        return
    if message.author.bot:
        return

    if message.attachments:
        for attachment in message.attachments:
            if attachment.filename.lower().endswith((".csv", ".xlsx")):
                await _handle_csv_upload(message, attachment)
                return

    await bot.process_commands(message)

    is_dm = isinstance(message.channel, discord.DMChannel)
    is_mention = bot.user is not None and bot.user.mentioned_in(message)

    state: PipelineState = {
        "message_content": message.content,
        "author_name": str(message.author),
        "author_id": message.author.id,
        "channel_id": message.channel.id,
        "is_dm": is_dm,
        "is_mention": is_mention,
        "is_bot": False,
    }

    pipeline = get_pipeline()

    try:
        result = await pipeline.ainvoke(state)
    except Exception:
        log.exception("Pipeline error for message from %s", message.author)
        return

    if result.get("verdict") == "DISMISS":
        return

    chunks: list[str] = result.get("final_chunks", [])
    if not chunks:
        return

    for i, chunk in enumerate(chunks):
        if i == 0:
            await message.reply(chunk, mention_author=False)
        else:
            await message.channel.send(chunk)


async def _handle_csv_upload(
    message: discord.Message, attachment: discord.Attachment
) -> None:
    try:
        raw = await attachment.read()
    except discord.HTTPException:
        await message.reply("Could not download the attachment.", mention_author=False)
        return

    result = parse_contest_csv(raw, event_name=attachment.filename.rsplit(".", 1)[0])
    if result.warnings and result.active_participants == 0:
        await message.reply(
            "Could not parse the CSV. " + " ".join(result.warnings),
            mention_author=False,
        )
        return

    embed = build_summary_embed(result)
    canva_file = build_canva_file(result)
    await message.reply(embed=embed, file=canva_file, mention_author=False)


async def _shutdown(sig: signal.Signals) -> None:
    log.info("Received %s, shutting down...", sig.name)
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
        close_db()
        loop.run_until_complete(bot.close())
        loop.close()


if __name__ == "__main__":
    main()
