"""Create a consistent local SQLite backup before the scheduler starts."""

from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

from database import database_path


def create_backup():
    load_dotenv()
    source = database_path()
    if not source.exists():
        return None
    backup_dir = Path(__file__).resolve().parent / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    target = backup_dir / f"a2z-booking-{datetime.now():%Y%m%d-%H%M%S}.db"
    source_conn = sqlite3.connect(source)
    target_conn = sqlite3.connect(target)
    try:
        source_conn.backup(target_conn)
    finally:
        target_conn.close()
        source_conn.close()
    return target


if __name__ == "__main__":
    result = create_backup()
    if result:
        print(f"Database backup: {result}")
