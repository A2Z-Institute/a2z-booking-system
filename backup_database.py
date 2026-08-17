"""Create a consistent local SQLite backup before the scheduler starts."""

from __future__ import annotations

import os
import sqlite3
import threading
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

from database import database_path


def backup_directory() -> Path:
    configured = os.environ.get("A2Z_BACKUP_DIR")
    if configured:
        return Path(configured).resolve()
    return Path(__file__).resolve().parent / "backups"


def verify_database(path: Path) -> None:
    """Raise before deployment/retention if a database is not fully readable."""
    connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=30)
    try:
        result = connection.execute("PRAGMA integrity_check").fetchone()[0]
    finally:
        connection.close()
    if result != "ok":
        raise sqlite3.DatabaseError(f"Database integrity check failed: {result}")


def create_backup(*, once_per_day=False, retain=30):
    load_dotenv()
    source = database_path()
    if not source.exists():
        return None
    verify_database(source)
    backup_dir = backup_directory()
    backup_dir.mkdir(parents=True, exist_ok=True)
    today_prefix = f"a2z-booking-{datetime.now():%Y%m%d}-"
    if once_per_day:
        for existing in backup_dir.glob(f"{today_prefix}*.db"):
            try:
                verify_database(existing)
                return None
            except (OSError, sqlite3.Error):
                # Keep the damaged file for diagnosis and create a valid
                # replacement rather than treating its name as success.
                continue
    target = backup_dir / f"a2z-booking-{datetime.now():%Y%m%d-%H%M%S}.db"
    source_conn = sqlite3.connect(source)
    target_conn = sqlite3.connect(target)
    try:
        source_conn.backup(target_conn)
    finally:
        target_conn.close()
        source_conn.close()
    verify_database(target)
    backups = sorted(backup_dir.glob("a2z-booking-*.db"), reverse=True)
    for expired in backups[max(1, int(retain)):]:
        expired.unlink(missing_ok=True)
    return target


def run_backup_worker(stop_event=None, interval_seconds=3600):
    """Keep one verified backup per day while the production process is alive."""
    stop_event = stop_event or threading.Event()
    while not stop_event.is_set():
        try:
            create_backup(
                once_per_day=True,
                retain=int(os.environ.get("A2Z_BACKUP_RETENTION", "30")),
            )
        except (OSError, sqlite3.Error) as exc:
            # Keep the application available; the next health check exposes a
            # damaged live database and the worker retries on the next cycle.
            print(f"A2Z backup warning: {exc}", flush=True)
        stop_event.wait(max(300, int(interval_seconds)))


if __name__ == "__main__":
    result = create_backup(
        once_per_day=os.environ.get("A2Z_BACKUP_ONCE_DAILY", "0") == "1",
        retain=int(os.environ.get("A2Z_BACKUP_RETENTION", "30")),
    )
    if result:
        print(f"Database backup: {result}")
