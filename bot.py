from __future__ import annotations

import asyncio
import logging
import signal
import sys

import discord

from src.config import settings
from src.graph import PipelineState, get_pipeline
from src.knowledge import load_knowledge, load_references

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("hrcc.bot")

intents = discord.Intents.default()
intents.message_content = True
intents.dm_messages = True

client = discord.Client(intents=intents)


@client.event
async def on_ready() -> None:
    load_knowledge()
    load_references()
    log.info("HRCC Bot online as %s (id=%s)", client.user, client.user.id if client.user else "?")


@client.event
async def on_message(message: discord.Message) -> None:
    if message.author == client.user:
        return

    is_dm = isinstance(message.channel, discord.DMChannel)
    is_mention = client.user is not None and client.user.mentioned_in(message)
    is_bot = message.author.bot

    state: PipelineState = {
        "message_content": message.content,
        "author_name": str(message.author),
        "author_id": message.author.id,
        "channel_id": message.channel.id,
        "is_dm": is_dm,
        "is_mention": is_mention,
        "is_bot": is_bot,
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


async def _shutdown(sig: signal.Signals) -> None:
    log.info("Received %s, shutting down...", sig.name)
    await client.close()


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
        loop.run_until_complete(client.start(token))
    except KeyboardInterrupt:
        log.info("KeyboardInterrupt received")
    finally:
        loop.run_until_complete(client.close())
        loop.close()


if __name__ == "__main__":
    main()
