"""Safely clear appointments while preserving all calendar capacity settings.

This utility removes appointment records only. It deliberately preserves
clients, instructors, equipment, blue booking slots, and break/busy-time rows.
It always makes a verified SQLite backup before an --apply deletion.

Run inside the Coolify A2Z application container:

    python clear_appointments_only.py            # report only
    python clear_appointments_only.py --apply    # delete appointments
"""

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from backup_database import create_backup, verify_database
from database import database_path, get_db


def _count(conn, statement: str) -> int:
    return int(conn.execute(statement).fetchone()[0])


def appointment_counts(conn) -> dict[str, int]:
    return {
        "appointments": _count(conn, "SELECT count(*) FROM bookings"),
        "appointment_services": _count(
            conn, "SELECT count(*) FROM booking_services"
        ),
        "appointment_intake_values": _count(
            conn, "SELECT count(*) FROM booking_intake_values"
        ),
        "appointment_notifications": _count(
            conn,
            """
            SELECT count(*) FROM notification_queue
            WHERE booking_id IN (SELECT id FROM bookings)
            """,
        ),
        "appointment_audit_events": _count(
            conn,
            """
            SELECT count(*) FROM audit_events
            WHERE booking_id IN (SELECT id FROM bookings)
            """,
        ),
        # These counts prove the script leaves calendar capacity in place.
        "booking_slots_preserved": _count(conn, "SELECT count(*) FROM booking_slots"),
        "breaks_and_busy_time_preserved": _count(
            conn, "SELECT count(*) FROM instructor_time_off"
        ),
        "clients_preserved": _count(
            conn, "SELECT count(*) FROM users WHERE role = 'student'"
        ),
        "instructors_preserved": _count(conn, "SELECT count(*) FROM instructors"),
    }


def write_report(path: Path, report: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Delete appointments only; keep clients, instructors, slots and breaks."
    )
    parser.add_argument(
        "--apply", action="store_true", help="Actually delete appointment records"
    )
    parser.add_argument("--database", help="Optional database path for maintenance")
    parser.add_argument("--report", help="Optional JSON report destination")
    args = parser.parse_args()

    if args.database:
        os.environ["A2Z_DATABASE"] = str(Path(args.database).expanduser().resolve())
    db_path = database_path()
    if not db_path.is_file():
        raise SystemExit(f"Database not found: {db_path}")
    verify_database(db_path)

    report_path = Path(
        args.report
        or (
            Path(os.environ.get("A2Z_BACKUP_DIR", "/data/backups"))
            / f"appointments-clear-{datetime.now():%Y%m%d-%H%M%S}.json"
        )
    ).resolve()
    report = {
        "applied": bool(args.apply),
        "database": str(db_path),
        "started_at": datetime.now(timezone.utc).isoformat(),
    }

    with get_db() as conn:
        report["before"] = appointment_counts(conn)
    if not args.apply:
        report["message"] = (
            "Dry run only. Use --apply to delete appointments after confirming the counts."
        )
        write_report(report_path, report)
        print(json.dumps(report, indent=2))
        return 0

    backup_path = create_backup(
        once_per_day=False,
        retain=int(os.environ.get("A2Z_BACKUP_RETENTION", "30")),
    )
    if not backup_path:
        raise SystemExit("A verified backup could not be created; no appointments were deleted.")
    report["pre_clear_backup"] = str(backup_path)

    with get_db() as conn:
        conn.execute("BEGIN IMMEDIATE")
        # Child rows without ON DELETE CASCADE are removed first.  Slots and
        # breaks are different calendar tables and are intentionally untouched.
        conn.execute(
            "DELETE FROM audit_events WHERE booking_id IN (SELECT id FROM bookings)"
        )
        conn.execute(
            "DELETE FROM notification_queue WHERE booking_id IN (SELECT id FROM bookings)"
        )
        conn.execute(
            "DELETE FROM booking_intake_values WHERE booking_id IN (SELECT id FROM bookings)"
        )
        conn.execute(
            "DELETE FROM booking_services WHERE booking_id IN (SELECT id FROM bookings)"
        )
        conn.execute("DELETE FROM bookings")
        report["after"] = appointment_counts(conn)

    verify_database(db_path)
    if report["after"]["appointments"] != 0:
        raise RuntimeError("Appointment clear did not complete; database backup is available.")
    report["integrity_check"] = "ok"
    report["completed_at"] = datetime.now(timezone.utc).isoformat()
    write_report(report_path, report)
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
