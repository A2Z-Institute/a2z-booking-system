"""SQLite data layer for the A2Z scheduling portal.

The schema migration helpers deliberately add columns in place so an existing
pilot database can be upgraded without deleting bookings.
"""

from __future__ import annotations

import os
import re
import sqlite3
from contextlib import contextmanager
from pathlib import Path

from werkzeug.security import generate_password_hash


BASE_DIR = Path(__file__).resolve().parent
DEFAULT_DB_PATH = BASE_DIR / "a2z_booking.db"


def database_path() -> Path:
    """Return the configured database path at call time (useful for tests)."""
    return Path(os.environ.get("A2Z_DATABASE", DEFAULT_DB_PATH)).resolve()


@contextmanager
def get_db():
    database_path().parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(database_path(), timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 15000")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _column_names(conn: sqlite3.Connection, table: str) -> set[str]:
    return {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}


def _ensure_columns(conn: sqlite3.Connection, table: str, columns: dict[str, str]) -> None:
    existing = _column_names(conn, table)
    for name, definition in columns.items():
        if name not in existing:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {definition}")


def _assert_unambiguous_login_identities(conn: sqlite3.Connection) -> None:
    """Fail safely instead of leaving case-insensitive login order-dependent."""
    duplicate = conn.execute(
        """
        SELECT lower(username) AS identity, group_concat(id) AS user_ids
        FROM users GROUP BY lower(username) HAVING count(*) > 1 LIMIT 1
        """
    ).fetchone()
    if duplicate:
        raise RuntimeError(
            "Duplicate usernames differing only by letter case must be resolved "
            f"before startup (identity {duplicate['identity']!r}, user IDs "
            f"{duplicate['user_ids']})."
        )
    collision = conn.execute(
        """
        SELECT u.id AS username_owner, e.id AS email_owner, u.username AS identity
        FROM users u JOIN users e
          ON e.id != u.id AND e.email IS NOT NULL AND e.email != ''
         AND lower(e.email) = lower(u.username)
        LIMIT 1
        """
    ).fetchone()
    if collision:
        raise RuntimeError(
            "A username duplicates another account's email and must be resolved "
            f"before startup (identity {collision['identity']!r}, user IDs "
            f"{collision['username_owner']} and {collision['email_owner']})."
        )


def _has_expected_account_foreign_keys(conn: sqlite3.Connection) -> bool:
    user_keys = {
        (row["from"], row["table"], row["to"])
        for row in conn.execute("PRAGMA foreign_key_list(users)")
    }
    booking_keys = {
        (row["from"], row["table"], row["to"])
        for row in conn.execute("PRAGMA foreign_key_list(bookings)")
    }
    return {
        ("branch_id", "branches", "id"),
        ("instructor_id", "instructors", "id"),
    }.issubset(user_keys) and {
        ("student_user_id", "users", "id"),
        ("reviewed_by", "users", "id"),
        ("attendance_recorded_by", "users", "id"),
    }.issubset(booking_keys)


def _rebuild_legacy_account_tables(conn: sqlite3.Connection) -> None:
    """Rebuild the two legacy tables so ALTER-added columns gain real FKs.

    SQLite cannot add a foreign-key constraint to an existing column. A table
    rebuild is therefore the only safe upgrade path. IDs and every legacy row
    are copied verbatim inside one transaction.
    """
    if _has_expected_account_foreign_keys(conn):
        return

    conn.commit()
    conn.execute("PRAGMA foreign_keys = OFF")
    try:
        # ``executescript`` issues an implicit commit before it runs. Execute
        # each statement directly so a failed legacy upgrade really is atomic.
        conn.execute("BEGIN IMMEDIATE")
        statements = [
            # These triggers live on tables that are not rebuilt but refer to
            # ``users``. Drop them inside the transaction before the table
            # swap; init_db recreates them after the rename succeeds.
            "DROP TRIGGER IF EXISTS validate_assignment_insert",
            "DROP TRIGGER IF EXISTS validate_assignment_reactivate",
            "DROP TRIGGER IF EXISTS validate_instructor_verifier_insert",
            "DROP TRIGGER IF EXISTS validate_instructor_verifier_update",
            "DROP TABLE IF EXISTS bookings_rebuild",
            "DROP TABLE IF EXISTS users_rebuild",
            """CREATE TABLE users_rebuild (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                role TEXT NOT NULL DEFAULT 'student',
                instructor_id INTEGER DEFAULT NULL,
                full_name TEXT,
                email TEXT,
                phone TEXT,
                branch_id INTEGER,
                is_active INTEGER NOT NULL DEFAULT 1,
                login_enabled INTEGER NOT NULL DEFAULT 1,
                must_change_password INTEGER NOT NULL DEFAULT 1,
                deactivated_at TEXT,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (instructor_id) REFERENCES instructors(id),
                FOREIGN KEY (branch_id) REFERENCES branches(id)
            )""",
            """CREATE TABLE bookings_rebuild (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                student_name TEXT NOT NULL,
                mobile_number TEXT NOT NULL,
                machine_id INTEGER NOT NULL,
                instructor_id INTEGER NOT NULL,
                branch_id INTEGER NOT NULL,
                target_date TEXT NOT NULL,
                start_time TEXT NOT NULL,
                end_time TEXT NOT NULL,
                validation_status TEXT NOT NULL DEFAULT 'Pending',
                student_user_id INTEGER,
                notes TEXT,
                review_notes TEXT,
                reviewed_by INTEGER,
                reviewed_at TEXT,
                attendance_recorded_by INTEGER,
                attendance_recorded_at TEXT,
                cancelled_at TEXT,
                whatsapp_sent INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (machine_id) REFERENCES machines(id),
                FOREIGN KEY (instructor_id) REFERENCES instructors(id),
                FOREIGN KEY (branch_id) REFERENCES branches(id),
                FOREIGN KEY (student_user_id) REFERENCES users_rebuild(id),
                FOREIGN KEY (reviewed_by) REFERENCES users_rebuild(id),
                FOREIGN KEY (attendance_recorded_by) REFERENCES users_rebuild(id)
            )""",
            """INSERT INTO users_rebuild
                (id, username, password_hash, role, instructor_id, full_name,
                 email, phone, branch_id, is_active, login_enabled,
                 must_change_password, deactivated_at, updated_at, created_at)
            SELECT id, username, password_hash, role, instructor_id, full_name,
                   email, phone, branch_id, is_active, login_enabled,
                   must_change_password, deactivated_at,
                   COALESCE(updated_at, created_at, CURRENT_TIMESTAMP),
                   COALESCE(created_at, CURRENT_TIMESTAMP)
            FROM users""",
            """INSERT INTO bookings_rebuild
                (id, student_name, mobile_number, machine_id, instructor_id,
                 branch_id, target_date, start_time, end_time,
                 validation_status, student_user_id, notes, review_notes,
                 reviewed_by, reviewed_at, attendance_recorded_by,
                 attendance_recorded_at, cancelled_at, whatsapp_sent,
                 created_at, updated_at)
            SELECT id, student_name, mobile_number, machine_id, instructor_id,
                   branch_id, target_date, start_time, end_time,
                   validation_status, student_user_id, notes, review_notes,
                   reviewed_by, reviewed_at, attendance_recorded_by,
                   attendance_recorded_at, cancelled_at,
                   COALESCE(whatsapp_sent, 0),
                   COALESCE(created_at, CURRENT_TIMESTAMP),
                   COALESCE(updated_at, created_at, CURRENT_TIMESTAMP)
            FROM bookings""",
            "DROP TABLE bookings",
            "DROP TABLE users",
            "ALTER TABLE users_rebuild RENAME TO users",
            "ALTER TABLE bookings_rebuild RENAME TO bookings",
        ]
        for statement in statements:
            conn.execute(statement)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.execute("PRAGMA foreign_keys = ON")


def init_db() -> None:
    """Create a new database or safely upgrade the original prototype schema."""
    with get_db() as conn:
        conn.execute("PRAGMA journal_mode = WAL")
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS branches (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE NOT NULL,
                address TEXT,
                phone TEXT,
                is_active INTEGER NOT NULL DEFAULT 1
            );

            CREATE TABLE IF NOT EXISTS machines (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                machine_code TEXT UNIQUE NOT NULL,
                category TEXT NOT NULL,
                location TEXT,
                branch_id INTEGER NOT NULL,
                is_active INTEGER NOT NULL DEFAULT 1,
                FOREIGN KEY (branch_id) REFERENCES branches(id)
            );

            CREATE TABLE IF NOT EXISTS instructors (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                branch_id INTEGER NOT NULL,
                specialty TEXT,
                is_active INTEGER NOT NULL DEFAULT 1,
                verification_status TEXT NOT NULL DEFAULT 'unverified',
                verified_at TEXT,
                verified_by INTEGER,
                uses_custom_availability INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (branch_id) REFERENCES branches(id),
                FOREIGN KEY (verified_by) REFERENCES users(id),
                UNIQUE (name, branch_id)
            );

            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                role TEXT NOT NULL DEFAULT 'student',
                instructor_id INTEGER DEFAULT NULL,
                full_name TEXT,
                email TEXT,
                phone TEXT,
                branch_id INTEGER,
                is_active INTEGER NOT NULL DEFAULT 1,
                login_enabled INTEGER NOT NULL DEFAULT 1,
                must_change_password INTEGER NOT NULL DEFAULT 1,
                deactivated_at TEXT,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (instructor_id) REFERENCES instructors(id),
                FOREIGN KEY (branch_id) REFERENCES branches(id)
            );

            CREATE TABLE IF NOT EXISTS bookings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                student_name TEXT NOT NULL,
                mobile_number TEXT NOT NULL,
                machine_id INTEGER NOT NULL,
                instructor_id INTEGER NOT NULL,
                branch_id INTEGER NOT NULL,
                target_date TEXT NOT NULL,
                start_time TEXT NOT NULL,
                end_time TEXT NOT NULL,
                validation_status TEXT NOT NULL DEFAULT 'Pending',
                student_user_id INTEGER,
                notes TEXT,
                review_notes TEXT,
                reviewed_by INTEGER,
                reviewed_at TEXT,
                attendance_recorded_by INTEGER,
                attendance_recorded_at TEXT,
                cancelled_at TEXT,
                whatsapp_sent INTEGER NOT NULL DEFAULT 0,
                service_id INTEGER,
                service_name TEXT,
                service_price_cents INTEGER NOT NULL DEFAULT 0,
                currency TEXT NOT NULL DEFAULT 'INR',
                buffer_before_minutes INTEGER NOT NULL DEFAULT 0,
                buffer_after_minutes INTEGER NOT NULL DEFAULT 0,
                calendar_revision INTEGER NOT NULL DEFAULT 1,
                series_id TEXT,
                repeat_rule TEXT,
                allow_double_booking INTEGER NOT NULL DEFAULT 0,
                series_position INTEGER NOT NULL DEFAULT 1,
                series_count INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (machine_id) REFERENCES machines(id),
                FOREIGN KEY (instructor_id) REFERENCES instructors(id),
                FOREIGN KEY (branch_id) REFERENCES branches(id),
                FOREIGN KEY (student_user_id) REFERENCES users(id),
                FOREIGN KEY (reviewed_by) REFERENCES users(id),
                FOREIGN KEY (attendance_recorded_by) REFERENCES users(id)
            );

            CREATE TABLE IF NOT EXISTS services (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                branch_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                description TEXT,
                category TEXT,
                duration_minutes INTEGER NOT NULL DEFAULT 30,
                price_cents INTEGER NOT NULL DEFAULT 0,
                currency TEXT NOT NULL DEFAULT 'INR',
                buffer_before_minutes INTEGER NOT NULL DEFAULT 0,
                buffer_after_minutes INTEGER NOT NULL DEFAULT 0,
                color TEXT NOT NULL DEFAULT '#C8141B',
                available_weekdays TEXT NOT NULL DEFAULT '0,1,2,3,4,5',
                requires_approval INTEGER NOT NULL DEFAULT 1,
                is_active INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (branch_id) REFERENCES branches(id),
                UNIQUE (branch_id, name)
            );

            CREATE TABLE IF NOT EXISTS schema_migrations (
                migration_key TEXT PRIMARY KEY,
                applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS service_machines (
                service_id INTEGER NOT NULL,
                machine_id INTEGER NOT NULL,
                PRIMARY KEY (service_id, machine_id),
                FOREIGN KEY (service_id) REFERENCES services(id) ON DELETE CASCADE,
                FOREIGN KEY (machine_id) REFERENCES machines(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS service_instructors (
                service_id INTEGER NOT NULL,
                instructor_id INTEGER NOT NULL,
                PRIMARY KEY (service_id, instructor_id),
                FOREIGN KEY (service_id) REFERENCES services(id) ON DELETE CASCADE,
                FOREIGN KEY (instructor_id) REFERENCES instructors(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS booking_services (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                booking_id INTEGER NOT NULL,
                service_id INTEGER,
                service_name TEXT NOT NULL,
                duration_minutes INTEGER NOT NULL,
                price_cents INTEGER NOT NULL DEFAULT 0,
                currency TEXT NOT NULL DEFAULT 'INR',
                sort_order INTEGER NOT NULL DEFAULT 0,
                FOREIGN KEY (booking_id) REFERENCES bookings(id) ON DELETE CASCADE,
                FOREIGN KEY (service_id) REFERENCES services(id)
            );

            CREATE TABLE IF NOT EXISTS service_intake_fields (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                service_id INTEGER NOT NULL,
                field_key TEXT NOT NULL,
                label TEXT NOT NULL,
                field_type TEXT NOT NULL DEFAULT 'text',
                help_text TEXT,
                placeholder TEXT,
                is_required INTEGER NOT NULL DEFAULT 0,
                options_json TEXT,
                price_adjustment_cents INTEGER NOT NULL DEFAULT 0,
                duration_adjustment_minutes INTEGER NOT NULL DEFAULT 0,
                sort_order INTEGER NOT NULL DEFAULT 0,
                is_active INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (service_id) REFERENCES services(id) ON DELETE CASCADE,
                UNIQUE (service_id, field_key)
            );

            CREATE TABLE IF NOT EXISTS booking_intake_values (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                booking_id INTEGER NOT NULL,
                field_id INTEGER,
                field_key TEXT NOT NULL,
                field_label TEXT NOT NULL,
                value_text TEXT,
                file_name TEXT,
                file_path TEXT,
                mime_type TEXT,
                file_size INTEGER,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (booking_id) REFERENCES bookings(id) ON DELETE CASCADE,
                FOREIGN KEY (field_id) REFERENCES service_intake_fields(id),
                UNIQUE (booking_id, field_id)
            );

            CREATE TABLE IF NOT EXISTS notification_queue (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                booking_id INTEGER NOT NULL,
                channel TEXT NOT NULL,
                event_type TEXT NOT NULL,
                destination TEXT NOT NULL,
                scheduled_for TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'queued',
                attempts INTEGER NOT NULL DEFAULT 0,
                last_error TEXT,
                sent_at TEXT,
                locked_at TEXT,
                next_attempt_at TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (booking_id) REFERENCES bookings(id) ON DELETE CASCADE,
                UNIQUE (booking_id, channel, event_type, scheduled_for)
            );

            CREATE TABLE IF NOT EXISTS client_profiles (
                user_id INTEGER PRIMARY KEY,
                secondary_phone TEXT,
                secondary_email TEXT,
                birthday TEXT,
                gender TEXT,
                zip_code TEXT,
                city TEXT,
                street TEXT,
                internal_notes TEXT,
                tags TEXT,
                reminders_enabled INTEGER NOT NULL DEFAULT 1,
                preferred_channel TEXT NOT NULL DEFAULT 'email',
                updated_by INTEGER,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
                FOREIGN KEY (updated_by) REFERENCES users(id)
            );

            CREATE TABLE IF NOT EXISTS audit_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                actor_user_id INTEGER,
                booking_id INTEGER,
                event_type TEXT NOT NULL,
                details TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (actor_user_id) REFERENCES users(id),
                FOREIGN KEY (booking_id) REFERENCES bookings(id)
            );

            CREATE TABLE IF NOT EXISTS student_instructor_assignments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                student_user_id INTEGER NOT NULL,
                instructor_id INTEGER NOT NULL,
                assigned_by INTEGER,
                is_active INTEGER NOT NULL DEFAULT 1,
                assigned_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                ended_at TEXT,
                FOREIGN KEY (student_user_id) REFERENCES users(id),
                FOREIGN KEY (instructor_id) REFERENCES instructors(id),
                FOREIGN KEY (assigned_by) REFERENCES users(id),
                UNIQUE (student_user_id, instructor_id)
            );

            CREATE TABLE IF NOT EXISTS instructor_weekly_availability (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                instructor_id INTEGER NOT NULL,
                weekday INTEGER NOT NULL,
                start_time TEXT NOT NULL,
                end_time TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (instructor_id) REFERENCES instructors(id) ON DELETE CASCADE,
                UNIQUE (instructor_id, weekday, start_time, end_time)
            );

            CREATE TABLE IF NOT EXISTS instructor_time_off (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                instructor_id INTEGER NOT NULL,
                target_date TEXT NOT NULL,
                start_time TEXT NOT NULL,
                end_time TEXT NOT NULL,
                reason TEXT,
                notes TEXT,
                series_id TEXT,
                repeat_rule TEXT,
                series_position INTEGER NOT NULL DEFAULT 1,
                series_count INTEGER NOT NULL DEFAULT 1,
                calendar_revision INTEGER NOT NULL DEFAULT 1,
                created_by INTEGER,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (instructor_id) REFERENCES instructors(id) ON DELETE CASCADE,
                FOREIGN KEY (created_by) REFERENCES users(id)
            );

            CREATE TABLE IF NOT EXISTS default_lunch_exceptions (
                instructor_id INTEGER NOT NULL,
                target_date TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (instructor_id, target_date),
                FOREIGN KEY (instructor_id) REFERENCES instructors(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS booking_slots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                instructor_id INTEGER NOT NULL,
                machine_id INTEGER NOT NULL,
                branch_id INTEGER NOT NULL,
                target_date TEXT NOT NULL,
                start_time TEXT NOT NULL,
                end_time TEXT NOT NULL,
                notes TEXT,
                series_id TEXT,
                repeat_rule TEXT,
                series_position INTEGER NOT NULL DEFAULT 1,
                series_count INTEGER NOT NULL DEFAULT 1,
                calendar_revision INTEGER NOT NULL DEFAULT 1,
                created_by INTEGER,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (instructor_id) REFERENCES instructors(id) ON DELETE CASCADE,
                FOREIGN KEY (machine_id) REFERENCES machines(id),
                FOREIGN KEY (branch_id) REFERENCES branches(id),
                FOREIGN KEY (created_by) REFERENCES users(id)
            );
            """
        )

        # Upgrade databases made by the original prototype.
        _ensure_columns(
            conn,
            "branches",
            {
                "address": "TEXT",
                "phone": "TEXT",
                "is_active": "INTEGER NOT NULL DEFAULT 1",
                "timezone": "TEXT NOT NULL DEFAULT 'Asia/Kolkata'",
                "currency": "TEXT NOT NULL DEFAULT 'INR'",
                "reminder_channel": "TEXT NOT NULL DEFAULT 'email'",
            },
        )
        _ensure_columns(conn, "machines", {"is_active": "INTEGER NOT NULL DEFAULT 1"})
        _ensure_columns(
            conn,
            "instructors",
            {
                "specialty": "TEXT",
                "is_active": "INTEGER NOT NULL DEFAULT 1",
                "verification_status": "TEXT NOT NULL DEFAULT 'unverified'",
                "verified_at": "TEXT",
                "verified_by": "INTEGER",
                "uses_custom_availability": "INTEGER NOT NULL DEFAULT 0",
                "created_at": "TEXT",
                "updated_at": "TEXT",
            },
        )
        _ensure_columns(
            conn,
            "users",
            {
                "instructor_id": "INTEGER DEFAULT NULL",
                "full_name": "TEXT",
                "email": "TEXT",
                "phone": "TEXT",
                "branch_id": "INTEGER",
                "is_active": "INTEGER NOT NULL DEFAULT 1",
                "login_enabled": "INTEGER NOT NULL DEFAULT 1",
                "must_change_password": "INTEGER NOT NULL DEFAULT 1",
                "deactivated_at": "TEXT",
                "updated_at": "TEXT",
                # SQLite only permits constant defaults on ALTER TABLE. These
                # are backfilled below; new databases still use the full DDL.
                "created_at": "TEXT",
            },
        )
        _ensure_columns(
            conn,
            "bookings",
            {
                "student_user_id": "INTEGER",
                "notes": "TEXT",
                "review_notes": "TEXT",
                "reviewed_by": "INTEGER",
                "reviewed_at": "TEXT",
                "attendance_recorded_by": "INTEGER",
                "attendance_recorded_at": "TEXT",
                "cancelled_at": "TEXT",
                "whatsapp_sent": "INTEGER NOT NULL DEFAULT 0",
                "created_at": "TEXT DEFAULT CURRENT_TIMESTAMP",
                "updated_at": "TEXT",
            },
        )
        _ensure_columns(
            conn,
            "notification_queue",
            {
                "locked_at": "TEXT",
                "next_attempt_at": "TEXT",
            },
        )
        padding_migration = "20260814_remove_all_private_padding"
        if not conn.execute(
            "SELECT 1 FROM schema_migrations WHERE migration_key = ?",
            (padding_migration,),
        ).fetchone():
            conn.execute(
                "UPDATE services SET buffer_before_minutes = 0, "
                "buffer_after_minutes = 0, updated_at = CURRENT_TIMESTAMP"
            )
            conn.execute(
                "UPDATE bookings SET buffer_before_minutes = 0, "
                "buffer_after_minutes = 0, updated_at = CURRENT_TIMESTAMP"
            )
            conn.execute(
                "INSERT INTO schema_migrations (migration_key) VALUES (?)",
                (padding_migration,),
            )
        _ensure_columns(
            conn,
            "client_profiles",
            {
                "secondary_phone": "TEXT",
                "secondary_email": "TEXT",
                "birthday": "TEXT",
                "gender": "TEXT",
                "zip_code": "TEXT",
                "city": "TEXT",
                "street": "TEXT",
                "source_reference": "TEXT",
            },
        )

        conn.execute(
            "UPDATE users SET created_at = CURRENT_TIMESTAMP WHERE created_at IS NULL"
        )
        conn.execute(
            "UPDATE users SET updated_at = COALESCE(created_at, CURRENT_TIMESTAMP) "
            "WHERE updated_at IS NULL"
        )
        conn.execute(
            "UPDATE instructors SET created_at = CURRENT_TIMESTAMP WHERE created_at IS NULL"
        )
        conn.execute(
            "UPDATE instructors SET updated_at = COALESCE(created_at, CURRENT_TIMESTAMP) "
            "WHERE updated_at IS NULL"
        )
        conn.execute(
            "UPDATE bookings SET updated_at = COALESCE(created_at, CURRENT_TIMESTAMP) "
            "WHERE updated_at IS NULL"
        )

        _rebuild_legacy_account_tables(conn)

        # SmartScheduling-style appointments retain a snapshot of the selected
        # services and their private padding. These columns are added after the
        # legacy account-table rebuild so an in-place upgrade cannot discard
        # them during the table swap.
        _ensure_columns(
            conn,
            "bookings",
            {
                "service_id": "INTEGER",
                "service_name": "TEXT",
                "service_price_cents": "INTEGER NOT NULL DEFAULT 0",
                "currency": "TEXT NOT NULL DEFAULT 'INR'",
                "buffer_before_minutes": "INTEGER NOT NULL DEFAULT 0",
                "buffer_after_minutes": "INTEGER NOT NULL DEFAULT 0",
                "calendar_revision": "INTEGER NOT NULL DEFAULT 1",
                "series_id": "TEXT",
                "repeat_rule": "TEXT",
                "allow_double_booking": "INTEGER NOT NULL DEFAULT 0",
                "series_position": "INTEGER NOT NULL DEFAULT 1",
                "series_count": "INTEGER NOT NULL DEFAULT 1",
                "source_reference": "TEXT",
            },
        )
        _ensure_columns(
            conn,
            "instructor_time_off",
            {
                "notes": "TEXT",
                "series_id": "TEXT",
                "repeat_rule": "TEXT",
                "series_position": "INTEGER NOT NULL DEFAULT 1",
                "series_count": "INTEGER NOT NULL DEFAULT 1",
                "calendar_revision": "INTEGER NOT NULL DEFAULT 1",
                "created_by": "INTEGER",
                "updated_at": "TEXT",
                "source_reference": "TEXT",
            },
        )
        _ensure_columns(
            conn,
            "booking_slots",
            {"source_reference": "TEXT"},
        )
        for index_name in (
            "uq_bookings_source_reference", "uq_booking_slots_source_reference",
            "uq_time_off_source_reference",
        ):
            conn.execute(f"DROP INDEX IF EXISTS {index_name}")
        conn.execute("CREATE UNIQUE INDEX uq_bookings_source_reference ON bookings(source_reference)")
        conn.execute("CREATE UNIQUE INDEX uq_booking_slots_source_reference ON booking_slots(source_reference)")
        conn.execute("CREATE UNIQUE INDEX uq_time_off_source_reference ON instructor_time_off(source_reference)")
        conn.execute(
            "UPDATE instructor_time_off "
            "SET updated_at = COALESCE(created_at, CURRENT_TIMESTAMP) "
            "WHERE updated_at IS NULL"
        )

        # Normalise prototype-only role labels before enforcing the managed
        # account model. Linked teaching profiles are instructors; all other
        # unknown legacy roles become students for administrator review.
        conn.execute(
            """
            UPDATE users
            SET role = CASE WHEN instructor_id IS NOT NULL THEN 'instructor' ELSE 'student' END
            WHERE role NOT IN ('student', 'booking_agent', 'instructor', 'admin')
            """
        )

        _assert_unambiguous_login_identities(conn)

        # Trigger definitions evolve with the booking model. Recreate the two
        # overlap guards so upgraded databases gain private service padding.
        conn.executescript(
            """
            DROP TRIGGER IF EXISTS prevent_approved_booking_overlap_insert;
            DROP TRIGGER IF EXISTS prevent_approved_booking_overlap_update;
            DROP TRIGGER IF EXISTS validate_booking_status_insert;
            DROP TRIGGER IF EXISTS validate_booking_status_update;
            DROP TRIGGER IF EXISTS validate_user_role_insert;
            DROP TRIGGER IF EXISTS validate_user_role_update;
            """
        )

        conn.executescript(
            """
            DROP INDEX IF EXISTS idx_users_email_unique;
            CREATE INDEX IF NOT EXISTS idx_users_email_lookup
                ON users(lower(email)) WHERE email IS NOT NULL AND email != '';
            CREATE UNIQUE INDEX IF NOT EXISTS idx_users_username_unique_ci
                ON users(lower(username));
            CREATE INDEX IF NOT EXISTS idx_bookings_date_branch
                ON bookings(branch_id, target_date);
            CREATE INDEX IF NOT EXISTS idx_bookings_instructor_status
                ON bookings(instructor_id, validation_status, target_date);
            CREATE INDEX IF NOT EXISTS idx_bookings_student
                ON bookings(student_user_id, target_date);
            CREATE INDEX IF NOT EXISTS idx_bookings_series
                ON bookings(series_id, series_position);
            CREATE INDEX IF NOT EXISTS idx_audit_booking
                ON audit_events(booking_id, created_at);
            CREATE INDEX IF NOT EXISTS idx_assignments_instructor_active
                ON student_instructor_assignments(instructor_id, is_active, student_user_id);
            CREATE INDEX IF NOT EXISTS idx_assignments_student_active
                ON student_instructor_assignments(student_user_id, is_active, instructor_id);
            CREATE INDEX IF NOT EXISTS idx_weekly_availability_instructor
                ON instructor_weekly_availability(instructor_id, weekday, start_time);
            CREATE INDEX IF NOT EXISTS idx_time_off_instructor_date
                ON instructor_time_off(instructor_id, target_date, start_time);
            CREATE INDEX IF NOT EXISTS idx_time_off_series
                ON instructor_time_off(series_id, series_position);
            CREATE INDEX IF NOT EXISTS idx_default_lunch_exceptions_date
                ON default_lunch_exceptions(target_date, instructor_id);
            CREATE INDEX IF NOT EXISTS idx_services_branch_active
                ON services(branch_id, is_active, name);
            CREATE INDEX IF NOT EXISTS idx_booking_services_booking
                ON booking_services(booking_id, sort_order);
            CREATE INDEX IF NOT EXISTS idx_intake_fields_service
                ON service_intake_fields(service_id, is_active, sort_order);
            CREATE INDEX IF NOT EXISTS idx_intake_values_booking
                ON booking_intake_values(booking_id);
            CREATE INDEX IF NOT EXISTS idx_notifications_due
                ON notification_queue(status, next_attempt_at, scheduled_for);
            CREATE INDEX IF NOT EXISTS idx_client_profiles_reminders
                ON client_profiles(reminders_enabled, preferred_channel);
            CREATE INDEX IF NOT EXISTS idx_client_profiles_secondary_email
                ON client_profiles(lower(secondary_email))
                WHERE secondary_email IS NOT NULL AND secondary_email != '';
            CREATE INDEX IF NOT EXISTS idx_client_profiles_secondary_phone
                ON client_profiles(secondary_phone)
                WHERE secondary_phone IS NOT NULL AND secondary_phone != '';

            CREATE TRIGGER IF NOT EXISTS validate_user_role_insert
            BEFORE INSERT ON users
            WHEN NEW.role NOT IN ('student', 'booking_agent', 'instructor', 'admin')
            BEGIN
                SELECT RAISE(ABORT, 'invalid user role');
            END;

            CREATE TRIGGER IF NOT EXISTS validate_user_role_update
            BEFORE UPDATE OF role ON users
            WHEN NEW.role NOT IN ('student', 'booking_agent', 'instructor', 'admin')
            BEGIN
                SELECT RAISE(ABORT, 'invalid user role');
            END;

            CREATE TRIGGER IF NOT EXISTS validate_user_instructor_link_insert
            BEFORE INSERT ON users
            WHEN (NEW.role = 'instructor' AND NEW.instructor_id IS NULL)
              OR (NEW.role != 'instructor' AND NEW.instructor_id IS NOT NULL)
            BEGIN
                SELECT RAISE(ABORT, 'instructor role and profile must match');
            END;

            CREATE TRIGGER IF NOT EXISTS validate_user_instructor_link_update
            BEFORE UPDATE OF role, instructor_id ON users
            WHEN (NEW.role = 'instructor' AND NEW.instructor_id IS NULL)
              OR (NEW.role != 'instructor' AND NEW.instructor_id IS NOT NULL)
            BEGIN
                SELECT RAISE(ABORT, 'instructor role and profile must match');
            END;

            CREATE TRIGGER IF NOT EXISTS validate_assignment_insert
            BEFORE INSERT ON student_instructor_assignments
            WHEN (SELECT role FROM users WHERE id = NEW.student_user_id) != 'student'
              OR (SELECT branch_id FROM users WHERE id = NEW.student_user_id)
                 != (SELECT branch_id FROM instructors WHERE id = NEW.instructor_id)
            BEGIN
                SELECT RAISE(ABORT, 'assignment people must be a student and same-branch instructor');
            END;

            CREATE TRIGGER IF NOT EXISTS validate_assignment_reactivate
            BEFORE UPDATE OF is_active, student_user_id, instructor_id
            ON student_instructor_assignments
            WHEN NEW.is_active = 1 AND (
                (SELECT role FROM users WHERE id = NEW.student_user_id) != 'student'
                OR (SELECT branch_id FROM users WHERE id = NEW.student_user_id)
                   != (SELECT branch_id FROM instructors WHERE id = NEW.instructor_id)
            )
            BEGIN
                SELECT RAISE(ABORT, 'assignment people must be a student and same-branch instructor');
            END;

            CREATE TRIGGER IF NOT EXISTS validate_instructor_verification_insert
            BEFORE INSERT ON instructors
            WHEN NEW.verification_status NOT IN ('unverified', 'verified')
            BEGIN
                SELECT RAISE(ABORT, 'invalid instructor verification status');
            END;

            CREATE TRIGGER IF NOT EXISTS validate_instructor_verification_update
            BEFORE UPDATE OF verification_status ON instructors
            WHEN NEW.verification_status NOT IN ('unverified', 'verified')
            BEGIN
                SELECT RAISE(ABORT, 'invalid instructor verification status');
            END;

            CREATE TRIGGER IF NOT EXISTS validate_instructor_verifier_insert
            BEFORE INSERT ON instructors
            WHEN NEW.verified_by IS NOT NULL AND NOT EXISTS (
                SELECT 1 FROM users
                WHERE id = NEW.verified_by AND role = 'admin' AND is_active = 1
            )
            BEGIN
                SELECT RAISE(ABORT, 'instructor verifier must be an active administrator');
            END;

            CREATE TRIGGER IF NOT EXISTS validate_instructor_verifier_update
            BEFORE UPDATE OF verified_by ON instructors
            WHEN NEW.verified_by IS NOT NULL AND NOT EXISTS (
                SELECT 1 FROM users
                WHERE id = NEW.verified_by AND role = 'admin' AND is_active = 1
            )
            BEGIN
                SELECT RAISE(ABORT, 'instructor verifier must be an active administrator');
            END;

            CREATE TRIGGER IF NOT EXISTS validate_weekday_insert
            BEFORE INSERT ON instructor_weekly_availability
            WHEN NEW.weekday < 0 OR NEW.weekday > 6 OR NEW.start_time >= NEW.end_time
            BEGIN
                SELECT RAISE(ABORT, 'invalid weekly availability');
            END;

            CREATE TRIGGER IF NOT EXISTS validate_weekday_update
            BEFORE UPDATE OF weekday, start_time, end_time ON instructor_weekly_availability
            WHEN NEW.weekday < 0 OR NEW.weekday > 6 OR NEW.start_time >= NEW.end_time
            BEGIN
                SELECT RAISE(ABORT, 'invalid weekly availability');
            END;

            DROP TRIGGER IF EXISTS validate_booking_status_insert;
            DROP TRIGGER IF EXISTS validate_booking_status_update;

            CREATE TRIGGER validate_booking_status_insert
            BEFORE INSERT ON bookings
            WHEN NEW.validation_status NOT IN
                ('Pending', 'Approved', 'Not Confirmed', 'Rejected', 'Cancelled',
                 'Completed', 'No-show', 'Running Late', 'Arrived', 'Rescheduled',
                 'No Action')
            BEGIN
                SELECT RAISE(ABORT, 'invalid booking status');
            END;

            CREATE TRIGGER validate_booking_status_update
            BEFORE UPDATE OF validation_status ON bookings
            WHEN NEW.validation_status NOT IN
                ('Pending', 'Approved', 'Not Confirmed', 'Rejected', 'Cancelled',
                 'Completed', 'No-show', 'Running Late', 'Arrived', 'Rescheduled',
                 'No Action')
            BEGIN
                SELECT RAISE(ABORT, 'invalid booking status');
            END;

            CREATE TRIGGER IF NOT EXISTS validate_booking_branch_insert
            BEFORE INSERT ON bookings
            WHEN (SELECT branch_id FROM machines WHERE id = NEW.machine_id) != NEW.branch_id
              OR (SELECT branch_id FROM instructors WHERE id = NEW.instructor_id) != NEW.branch_id
            BEGIN
                SELECT RAISE(ABORT, 'booking resources must belong to the branch');
            END;

            CREATE TRIGGER IF NOT EXISTS validate_booking_branch_update
            BEFORE UPDATE OF machine_id, instructor_id, branch_id ON bookings
            WHEN (SELECT branch_id FROM machines WHERE id = NEW.machine_id) != NEW.branch_id
              OR (SELECT branch_id FROM instructors WHERE id = NEW.instructor_id) != NEW.branch_id
            BEGIN
                SELECT RAISE(ABORT, 'booking resources must belong to the branch');
            END;

            CREATE TRIGGER IF NOT EXISTS prevent_approved_booking_overlap_insert
            BEFORE INSERT ON bookings
            WHEN NEW.validation_status = 'Approved'
              AND COALESCE(NEW.allow_double_booking, 0) = 0 AND EXISTS (
                SELECT 1 FROM bookings b
                WHERE b.target_date = NEW.target_date
                  AND b.validation_status = 'Approved'
                  AND (
                    (
                      NEW.student_user_id IS NOT NULL
                      AND b.student_user_id = NEW.student_user_id
                      AND NEW.start_time < b.end_time
                      AND NEW.end_time > b.start_time
                    )
                    OR (
                      (b.machine_id = NEW.machine_id
                       OR b.instructor_id = NEW.instructor_id)
                      AND (
                        CAST(substr(NEW.start_time, 1, 2) AS INTEGER) * 60
                        + CAST(substr(NEW.start_time, 4, 2) AS INTEGER)
                        - COALESCE(NEW.buffer_before_minutes, 0)
                      ) < (
                        CAST(substr(b.end_time, 1, 2) AS INTEGER) * 60
                        + CAST(substr(b.end_time, 4, 2) AS INTEGER)
                        + COALESCE(b.buffer_after_minutes, 0)
                      )
                      AND (
                        CAST(substr(NEW.end_time, 1, 2) AS INTEGER) * 60
                        + CAST(substr(NEW.end_time, 4, 2) AS INTEGER)
                        + COALESCE(NEW.buffer_after_minutes, 0)
                      ) > (
                        CAST(substr(b.start_time, 1, 2) AS INTEGER) * 60
                        + CAST(substr(b.start_time, 4, 2) AS INTEGER)
                        - COALESCE(b.buffer_before_minutes, 0)
                      )
                    )
                  )
            )
            BEGIN
                SELECT RAISE(ABORT, 'approved booking overlaps an existing booking');
            END;

            CREATE TRIGGER IF NOT EXISTS prevent_approved_booking_overlap_update
            BEFORE UPDATE OF validation_status, target_date, start_time, end_time,
                             machine_id, instructor_id, student_user_id,
                             buffer_before_minutes, buffer_after_minutes,
                             allow_double_booking ON bookings
            WHEN NEW.validation_status = 'Approved'
              AND COALESCE(NEW.allow_double_booking, 0) = 0 AND EXISTS (
                SELECT 1 FROM bookings b
                WHERE b.id != NEW.id
                  AND b.target_date = NEW.target_date
                  AND b.validation_status = 'Approved'
                  AND (
                    (
                      NEW.student_user_id IS NOT NULL
                      AND b.student_user_id = NEW.student_user_id
                      AND NEW.start_time < b.end_time
                      AND NEW.end_time > b.start_time
                    )
                    OR (
                      (b.machine_id = NEW.machine_id
                       OR b.instructor_id = NEW.instructor_id)
                      AND (
                        CAST(substr(NEW.start_time, 1, 2) AS INTEGER) * 60
                        + CAST(substr(NEW.start_time, 4, 2) AS INTEGER)
                        - COALESCE(NEW.buffer_before_minutes, 0)
                      ) < (
                        CAST(substr(b.end_time, 1, 2) AS INTEGER) * 60
                        + CAST(substr(b.end_time, 4, 2) AS INTEGER)
                        + COALESCE(b.buffer_after_minutes, 0)
                      )
                      AND (
                        CAST(substr(NEW.end_time, 1, 2) AS INTEGER) * 60
                        + CAST(substr(NEW.end_time, 4, 2) AS INTEGER)
                        + COALESCE(NEW.buffer_after_minutes, 0)
                      ) > (
                        CAST(substr(b.start_time, 1, 2) AS INTEGER) * 60
                        + CAST(substr(b.start_time, 4, 2) AS INTEGER)
                        - COALESCE(b.buffer_before_minutes, 0)
                      )
                    )
                  )
            )
            BEGIN
                SELECT RAISE(ABORT, 'approved booking overlaps an existing booking');
            END;
            """
        )


def seed_reference_data() -> None:
    """Seed public branch/resources and, only when requested, demo people.

    A2Z's public website does not publish an instructor roster. Fresh
    installations therefore never create real-looking staff accounts from an
    unverifiable list. The legacy demo roster remains available behind an
    explicit development flag so old tests and disposable demos can run.
    """
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT OR IGNORE INTO branches (name, address, phone)
            VALUES (?, ?, ?)
            """,
            (
                "Willingdon Island",
                "Near Old Harbour Bridge, Mattanchery Halt, Willingdon Island, Kerala",
                "+91 96335 79475",
            ),
        )
        cur.execute(
            """
            UPDATE branches
            SET address = COALESCE(NULLIF(address, ''), ?),
                phone = COALESCE(NULLIF(phone, ''), ?)
            WHERE name = ?
            """,
            (
                "Near Old Harbour Bridge, Mattanchery Halt, Willingdon Island, Kerala",
                "+91 96335 79475",
                "Willingdon Island",
            ),
        )
        branch_id = cur.execute(
            "SELECT id FROM branches WHERE name = ?", ("Willingdon Island",)
        ).fetchone()["id"]

        machines = [
            ("FORKLIFT MANUAL", "Forklift", "Track"),
            ("TRAILER - TEST TRIAL", "Trailer", "Track"),
            ("ELECTRIC FORKLIFT", "Forklift", "Track"),
            ("ZOOMLION CRANE", "Crane", "Track"),
            ("20 TRAILER", "Trailer", "Track"),
            ("HIGH REACH TRUCK", "Warehouse equipment", "Track"),
            ("JCB", "Backhoe loader", "Track"),
            ("FORKLIFT AUTOMATIC", "Forklift", "Track"),
            ("HITACHI", "Excavator", "Track"),
            ("BOBCAT", "Skid-steer loader", "Track"),
            ("ROUGH TERRAIN", "Crane", "Track"),
            ("HYDRA", "Crane", "Track"),
            ("MOBILE TOWER", "Crane", "Track"),
            ("FIXED TOWER", "Crane", "Track"),
            ("JEEP TRAILER", "Trailer", "Track"),
            ("COUPLING", "Trailer", "Track"),
            ("TRAILER", "Trailer", "Track"),
            ("HEAVY TELESCOPIC", "Crane", "Track"),
            ("BUS", "Heavy vehicle", "Parking Yard"),
            ("BUS - T", "Heavy vehicle", "Parking Yard"),
            ("BUS ROAD CLASS", "Heavy vehicle", "Parking Yard"),
            ("TRAILER - TEST PRACTICE", "Trailer", "Parking Yard"),
        ]
        for label, category, location in machines:
            code = re.sub(r"-+", "-", re.sub(r"[^A-Z0-9]+", "-", label)).strip("-")
            cur.execute(
                """
                INSERT OR IGNORE INTO machines
                    (machine_code, category, location, branch_id)
                VALUES (?, ?, ?, ?)
                """,
                (code, category, location, branch_id),
            )

        # Services drive the customer-facing booking sequence. Existing A2Z
        # equipment remains the scarce resource underneath each service.
        service_colours = (
            "#C8141B",
            "#2F6B9A",
            "#7A4EAB",
            "#237A57",
            "#B36B16",
            "#6B7280",
            "#0F766E",
        )
        categories = [
            row["category"]
            for row in cur.execute(
                """
                SELECT DISTINCT category FROM machines
                WHERE branch_id = ? ORDER BY lower(category)
                """,
                (branch_id,),
            ).fetchall()
        ]
        for position, category in enumerate(categories):
            service_name = f"{category} practical training"
            cur.execute(
                """
                INSERT OR IGNORE INTO services
                    (branch_id, name, description, category, duration_minutes,
                     price_cents, currency, buffer_before_minutes,
                     buffer_after_minutes, color, available_weekdays,
                     requires_approval)
                VALUES (?, ?, ?, ?, 60, 0, 'INR', 0, 0, ?, '0,1,2,3,4,5', 0)
                """,
                (
                    branch_id,
                    service_name,
                    f"One-to-one supervised {category.lower()} practice.",
                    category,
                    service_colours[position % len(service_colours)],
                ),
            )
            service_id = cur.execute(
                "SELECT id FROM services WHERE branch_id = ? AND name = ?",
                (branch_id, service_name),
            ).fetchone()["id"]
            cur.execute(
                """
                INSERT OR IGNORE INTO service_machines (service_id, machine_id)
                SELECT ?, id FROM machines
                WHERE branch_id = ? AND category = ?
                """,
                (service_id, branch_id, category),
            )
            cur.execute(
                """
                INSERT OR IGNORE INTO service_intake_fields
                    (service_id, field_key, label, field_type, help_text,
                     placeholder, is_required, options_json, sort_order)
                VALUES (?, 'experience_level', 'Current experience',
                        'select', 'This helps the instructor prepare.',
                        NULL, 1,
                        '["First session","Some practice","Assessment preparation"]',
                        10)
                """,
                (service_id,),
            )
            cur.execute(
                """
                INSERT OR IGNORE INTO service_intake_fields
                    (service_id, field_key, label, field_type, help_text,
                     placeholder, is_required, sort_order)
                VALUES (?, 'training_goal', 'What would you like to work on?',
                        'textarea', NULL,
                        'Tell the instructor what you want to practise.',
                        0, 20)
                """,
                (service_id,),
            )
            cur.execute(
                """
                INSERT OR IGNORE INTO service_intake_fields
                    (service_id, field_key, label, field_type, help_text,
                     is_required, sort_order)
                VALUES (?, 'safety_confirmation', 'Safety declaration',
                        'checkbox',
                        'I will follow the instructor and site safety rules.',
                        1, 30)
                """,
                (service_id,),
            )

        demo_instructor_ids = []
        if os.environ.get("A2Z_SEED_DEMO_DATA", "0") == "1":
            instructors = [
                "Demo Instructor One",
                "Demo Instructor Two",
            ]
            instructor_password = os.environ.get("A2Z_INSTRUCTOR_PASSWORD")
            if not instructor_password:
                raise RuntimeError(
                    "A2Z_INSTRUCTOR_PASSWORD is required when demo data is enabled."
                )
            for name in instructors:
                cur.execute(
                    """
                    INSERT OR IGNORE INTO instructors
                        (name, branch_id, verification_status, verified_at)
                    VALUES (?, ?, 'verified', CURRENT_TIMESTAMP)
                    """,
                    (name, branch_id),
                )
                instructor_id = cur.execute(
                    "SELECT id FROM instructors WHERE name = ? AND branch_id = ?",
                    (name, branch_id),
                ).fetchone()["id"]
                demo_instructor_ids.append(instructor_id)
                username = re.sub(r"[^A-Z0-9]+", "_", name.upper()).strip("_")
                cur.execute(
                    """
                    INSERT OR IGNORE INTO users
                        (username, password_hash, role, instructor_id, full_name,
                         branch_id, must_change_password)
                    VALUES (?, ?, 'instructor', ?, ?, ?, 0)
                    """,
                    (
                        username,
                        generate_password_hash(instructor_password),
                        instructor_id,
                        name.title(),
                        branch_id,
                    ),
                )
                cur.execute(
                    """
                    UPDATE users SET full_name = COALESCE(NULLIF(full_name, ''), ?),
                        branch_id = COALESCE(branch_id, ?), instructor_id = ?,
                        must_change_password = 0
                    WHERE username = ?
                    """,
                    (name.title(), branch_id, instructor_id, username),
                )
        configured_admin_password = os.environ.get("A2Z_ADMIN_PASSWORD")
        if not configured_admin_password:
            raise RuntimeError("A2Z_ADMIN_PASSWORD must be configured before startup.")
        admin_password = configured_admin_password
        admin_must_change = 0
        cur.execute(
            """
            INSERT OR IGNORE INTO users
                (username, password_hash, role, full_name, email, branch_id,
                 must_change_password)
            VALUES ('admin', ?, 'admin', 'Operations Admin', 'admin@a2z.local', ?, ?)
            """,
            (generate_password_hash(admin_password), branch_id, admin_must_change),
        )
        cur.execute(
            """
            UPDATE users SET full_name = COALESCE(NULLIF(full_name, ''), 'Operations Admin'),
                email = COALESCE(NULLIF(email, ''), 'admin@a2z.local'),
                branch_id = COALESCE(branch_id, ?)
            WHERE username = 'admin'
            """,
            (branch_id,),
        )
        if not cur.execute(
            "SELECT 1 FROM users WHERE role = 'admin' AND is_active = 1 LIMIT 1"
        ).fetchone():
            raise RuntimeError(
                "No active administrator account exists. Resolve the conflicting "
                "'admin' username or restore an administrator before startup."
            )

        if os.environ.get("A2Z_SEED_DEMO_STUDENT", "0") == "1":
            student_password = os.environ.get("A2Z_STUDENT_PASSWORD")
            if not student_password:
                raise RuntimeError(
                    "A2Z_STUDENT_PASSWORD is required when the demo student is enabled."
                )
            cur.execute(
                """
                INSERT OR IGNORE INTO users
                    (username, password_hash, role, full_name, email, phone,
                     branch_id, login_enabled, must_change_password)
                VALUES ('student', ?, 'student', 'Demo Student',
                        'student@example.invalid', '0000000000', ?, ?, 0)
                """,
                (
                    generate_password_hash(student_password),
                    branch_id,
                    1,
                ),
            )
            cur.execute(
                """
                UPDATE users SET login_enabled = ?
                WHERE username = 'student' AND role = 'student'
                """,
                (1,),
            )
            student_row = cur.execute(
                "SELECT id FROM users WHERE username = 'student'"
            ).fetchone()
            if student_row and demo_instructor_ids:
                admin_row = cur.execute(
                    "SELECT id FROM users WHERE username = 'admin'"
                ).fetchone()
                cur.execute(
                    """
                    INSERT OR IGNORE INTO student_instructor_assignments
                        (student_user_id, instructor_id, assigned_by)
                    VALUES (?, ?, ?)
                    """,
                    (student_row["id"], demo_instructor_ids[0], admin_row["id"]),
                )

        # Import historical pairs as inactive review suggestions. A rejected
        # or old booking must never silently grant present-day access.
        cur.execute(
            """
            INSERT OR IGNORE INTO student_instructor_assignments
                (student_user_id, instructor_id, assigned_by, is_active, ended_at)
            SELECT DISTINCT b.student_user_id, b.instructor_id, NULL, 0,
                   CURRENT_TIMESTAMP
            FROM bookings b
            JOIN users u ON u.id = b.student_user_id AND u.role = 'student'
            WHERE b.student_user_id IS NOT NULL
            """
        )


# Backwards-compatible name used by the original project.
seed_sample_data = seed_reference_data


if __name__ == "__main__":
    init_db()
    seed_reference_data()
