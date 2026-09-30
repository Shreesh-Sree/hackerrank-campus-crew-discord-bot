"""Copy the SQLite store into PostgreSQL after a failover (or for first-time Postgres adoption).

Usage:
    python -m hrcc_bot.core.migrate_to_postgres --dry-run   # report only, nothing written
    python -m hrcc_bot.core.migrate_to_postgres             # copy, then clear the failover marker
    python -m hrcc_bot.core.migrate_to_postgres --force     # clear the marker even if rows conflicted

Rows are inserted with their original ids; rows whose primary/unique key already
exists in Postgres are skipped and reported. Restart the bot afterwards so it
switches back to Postgres.
"""
from __future__ import annotations

import argparse
import re
import sqlite3
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from hrcc_bot.config import settings
from hrcc_bot.core import db


@dataclass
class TableReport:
    rows: int = 0
    inserted: int = 0

    @property
    def skipped(self) -> int:
        return self.rows - self.inserted


def _table_order() -> list[str]:
    return re.findall(r"CREATE TABLE IF NOT EXISTS (\w+)", db._SQLITE_SCHEMA)


def ensure_pg_schema(conn: Any) -> None:
    for stmt in db._PG_SCHEMA.strip().split(";"):
        if stmt.strip():
            conn.execute(stmt)
    for table, col, typedef in db._SQLITE_MIGRATIONS:
        pg_type = typedef.replace("INTEGER", "BIGINT")
        conn.execute(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {col} {pg_type}")


def migrate(sqlite_path: Path, pg_url: str, *, dry_run: bool = False) -> dict[str, TableReport]:
    import psycopg

    src = sqlite3.connect(f"file:{sqlite_path}?mode=ro", uri=True)
    src.row_factory = sqlite3.Row
    report: dict[str, TableReport] = {}
    with psycopg.connect(pg_url, connect_timeout=settings.pg_connect_timeout, autocommit=False) as dst:
        ensure_pg_schema(dst)
        for table in _table_order():
            src_cols = [r[1] for r in src.execute(f"PRAGMA table_info({table})")]
            if not src_cols:
                continue
            dst_cols = {
                r[0] for r in dst.execute(
                    "SELECT column_name FROM information_schema.columns WHERE table_name = %s", (table,)
                ).fetchall()
            }
            cols = [c for c in src_cols if c in dst_cols]
            rows = src.execute(f"SELECT {', '.join(cols)} FROM {table}").fetchall()
            tr = TableReport(rows=len(rows))
            placeholders = ", ".join(["%s"] * len(cols))
            sql = f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({placeholders}) ON CONFLICT DO NOTHING"
            for row in rows:
                tr.inserted += dst.execute(sql, tuple(row)).rowcount
            if "id" in cols:
                seq = dst.execute("SELECT pg_get_serial_sequence(%s, 'id')", (table,)).fetchone()[0]
                if seq:
                    dst.execute(f"SELECT setval(%s, GREATEST((SELECT COALESCE(MAX(id), 0) FROM {table}), 1))", (seq,))
            report[table] = tr
        if dry_run:
            dst.rollback()
        else:
            dst.commit()
    src.close()
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dry-run", action="store_true", help="report what would be copied; write nothing")
    parser.add_argument("--force", action="store_true", help="clear the failover marker even if rows were skipped")
    args = parser.parse_args(argv)

    if not db._is_postgres():
        print("DATABASE_URL is not a PostgreSQL URL; nothing to migrate to.", file=sys.stderr)
        return 1
    if not db._SQLITE_PATH.exists():
        print(f"No SQLite store at {db._SQLITE_PATH}.", file=sys.stderr)
        return 1

    report = migrate(db._SQLITE_PATH, settings.database_url, dry_run=args.dry_run)
    skipped = 0
    for table, tr in report.items():
        skipped += tr.skipped
        flag = f"  ({tr.skipped} skipped: key already in Postgres)" if tr.skipped else ""
        print(f"{table:22} {tr.inserted:6} / {tr.rows:<6} copied{flag}")

    if args.dry_run:
        print("\nDry run: nothing was written.")
        return 0
    if skipped and not args.force:
        print(f"\n{skipped} row(s) conflicted with existing Postgres data. Review them, then rerun with --force "
              "to keep Postgres's versions and clear the failover marker.", file=sys.stderr)
        return 2
    db.clear_failover_marker()
    print("\nMigration complete; failover marker cleared. Restart the bot to switch to PostgreSQL.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
