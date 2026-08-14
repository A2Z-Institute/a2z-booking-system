"""Safely reset the local A2Z administrator password."""

from __future__ import annotations

import getpass

from dotenv import load_dotenv
from werkzeug.security import generate_password_hash

from database import database_path, get_db, init_db


def main() -> None:
    load_dotenv()
    init_db()
    print(f"Database: {database_path()}")
    password = getpass.getpass("New admin password: ")
    confirmation = getpass.getpass("Confirm new password: ")
    if password != confirmation:
        raise SystemExit("Passwords did not match. Nothing was changed.")
    if len(password) < 12:
        raise SystemExit("Use at least 12 characters. Nothing was changed.")
    if password.lower() == password or password.upper() == password:
        raise SystemExit("Include both uppercase and lowercase letters. Nothing was changed.")
    if not any(character.isdigit() for character in password):
        raise SystemExit("Include at least one number. Nothing was changed.")

    with get_db() as connection:
        result = connection.execute(
            """UPDATE users
               SET password_hash=?, must_change_password=0, is_active=1,
                   login_enabled=1, updated_at=CURRENT_TIMESTAMP
               WHERE lower(trim(username))='admin' AND role='admin'""",
            (generate_password_hash(password),),
        )
        if result.rowcount != 1:
            raise SystemExit(
                f"Expected one admin account but updated {result.rowcount}. Nothing was changed."
            )
    print("Administrator password reset successfully.")


if __name__ == "__main__":
    main()
