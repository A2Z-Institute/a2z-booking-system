#!/usr/bin/env python3
"""Relink appointments that belong to duplicate client records.

This is deliberately conservative.  A client is only treated as a duplicate
when both the normalized full name and normalized primary phone number match.
It keeps every client record, instructor, booking slot, break and appointment;
only the appointment's client reference is made consistent.

Run without --apply first.  A verified database backup is made before changes.
"""

from __future__ import annotations

import argparse
import os
import re
import sqlite3
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path


def identity_key(name: object, phone: object) -> tuple[str, str] | None:
    normalized_name = " ".join(str(name or "").casefold().split())
    normalized_phone = re.sub(r"\D", "", str(phone or ""))
    return (normalized_name, normalized_phone) if normalized_name and normalized_phone else None


def backup_database(database: Path) -> Path:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    destination = database.parent / "backups" / f"a2z-before-client-relink-{stamp}.db"
    destination.parent.mkdir(parents=True, exist_ok=True)
    source = sqlite3.connect(database)
    target = sqlite3.connect(destination)
    try:
        source.backup(target)
    finally:
        target.close()
        source.close()
    return destination


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--database",
        default=os.getenv("A2Z_DATABASE", "/data/a2z_booking.db"),
        help="SQLite database path (defaults to A2Z_DATABASE or /data/a2z_booking.db)",
    )
    parser.add_argument("--apply", action="store_true", help="Make the relinking changes")
    args = parser.parse_args()
    database = Path(args.database).expanduser()
    if not database.is_file():
        print(f"Database not found: {database}", file=sys.stderr)
        return 2

    conn = sqlite3.connect(database)
    conn.row_factory = sqlite3.Row
    try:
        clients = conn.execute(
            "SELECT id, full_name, phone FROM users WHERE role = 'student' ORDER BY id"
        ).fetchall()
        groups: dict[tuple[str, str], list[sqlite3.Row]] = defaultdict(list)
        for client in clients:
            key = identity_key(client["full_name"], client["phone"])
            if key:
                groups[key].append(client)

        mappings: dict[int, int] = {}
        for matches in groups.values():
            if len(matches) < 2:
                continue
            canonical_id = min(row["id"] for row in matches)
            for row in matches:
                if row["id"] != canonical_id:
                    mappings[row["id"]] = canonical_id

        affected = 0
        for duplicate_id in mappings:
            affected += conn.execute(
                "SELECT count(*) FROM bookings WHERE student_user_id = ?", (duplicate_id,)
            ).fetchone()[0]

        print(f"Duplicate client records detected: {len(mappings)}")
        print(f"Appointments that would be relinked: {affected}")
        if not args.apply:
            print("Dry run only. Re-run with --apply to relink the appointments.")
            return 0
        if not mappings:
            print("Nothing to change.")
            return 0

        backup = backup_database(database)
        conn.execute("BEGIN IMMEDIATE")
        for duplicate_id, canonical_id in mappings.items():
            canonical = conn.execute(
                "SELECT full_name, COALESCE(phone, '') AS phone FROM users WHERE id = ?",
                (canonical_id,),
            ).fetchone()
            conn.execute(
                """
                UPDATE bookings
                SET student_user_id = ?, student_name = ?, mobile_number = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE student_user_id = ?
                """,
                (canonical_id, canonical["full_name"], canonical["phone"], duplicate_id),
            )
        conn.commit()
        integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
        if integrity != "ok":
            raise RuntimeError(f"Database integrity check failed: {integrity}")
        print(f"Relinked {affected} appointments. Backup created: {backup}")
        return 0
    except Exception as exc:
        conn.rollback()
        print(f"No changes were kept: {exc}", file=sys.stderr)
        return 1
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
