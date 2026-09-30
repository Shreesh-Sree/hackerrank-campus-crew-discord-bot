import os

# hrcc_bot.config builds Settings at import time and DISCORD_BOT_TOKEN is required.
# Environment variables take precedence over the repo's .env, so pin anything
# that would otherwise leak production config (live DB, open gate) into tests.
os.environ.setdefault("DISCORD_BOT_TOKEN", "test-token")
os.environ["DATABASE_URL"] = ""
os.environ["ALLOW_ALL_USERS"] = "false"
