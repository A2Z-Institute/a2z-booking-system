"""Read-only production database verification for deployment and backups."""

from __future__ import annotations

import sqlite3

from backup_database import verify_database
from database import database_path


def main():
    path = database_path()
    if not path.is_file():
        raise SystemExit(f"Database not found: {path}")
    verify_database(path)
    connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=30)
    try:
        foreign_key_issues = connection.execute("PRAGMA foreign_key_check").fetchall()
        if foreign_key_issues:
            raise SystemExit(
                f"Foreign-key verification failed with {len(foreign_key_issues)} issue(s)."
            )
        counts = {}
        for label, table, where in (
            ("bookings", "bookings", ""),
            ("active bookings", "bookings", " WHERE validation_status NOT IN ('Cancelled','Rejected')"),
            ("clients", "users", " WHERE role='student'"),
            ("instructors", "instructors", ""),
            ("equipment", "machines", ""),
            ("services", "services", ""),
            ("booking slots", "booking_slots", ""),
            ("breaks/busy periods", "instructor_time_off", ""),
            ("notification jobs", "notification_queue", ""),
        ):
            counts[label] = connection.execute(
                f"SELECT count(*) FROM {table}{where}"
            ).fetchone()[0]
    finally:
        connection.close()
    print(f"Database: {path}")
    print("Integrity: ok")
    print("Foreign keys: ok")
    for label, value in counts.items():
        print(f"{label.title()}: {value}")


if __name__ == "__main__":
    main()
