#!/usr/bin/env python3
"""Safely consolidate two A2Z instructor records.

Use --find first to list the duplicate instructor ids.  Then select the record
that should remain with --target-id and the duplicate record with --source-id.
All related appointments, booking slots, breaks, availability and assignments
are moved to the retained record.  The duplicate is deactivated, not deleted,
so audit history remains intact.
"""

from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from datetime import datetime
from pathlib import Path


def backup_database(database: Path) -> Path:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    destination = database.parent / "backups" / f"a2z-before-instructor-merge-{stamp}.db"
    destination.parent.mkdir(parents=True, exist_ok=True)
    source = sqlite3.connect(database)
    target = sqlite3.connect(destination)
    try:
        source.backup(target)
    finally:
        target.close()
        source.close()
    return destination


def counts(conn: sqlite3.Connection, instructor_id: int) -> dict[str, int]:
    tables = {
        "appointments": "bookings",
        "booking_slots": "booking_slots",
        "breaks_and_busy_time": "instructor_time_off",
        "weekly_availability": "instructor_weekly_availability",
        "student_assignments": "student_instructor_assignments",
        "service_permissions": "service_instructors",
    }
    return {
        label: conn.execute(
            f"SELECT count(*) FROM {table} WHERE instructor_id = ?", (instructor_id,)
        ).fetchone()[0]
        for label, table in tables.items()
    }


def list_matches(conn: sqlite3.Connection, name: str) -> int:
    rows = conn.execute(
        """
        SELECT i.id, i.name, b.name AS branch_name, i.is_active,
               count(DISTINCT ap.id) AS appointment_count,
               count(DISTINCT sl.id) AS slot_count
        FROM instructors i
        JOIN branches b ON b.id = i.branch_id
        LEFT JOIN bookings ap ON ap.instructor_id = i.id
        LEFT JOIN booking_slots sl ON sl.instructor_id = i.id
        WHERE lower(i.name) LIKE lower(?)
        GROUP BY i.id
        ORDER BY i.is_active DESC, lower(i.name), i.id
        """,
        (f"%{name.strip()}%",),
    ).fetchall()
    if not rows:
        print("No instructor matches found.")
        return 1
    print("id | instructor | branch | active | appointments | booking slots")
    for row in rows:
        print(
            f"{row['id']} | {row['name']} | {row['branch_name']} | "
            f"{row['is_active']} | {row['appointment_count']} | {row['slot_count']}"
        )
    return 0


def overlapping_approved_count(conn: sqlite3.Connection, source_id: int, target_id: int) -> int:
    return conn.execute(
        """
        SELECT count(*)
        FROM bookings source
        JOIN bookings target
          ON target.instructor_id = ?
         AND target.id != source.id
         AND target.target_date = source.target_date
         AND target.validation_status = 'Approved'
         AND source.start_time < target.end_time
         AND source.end_time > target.start_time
        WHERE source.instructor_id = ?
          AND source.validation_status = 'Approved'
        """,
        (target_id, source_id),
    ).fetchone()[0]


def merge_assignments(conn: sqlite3.Connection, source_id: int, target_id: int) -> None:
    rows = conn.execute(
        """
        SELECT student_user_id, assigned_by, is_active, assigned_at, ended_at
        FROM student_instructor_assignments WHERE instructor_id = ?
        """,
        (source_id,),
    ).fetchall()
    for row in rows:
        existing = conn.execute(
            """
            SELECT id, is_active FROM student_instructor_assignments
            WHERE student_user_id = ? AND instructor_id = ?
            """,
            (row["student_user_id"], target_id),
        ).fetchone()
        if existing:
            if row["is_active"] and not existing["is_active"]:
                conn.execute(
                    """
                    UPDATE student_instructor_assignments
                    SET is_active = 1, ended_at = NULL, assigned_by = ?
                    WHERE id = ?
                    """,
                    (row["assigned_by"], existing["id"]),
                )
        else:
            conn.execute(
                """
                INSERT INTO student_instructor_assignments
                    (student_user_id, instructor_id, assigned_by, is_active,
                     assigned_at, ended_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    row["student_user_id"], target_id, row["assigned_by"],
                    row["is_active"], row["assigned_at"], row["ended_at"],
                ),
            )
    conn.execute(
        "DELETE FROM student_instructor_assignments WHERE instructor_id = ?",
        (source_id,),
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", default=os.getenv("A2Z_DATABASE", "/data/a2z_booking.db"))
    parser.add_argument("--find", help="Find instructor records by name")
    parser.add_argument("--source-id", type=int, help="Duplicate instructor id to consolidate")
    parser.add_argument("--target-id", type=int, help="Instructor id to keep")
    parser.add_argument("--apply", action="store_true", help="Apply the instructor merge")
    parser.add_argument(
        "--allow-overlaps", action="store_true",
        help="Allow existing overlapping approved appointments; moved records are flagged as allowed double bookings.",
    )
    args = parser.parse_args()
    database = Path(args.database).expanduser()
    if not database.is_file():
        print(f"Database not found: {database}", file=sys.stderr)
        return 2
    conn = sqlite3.connect(database)
    conn.row_factory = sqlite3.Row
    try:
        if args.find:
            return list_matches(conn, args.find)
        if not args.source_id or not args.target_id or args.source_id == args.target_id:
            parser.error("use --find, or provide different --source-id and --target-id values")
        source = conn.execute("SELECT * FROM instructors WHERE id = ?", (args.source_id,)).fetchone()
        target = conn.execute("SELECT * FROM instructors WHERE id = ?", (args.target_id,)).fetchone()
        if not source or not target:
            raise ValueError("One or both instructor ids do not exist.")
        if source["branch_id"] != target["branch_id"]:
            raise ValueError("The two instructors are in different branches and cannot be merged safely.")
        source_counts = counts(conn, args.source_id)
        source_login_ids = [
            row["id"]
            for row in conn.execute(
                "SELECT id FROM users WHERE role = 'instructor' AND instructor_id = ?",
                (args.source_id,),
            ).fetchall()
        ]
        overlap_count = overlapping_approved_count(conn, args.source_id, args.target_id)
        print(f"Move from: {args.source_id} | {source['name']}")
        print(f"Keep:      {args.target_id} | {target['name']}")
        print("Records to move:")
        for label, count in source_counts.items():
            print(f"  {label.replace('_', ' ')}: {count}")
        print(f"  overlapping approved appointments: {overlap_count}")
        if not args.apply:
            print("Dry run only. Re-run with --apply after verifying the ids and counts.")
            return 0
        if overlap_count and not args.allow_overlaps:
            raise ValueError(
                "Approved appointments would overlap after this merge. Review them, or re-run with --allow-overlaps to preserve them as explicit allowed double bookings."
            )

        backup = backup_database(database)
        conn.execute("BEGIN IMMEDIATE")
        if overlap_count:
            conn.execute(
                "UPDATE bookings SET allow_double_booking = 1 WHERE instructor_id = ? AND validation_status = 'Approved'",
                (args.source_id,),
            )
        conn.execute("UPDATE bookings SET instructor_id = ?, updated_at = CURRENT_TIMESTAMP WHERE instructor_id = ?", (args.target_id, args.source_id))
        conn.execute("UPDATE booking_slots SET instructor_id = ?, updated_at = CURRENT_TIMESTAMP WHERE instructor_id = ?", (args.target_id, args.source_id))
        conn.execute("UPDATE instructor_time_off SET instructor_id = ?, updated_at = CURRENT_TIMESTAMP WHERE instructor_id = ?", (args.target_id, args.source_id))
        conn.execute("INSERT OR IGNORE INTO instructor_weekly_availability (instructor_id, weekday, start_time, end_time, created_at, updated_at) SELECT ?, weekday, start_time, end_time, created_at, updated_at FROM instructor_weekly_availability WHERE instructor_id = ?", (args.target_id, args.source_id))
        conn.execute("DELETE FROM instructor_weekly_availability WHERE instructor_id = ?", (args.source_id,))
        conn.execute("INSERT OR IGNORE INTO service_instructors (service_id, instructor_id) SELECT service_id, ? FROM service_instructors WHERE instructor_id = ?", (args.target_id, args.source_id))
        conn.execute("DELETE FROM service_instructors WHERE instructor_id = ?", (args.source_id,))
        conn.execute("INSERT OR IGNORE INTO default_lunch_exceptions (instructor_id, target_date, created_at) SELECT ?, target_date, created_at FROM default_lunch_exceptions WHERE instructor_id = ?", (args.target_id, args.source_id))
        conn.execute("DELETE FROM default_lunch_exceptions WHERE instructor_id = ?", (args.source_id,))
        conn.execute("INSERT OR IGNORE INTO default_break_exceptions (instructor_id, target_date, break_kind, created_at) SELECT ?, target_date, break_kind, created_at FROM default_break_exceptions WHERE instructor_id = ?", (args.target_id, args.source_id))
        conn.execute("DELETE FROM default_break_exceptions WHERE instructor_id = ?", (args.source_id,))
        merge_assignments(conn, args.source_id, args.target_id)
        conn.execute("UPDATE users SET instructor_id = ?, updated_at = CURRENT_TIMESTAMP WHERE instructor_id = ?", (args.target_id, args.source_id))
        if source_login_ids:
            placeholders = ",".join("?" for _ in source_login_ids)
            conn.execute(
                f"""
                UPDATE users
                SET is_active = 0, login_enabled = 0, deactivated_at = CURRENT_TIMESTAMP,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id IN ({placeholders})
                """,
                source_login_ids,
            )
        conn.execute("UPDATE instructors SET is_active = 0, updated_at = CURRENT_TIMESTAMP WHERE id = ?", (args.source_id,))
        conn.commit()
        integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
        if integrity != "ok":
            raise RuntimeError(f"Database integrity check failed: {integrity}")
        print(f"Instructor merge complete. Backup created: {backup}")
        return 0
    except Exception as exc:
        conn.rollback()
        print(f"No changes were kept: {exc}", file=sys.stderr)
        return 1
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
