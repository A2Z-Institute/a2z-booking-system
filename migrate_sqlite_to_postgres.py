"""Copy an A2Z SQLite database into a *new* PostgreSQL database safely.

This does not modify the source SQLite file.  A preview is the default; actual
writing needs BOTH --apply and --replace-target, so it cannot accidentally
overwrite a production database.

Before using --apply, create a fresh PostgreSQL database and load
postgres_schema.sql.  The Flask app must be switched to the PostgreSQL-ready
release separately; this tool only copies and validates data.
"""

from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from collections import OrderedDict
from pathlib import Path

try:
    import psycopg
    from psycopg import sql
except ImportError:  # Preview mode only needs Python's built-in sqlite3.
    psycopg = None
    sql = None


TABLE_ORDER = (
    "branches", "machines", "instructors", "users", "services",
    "service_machines", "service_instructors", "service_intake_fields",
    "bookings", "booking_services", "booking_intake_values", "client_profiles",
    "instructor_weekly_availability", "instructor_time_off",
    "default_lunch_exceptions", "default_break_exceptions", "booking_slots",
    "notification_queue", "audit_events", "student_instructor_assignments",
    "schema_migrations",
)


def source_connection(path: Path) -> sqlite3.Connection:
    if not path.is_file():
        raise SystemExit(f"SQLite database was not found: {path}")
    conn = sqlite3.connect(f"file:{path.resolve()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    result = conn.execute("PRAGMA integrity_check").fetchone()[0]
    if result != "ok":
        raise SystemExit(f"SQLite integrity check failed: {result}")
    return conn


def source_tables(conn: sqlite3.Connection) -> set[str]:
    return {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}


def counts(conn: sqlite3.Connection) -> OrderedDict[str, int]:
    found = source_tables(conn)
    return OrderedDict(
        (table, conn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0])
        for table in TABLE_ORDER if table in found
    )


def target_counts(conn) -> OrderedDict[str, int]:
    return OrderedDict(
        (table, conn.execute(sql.SQL("SELECT COUNT(*) FROM {}").format(sql.Identifier(table))).fetchone()[0])
        for table in TABLE_ORDER
    )


def validate_target_schema(conn) -> None:
    actual = {
        row[0] for row in conn.execute(
            "SELECT tablename FROM pg_catalog.pg_tables WHERE schemaname = 'public'"
        )
    }
    missing = [table for table in TABLE_ORDER if table not in actual]
    if missing:
        raise SystemExit(
            "Target PostgreSQL schema is incomplete. Load postgres_schema.sql first. "
            f"Missing: {', '.join(missing)}"
        )


def copy_table(source: sqlite3.Connection, target, table: str) -> int:
    columns = [row[1] for row in source.execute(f'PRAGMA table_info("{table}")')]
    if not columns:
        return 0
    rows = source.execute(f'SELECT * FROM "{table}"').fetchall()
    if not rows:
        return 0
    statement = sql.SQL("INSERT INTO {} ({}) VALUES ({})").format(
        sql.Identifier(table),
        sql.SQL(", ").join(map(sql.Identifier, columns)),
        sql.SQL(", ").join(sql.Placeholder() for _ in columns),
    )
    # Psycopg accepts SQLite's None/int/text/blob values directly.
    with target.cursor() as cursor:
        cursor.executemany(
            statement,
            [tuple(row[column] for column in columns) for row in rows],
        )
    return len(rows)


def reset_sequences(target) -> None:
    # All identity columns are named id. setval keeps the next inserted record
    # above the imported ids instead of reusing an existing record id.
    for table in TABLE_ORDER:
        target.execute(
            "SELECT setval(pg_get_serial_sequence(%s, 'id'), "
            "COALESCE((SELECT MAX(id) FROM " + table + "), 1), true) "
            "WHERE pg_get_serial_sequence(%s, 'id') IS NOT NULL",
            (table, table),
        )


def print_counts(title: str, values: OrderedDict[str, int]) -> None:
    print(title)
    for name, total in values.items():
        print(f"  {name:38} {total:,}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("sqlite_database", type=Path, help="Fresh SQLite backup (.db), never the live mounted file")
    parser.add_argument("--database-url", default=os.environ.get("A2Z_POSTGRES_URL"), help="Target PostgreSQL URL (or set A2Z_POSTGRES_URL)")
    parser.add_argument("--apply", action="store_true", help="Write to the new PostgreSQL database")
    parser.add_argument("--replace-target", action="store_true", help="Allow truncating the target before import")
    args = parser.parse_args()

    src = source_connection(args.sqlite_database)
    try:
        before = counts(src)
        print_counts("Verified SQLite source totals:", before)
        if not args.apply:
            print("\nPreview only. No PostgreSQL data was changed. Use --apply --replace-target only for the NEW target database.")
            return 0
        if not args.replace_target:
            raise SystemExit("Safety stop: --apply requires --replace-target. This protects an existing target database.")
        if not args.database_url:
            raise SystemExit("Set A2Z_POSTGRES_URL or provide --database-url for the new PostgreSQL database.")
        if psycopg is None:
            raise SystemExit("Install PostgreSQL support first: pip install 'psycopg[binary]>=3.2,<4'")

        with psycopg.connect(args.database_url) as pg:
            validate_target_schema(pg)
            # The source database legitimately has a circular relationship:
            # instructors.verified_by -> users and users.instructor_id ->
            # instructors. Both constraints are deferred in postgres_schema.sql.
            pg.execute("SET CONSTRAINTS ALL DEFERRED")
            existing = target_counts(pg)
            if any(existing.values()):
                print_counts("\nTarget currently contains:", existing)
            pg.execute("TRUNCATE TABLE " + ", ".join(TABLE_ORDER) + " RESTART IDENTITY CASCADE")
            for table in before:
                copied = copy_table(src, pg, table)
                print(f"Imported {table}: {copied:,}")
            reset_sequences(pg)
            after = target_counts(pg)
            if before != after:
                print_counts("\nExpected totals:", before)
                print_counts("Actual PostgreSQL totals:", after)
                raise RuntimeError("Migration verification failed; the PostgreSQL transaction was rolled back.")
            print_counts("\nPostgreSQL totals verified:", after)
        print("\nMigration completed successfully. Keep the SQLite server running until application tests and sign-off are complete.")
        return 0
    finally:
        src.close()


if __name__ == "__main__":
    raise SystemExit(main())
