"""Create a consistent local SQLite backup before the scheduler starts."""

from __future__ import annotations

import os
import sqlite3
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

from database import database_path


def backup_directory() -> Path:
    configured = os.environ.get("A2Z_BACKUP_DIR")
    if configured:
        return Path(configured).resolve()
    return Path(__file__).resolve().parent / "backups"


def create_backup(*, once_per_day=False, retain=30):
    load_dotenv()
    source = database_path()
    if not source.exists():
        return None
    backup_dir = backup_directory()
    backup_dir.mkdir(parents=True, exist_ok=True)
    today_prefix = f"a2z-booking-{datetime.now():%Y%m%d}-"
    if once_per_day and any(backup_dir.glob(f"{today_prefix}*.db")):
        return None
    target = backup_dir / f"a2z-booking-{datetime.now():%Y%m%d-%H%M%S}.db"
    source_conn = sqlite3.connect(source)
    target_conn = sqlite3.connect(target)
    try:
        source_conn.backup(target_conn)
    finally:
        target_conn.close()
        source_conn.close()
    backups = sorted(backup_dir.glob("a2z-booking-*.db"), reverse=True)
    for expired in backups[max(1, int(retain)):]:
        expired.unlink(missing_ok=True)
    return target


if __name__ == "__main__":
    result = create_backup(
        once_per_day=os.environ.get("A2Z_BACKUP_ONCE_DAILY", "0") == "1",
        retain=int(os.environ.get("A2Z_BACKUP_RETENTION", "30")),
    )
    if result:
        print(f"Database backup: {result}")
