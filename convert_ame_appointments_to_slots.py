#!/usr/bin/env python3
"""Convert placeholder AME appointments into blue booking-slot bands.

AME rows such as ``AME 58`` are operational availability blocks, not client
appointments.  This utility converts only names matching ``AME`` followed by a
number.  It preserves the instructor, equipment, branch, date and time, then
removes the placeholder appointment and its appointment-only child records.

Always run the preview first:

    python convert_ame_appointments_to_slots.py
    python convert_ame_appointments_to_slots.py --apply

The apply operation creates a verified database backup before changing data.
"""

from __future__ import annotations

import argparse
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path

from backup_database import create_backup, verify_database
from database import database_path, get_db


AME_NAME = re.compile(r"^\s*AME\s*[- ]*\d+\b", re.IGNORECASE)


def matching_rows(conn):
    return conn.execute(
        """
        SELECT b.id, b.student_name, b.mobile_number, b.target_date,
               b.start_time, b.end_time, b.notes, b.instructor_id,
               b.machine_id, b.branch_id, i.name AS instructor_name,
               m.name AS machine_name, m.code AS machine_code
          FROM bookings b
          JOIN instructors i ON i.id = b.instructor_id
          JOIN machines m ON m.id = b.machine_id
         ORDER BY b.target_date, b.start_time, b.id
        """
    ).fetchall()


def ame_rows(conn):
    return [row for row in matching_rows(conn) if AME_NAME.match(row["student_name"] or "")]


def slot_exists(conn, row) -> bool:
    return bool(
        conn.execute(
            """
            SELECT 1 FROM booking_slots
             WHERE instructor_id = ? AND machine_id = ? AND target_date = ?
               AND start_time = ? AND end_time = ?
             LIMIT 1
            """,
            (row["instructor_id"], row["machine_id"], row["target_date"], row["start_time"], row["end_time"]),
        ).fetchone()
    )


def report_for(conn) -> dict:
    rows = ame_rows(conn)
    return {
        "matched_ame_appointments": len(rows),
        "would_create_slots": sum(not slot_exists(conn, row) for row in rows),
        "would_remove_placeholder_appointments": len(rows),
        "items": [
            {
                "booking_id": row["id"],
                "ame_name": row["student_name"],
                "date": row["target_date"],
                "time": f"{row['start_time']}-{row['end_time']}",
                "instructor": row["instructor_name"],
                "equipment": row["machine_name"] or row["machine_code"],
            }
            for row in rows
        ],
    }


def remove_appointment_children(conn, booking_id: int) -> None:
    # The slot replaces the appointment; client records are never touched.
    conn.execute("DELETE FROM audit_events WHERE booking_id = ?", (booking_id,))
    conn.execute("DELETE FROM notification_queue WHERE booking_id = ?", (booking_id,))
    conn.execute("DELETE FROM booking_intake_values WHERE booking_id = ?", (booking_id,))
    conn.execute("DELETE FROM booking_services WHERE booking_id = ?", (booking_id,))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Create slots and remove matched AME appointment records")
    parser.add_argument("--database", help="Optional database path")
    parser.add_argument("--report", help="Optional JSON report path")
    args = parser.parse_args()

    if args.database:
        os.environ["A2Z_DATABASE"] = str(Path(args.database).expanduser().resolve())
    db_path = database_path()
    if not db_path.is_file():
        raise SystemExit(f"Database not found: {db_path}")
    verify_database(db_path)

    report_path = Path(
        args.report
        or Path(os.environ.get("A2Z_BACKUP_DIR", "/data/backups"))
        / f"ame-slot-conversion-{datetime.now():%Y%m%d-%H%M%S}.json"
    )
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report = {"applied": bool(args.apply), "database": str(db_path), "started_at": datetime.now(timezone.utc).isoformat()}

    with get_db() as conn:
        report.update(report_for(conn))
    if not args.apply:
        report["message"] = "Preview only. Run again with --apply after checking the AME list."
        report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(json.dumps(report, indent=2))
        return 0

    backup = create_backup(once_per_day=False, retain=int(os.environ.get("A2Z_BACKUP_RETENTION", "30")))
    if not backup:
        raise SystemExit("A verified pre-conversion backup could not be created; no changes were made.")
    report["pre_conversion_backup"] = str(backup)

    with get_db() as conn:
        rows = ame_rows(conn)
        conn.execute("BEGIN IMMEDIATE")
        created = 0
        for row in rows:
            if not slot_exists(conn, row):
                note = f"Converted AME availability slot from appointment #{row['id']}: {row['student_name']}"
                if row["notes"]:
                    note += f" | Original note: {row['notes']}"
                conn.execute(
                    """
                    INSERT INTO booking_slots
                        (instructor_id, machine_id, branch_id, target_date,
                         start_time, end_time, notes, source_reference)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (row["instructor_id"], row["machine_id"], row["branch_id"], row["target_date"],
                     row["start_time"], row["end_time"], note, f"a2z:ame-slot:{row['id']}"),
                )
                created += 1
            remove_appointment_children(conn, row["id"])
            conn.execute("DELETE FROM bookings WHERE id = ?", (row["id"],))
        report["slots_created"] = created
        report["appointments_removed"] = len(rows)

    verify_database(db_path)
    report["integrity_check"] = "ok"
    report["completed_at"] = datetime.now(timezone.utc).isoformat()
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
