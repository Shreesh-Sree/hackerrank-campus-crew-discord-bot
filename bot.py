"""Compatibility launcher for systemd units that still run ``python bot.py``.

Reinstall deploy/hrcc-bot.service (ExecStart: python -m hrcc_bot) and delete this file.
"""
from hrcc_bot.app import main

if __name__ == "__main__":
    main()
