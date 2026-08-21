"""Apply the approved instructor username and temporary-password register.

Run this once in the Coolify application terminal after deploying the release:

    python apply_instructor_credentials.py --apply

The script takes a SQLite backup before it changes anything. Without --apply it
performs only a safe preview. Every updated or created account is marked to
change its password at first sign-in.
"""

from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

from werkzeug.security import generate_password_hash

from database import database_path


# Approved instructor account details from "booking credintial.xlsx".
CREDENTIALS = {
    "JASMIN": ("Jasmin", "jasmin@123"),
    "ASHWIN TM": ("Ashwin Tm", "ashwin@123"),
    "MUHAMMAD ANFAL": ("Muhammad Anfal", "anfal@123"),
    "ALBIN THOMAS": ("Albin Thomas", "albin@123"),
    "THAHA HUSSAIN M A": ("Thaha", "thaha@123"),
    "JITHU PRAKASH": ("Jithu Prakash", "jithu@123"),
    "SHARHABIL": ("Sharhabil", "sharhabil@123"),
    "ABHISHEK P P": ("Abhishek P P", "abhishek@123"),
    "ASWANTH M P": ("Aswanth M P", "aswanth@123"),
    "GOKUL BABU": ("Gokul Babu", "gokul@123"),
    "ANSAN": ("Ansan", "ansan@123"),
    "ANU AASHAN": ("Anu Aashan", "anu@123"),
    "AJAY KUNJUMON": ("Ajay Kunjumon", "ajay@123"),
    "ABHINAND BIJU": ("Abhinand Biju", "abhinand@123"),
    "ADHITHYAN SAJEEV": ("Adhithyan Sajeev", "adhithyan@123"),
    "REYNOLD FORKLIFT": ("Reynold", "reynold@123"),
    "ROSHAN(FIXED TOWER)": ("Roshan", "roshan@123"),
    "SARATH K U": ("Sarath K U", "sarath@123"),
    "ASHISH": ("Ashish", "ashish@123"),
    "JAYAKRISHNAN": ("Jayakrishnan", "jayakrishnan@123"),
    "ALIN SHIBY": ("Alin Shiby", "alin@123"),
    "AJAY KRISHNA": ("Ajay Krishna", "ajay@123"),
}


def normalise(value: str) -> str:
    return " ".join(str(value or "").upper().split()).replace("( ", "(").replace(" )", ")")


def instructor_key(value: str) -> str:
    return normalise(value).split("(", 1)[0].strip() if "(" in normalise(value) else normalise(value)


def backup_database(db_path: Path) -> Path:
    backup_dir = Path(os.environ.get("A2Z_BACKUP_DIR", db_path.parent / "backups"))
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_path = backup_dir / f"a2z-before-instructor-credentials-{stamp}.db"
    with sqlite3.connect(db_path) as source, sqlite3.connect(backup_path) as destination:
        source.backup(destination)
    return backup_path


def load_instructors(connection: sqlite3.Connection) -> dict[str, sqlite3.Row]:
    rows = connection.execute(
        "SELECT id, name, branch_id FROM instructors WHERE is_active = 1 ORDER BY id"
    ).fetchall()
    by_key: dict[str, sqlite3.Row] = {}
    for row in rows:
        key = instructor_key(row["name"])
        if key in by_key:
            raise RuntimeError(
                f"More than one active instructor matches {key!r}; merge duplicates before applying credentials."
            )
        by_key[key] = row
    return by_key


def validate(connection: sqlite3.Connection, instructors: dict[str, sqlite3.Row]) -> list[tuple[str, sqlite3.Row, str, str, sqlite3.Row | None]]:
    plan = []
    missing = []
    for name, (username, password) in CREDENTIALS.items():
        instructor = instructors.get(instructor_key(name))
        if not instructor:
            missing.append(name)
            continue
        linked_users = connection.execute(
            "SELECT id, username FROM users WHERE instructor_id = ? ORDER BY id", (instructor["id"],)
        ).fetchall()
        if len(linked_users) > 1:
            raise RuntimeError(
                f"Instructor {instructor['name']} has {len(linked_users)} linked accounts; resolve this first."
            )
        collision = connection.execute(
            "SELECT id, instructor_id FROM users WHERE lower(username) = lower(?)", (username,)
        ).fetchone()
        linked_user = linked_users[0] if linked_users else None
        if collision and (not linked_user or collision["id"] != linked_user["id"]):
            raise RuntimeError(
                f"Username {username!r} already belongs to another account (user ID {collision['id']})."
            )
        plan.append((name, instructor, username, password, linked_user))
    if missing:
        raise RuntimeError("No active instructor profile found for: " + ", ".join(missing))
    return plan


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="apply the account changes")
    args = parser.parse_args()

    db_path = database_path()
    if not db_path.exists():
        raise SystemExit(f"Database not found: {db_path}")

    connection = sqlite3.connect(db_path, timeout=30)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    try:
        plan = validate(connection, load_instructors(connection))
        print(f"Database: {db_path}")
        print(f"Instructor accounts in register: {len(plan)}")
        for _, instructor, username, _, linked_user in plan:
            action = "update" if linked_user else "create"
            print(f"  {action:6} {instructor['name']} -> {username}")
        if not args.apply:
            print("Preview only. Re-run with --apply to create/reset these instructor accounts.")
            return

        backup_path = backup_database(db_path)
        connection.execute("BEGIN IMMEDIATE")
        for _, instructor, username, password, linked_user in plan:
            password_hash = generate_password_hash(password)
            if linked_user:
                connection.execute(
                    """
                    UPDATE users
                    SET username = ?, password_hash = ?, role = 'instructor',
                        full_name = ?, branch_id = ?, is_active = 1,
                        login_enabled = 1, must_change_password = 1,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                    """,
                    (username, password_hash, instructor["name"], instructor["branch_id"], linked_user["id"]),
                )
            else:
                connection.execute(
                    """
                    INSERT INTO users
                        (username, password_hash, role, instructor_id, full_name,
                         branch_id, is_active, login_enabled, must_change_password)
                    VALUES (?, ?, 'instructor', ?, ?, ?, 1, 1, 1)
                    """,
                    (username, password_hash, instructor["id"], instructor["name"], instructor["branch_id"]),
                )
        connection.commit()
        print(f"Credential update complete. Backup created: {backup_path}")
        print("Every instructor must change the temporary password after first sign-in.")
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(f"No account changes were applied: {error}", file=sys.stderr)
        raise SystemExit(1) from error
