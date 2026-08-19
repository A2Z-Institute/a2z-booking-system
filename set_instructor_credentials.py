"""Set every instructor login to the A2Z standard credentials.

Username: exact full name, e.g. ``Abhinand Biju``
Password: first name in lowercase + ``@123``, e.g. ``abhinand@123``

The script creates a verified backup before changing anything and refuses to
partially update the database if usernames would collide with another account.
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
from datetime import datetime, timezone

from backup_database import create_backup, verify_database
from database import database_path, get_db
from werkzeug.security import generate_password_hash


def credentials(full_name: str) -> tuple[str, str]:
    name = " ".join((full_name or "").split())
    if not name:
        raise ValueError("Instructor has an empty full name.")
    if len(name) > 50:
        raise ValueError(f"Instructor full name is over 50 characters: {name!r}")
    if not re.fullmatch(r"[A-Za-z0-9._ -]{3,50}", name):
        raise ValueError(f"Instructor name cannot be used as a username: {name!r}")
    first = re.sub(r"[^A-Za-z0-9]", "", name.split()[0]).lower()
    if not first:
        raise ValueError(f"Instructor first name cannot form a password: {name!r}")
    return name, f"{first}@123"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply", action="store_true",
        help="write the instructor usernames/passwords after creating a backup",
    )
    args = parser.parse_args()

    path = database_path()
    if not path.exists():
        raise SystemExit(f"Database not found: {path}")
    verify_database(path)

    with get_db() as conn:
        rows = conn.execute(
            """
            SELECT u.id, u.username, u.full_name, u.email, i.name AS instructor_name
            FROM users u
            JOIN instructors i ON i.id = u.instructor_id
            WHERE u.role = 'instructor'
            ORDER BY u.id
            """
        ).fetchall()
        if not rows:
            print(json.dumps({"updated": 0, "message": "No instructor accounts found."}, indent=2))
            return

        planned = []
        usernames = {}
        for row in rows:
            username, password = credentials(row["full_name"] or row["instructor_name"])
            key = username.casefold()
            if key in usernames and usernames[key] != row["id"]:
                raise SystemExit(f"Duplicate instructor username would be created: {username!r}")
            usernames[key] = row["id"]
            planned.append((row["id"], username, password))

        placeholders = ",".join("?" for _ in planned)
        ids = [item[0] for item in planned]
        conflicts = conn.execute(
            f"""
            SELECT id, username, role, 'username' AS conflict_type FROM users
            WHERE lower(username) IN ({','.join('lower(?)' for _ in planned)})
              AND id NOT IN ({placeholders})
            UNION ALL
            SELECT id, email AS username, role, 'email' AS conflict_type FROM users
            WHERE email IS NOT NULL AND trim(email) != ''
              AND lower(email) IN ({','.join('lower(?)' for _ in planned)})
              AND id NOT IN ({placeholders})
            """,
            [item[1] for item in planned] + ids + [item[1] for item in planned] + ids,
        ).fetchall()
        if conflicts:
            details = [dict(row) for row in conflicts]
            raise SystemExit(f"Username conflicts found; nothing changed: {details}")

        print(json.dumps({
            "database": str(path),
            "instructor_accounts": len(planned),
            "applied": args.apply,
            "planned": [
                {"user_id": user_id, "username": username, "password": password}
                for user_id, username, password in planned
            ],
        }, indent=2))
        if not args.apply:
            print("Dry run only. Use --apply to update instructor accounts after confirming the list.")
            return

    backup = create_backup(once_per_day=False, retain=30)
    if not backup:
        raise SystemExit("Backup could not be created; nothing was changed.")

    with get_db() as conn:
        conn.execute("BEGIN IMMEDIATE")
        for user_id, username, password in planned:
            conn.execute(
                """
                UPDATE users
                SET username = ?, password_hash = ?, must_change_password = 0,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ? AND role = 'instructor'
                """,
                (username, generate_password_hash(password), user_id),
            )

    verify_database(path)
    print(json.dumps({
        "updated": len(planned),
        "backup": str(backup),
        "integrity_check": "ok",
        "completed_at": datetime.now(timezone.utc).isoformat(),
    }, indent=2))


if __name__ == "__main__":
    main()
