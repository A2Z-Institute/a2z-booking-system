"""Create and verify a backup of the configured scheduling database."""

from __future__ import annotations

import os
import shutil
import sqlite3
import subprocess
import threading
from datetime import datetime
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit

from dotenv import load_dotenv

from database import database_path, postgres_url


class BackupError(RuntimeError):
    """Raised when a database backup cannot be created or verified."""


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


def verify_postgres_backup(path: Path) -> None:
    """Verify that pg_restore can read the complete custom-format archive."""
    pg_restore = shutil.which("pg_restore")
    if not pg_restore:
        raise BackupError("pg_restore is not installed in the application container.")
    try:
        result = subprocess.run(
            [pg_restore, "--list", str(path)],
            capture_output=True,
            text=True,
            check=False,
            timeout=120,
        )
    except subprocess.TimeoutExpired as exc:
        raise BackupError("PostgreSQL backup verification timed out.") from exc
    if result.returncode:
        message = (result.stderr or result.stdout or "unknown pg_restore error").strip()
        raise BackupError(f"PostgreSQL backup verification failed: {message}")


def verify_backup(path: Path) -> None:
    if path.suffix == ".dump":
        verify_postgres_backup(path)
    else:
        verify_database(path)


def _remove_expired_backups(backup_dir: Path, pattern: str, retain: int) -> None:
    backups = sorted(backup_dir.glob(pattern), reverse=True)
    for expired in backups[max(1, int(retain)):]:
        expired.unlink(missing_ok=True)


def _postgres_environment(database_url: str) -> dict[str, str]:
    """Build libpq variables without exposing the password in process args."""
    parsed = urlsplit(database_url)
    if parsed.scheme not in {"postgres", "postgresql"} or not parsed.hostname:
        raise BackupError("A2Z_POSTGRES_URL is not a valid PostgreSQL URL.")
    database_name = unquote(parsed.path.lstrip("/"))
    if not database_name:
        raise BackupError("A2Z_POSTGRES_URL does not include a database name.")
    environment = os.environ.copy()
    environment.update(
        {
            "PGHOST": parsed.hostname,
            "PGPORT": str(parsed.port or 5432),
            "PGDATABASE": database_name,
        }
    )
    if parsed.username:
        environment["PGUSER"] = unquote(parsed.username)
    if parsed.password:
        environment["PGPASSWORD"] = unquote(parsed.password)
    supported_options = {
        "sslmode": "PGSSLMODE",
        "sslrootcert": "PGSSLROOTCERT",
        "sslcert": "PGSSLCERT",
        "sslkey": "PGSSLKEY",
        "sslpassword": "PGSSLPASSWORD",
        "target_session_attrs": "PGTARGETSESSIONATTRS",
    }
    query = parse_qs(parsed.query, keep_blank_values=False)
    for option, variable in supported_options.items():
        if query.get(option):
            environment[variable] = query[option][-1]
    return environment


def _create_postgres_backup(*, once_per_day: bool, retain: int):
    database_url = postgres_url()
    if not database_url:
        raise BackupError("A2Z_POSTGRES_URL is not configured.")
    pg_dump = shutil.which("pg_dump")
    if not pg_dump:
        raise BackupError("pg_dump is not installed in the application container.")

    backup_dir = backup_directory()
    backup_dir.mkdir(parents=True, exist_ok=True)
    today_prefix = f"a2z-booking-{datetime.now():%Y%m%d}-"
    if once_per_day:
        for existing in backup_dir.glob(f"{today_prefix}*.dump"):
            try:
                verify_postgres_backup(existing)
                return None
            except (OSError, BackupError):
                # Retain the damaged archive for diagnosis and create a valid
                # replacement rather than treating its filename as success.
                continue

    target = backup_dir / f"a2z-booking-{datetime.now():%Y%m%d-%H%M%S}.dump"
    temporary = target.with_suffix(".dump.partial")
    try:
        result = subprocess.run(
            [
                pg_dump,
                "--format=custom",
                "--no-owner",
                "--no-privileges",
                "--no-password",
                "--file",
                str(temporary),
            ],
            env=_postgres_environment(database_url),
            capture_output=True,
            text=True,
            check=False,
            timeout=1800,
        )
    except subprocess.TimeoutExpired as exc:
        temporary.unlink(missing_ok=True)
        raise BackupError("PostgreSQL backup timed out after 30 minutes.") from exc
    if result.returncode:
        temporary.unlink(missing_ok=True)
        message = (result.stderr or result.stdout or "unknown pg_dump error").strip()
        raise BackupError(f"PostgreSQL backup failed: {message}")
    try:
        verify_postgres_backup(temporary)
        temporary.replace(target)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    _remove_expired_backups(backup_dir, "a2z-booking-*.dump", retain)
    return target


def create_backup(*, once_per_day=False, retain=30):
    load_dotenv()
    if postgres_url():
        return _create_postgres_backup(
            once_per_day=bool(once_per_day), retain=int(retain)
        )
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
    _remove_expired_backups(backup_dir, "a2z-booking-*.db", retain)
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
        except (OSError, sqlite3.Error, BackupError) as exc:
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
