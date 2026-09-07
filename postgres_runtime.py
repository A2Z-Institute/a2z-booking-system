"""Small SQLite-compatibility layer used while A2Z runs on PostgreSQL.

The web application historically calls ``conn.execute(sql, parameters)`` and
uses SQLite ``?`` placeholders.  Keeping that public interface lets the
application move to PostgreSQL without a risky, one-shot rewrite of every
route.  This module deliberately handles only SQL emitted by the application;
it is not a general SQL converter.
"""

from __future__ import annotations

import re
from typing import Any

import psycopg
from psycopg.rows import RowFactory


class CompatibleRow(dict):
    """Mapping rows with SQLite's useful numeric-index compatibility."""

    def __getitem__(self, key):
        if isinstance(key, int):
            return tuple(self.values())[key]
        return super().__getitem__(key)


def compatible_row(cursor) -> RowFactory[CompatibleRow]:
    if cursor.description is None:
        return lambda _values: CompatibleRow()

    names = [column.name for column in cursor.description]

    def make_row(values):
        return CompatibleRow(zip(names, values))

    return make_row


_INSERT_OR_IGNORE = re.compile(r"^\s*INSERT\s+OR\s+IGNORE\s+", re.IGNORECASE)
_SQLITE_BEGIN = re.compile(
    r"^\s*BEGIN\s+(?:IMMEDIATE|EXCLUSIVE)\s*;?\s*$", re.IGNORECASE
)


def translate_sql(statement: str) -> str:
    """Translate the few SQLite dialect pieces used by A2Z routes."""
    sql = statement
    # SQLite write routes use BEGIN IMMEDIATE to reserve the database before
    # changing rows. PostgreSQL provides transaction isolation and row locks,
    # and accepts BEGIN but not SQLite's IMMEDIATE/EXCLUSIVE modifiers.
    if _SQLITE_BEGIN.match(sql):
        sql = "BEGIN"
    if _INSERT_OR_IGNORE.match(sql):
        sql = _INSERT_OR_IGNORE.sub("INSERT ", sql)
        sql = sql.rstrip().rstrip(";") + " ON CONFLICT DO NOTHING"
    sql = sql.replace("date('now')", "CURRENT_DATE::text")
    # SQLite calls its string aggregate ``group_concat``. PostgreSQL uses the
    # equivalent ``string_agg`` with the same two-argument form used by A2Z.
    sql = re.sub(r"\bgroup_concat\s*\(", "string_agg(", sql, flags=re.IGNORECASE)
    sql = re.sub(
        r"CAST\(strftime\('%w',\s*([^)]+)\)\s+AS\s+INTEGER\)",
        r"EXTRACT(DOW FROM \1)::INTEGER",
        sql,
        flags=re.IGNORECASE,
    )
    # The A2Z project uses only positional DB-API parameters. Psycopg uses
    # %s. A literal question mark is not used in project queries.
    sql = sql.replace("?", "%s")
    return sql


class Cursor:
    def __init__(self, cursor, connection, inserted_id: int | None = None):
        self._cursor = cursor
        self._connection = connection
        self._inserted_id = inserted_id

    @property
    def lastrowid(self):
        if self._inserted_id is None:
            # PostgreSQL's LASTVAL() is scoped to this connection. It is the
            # equivalent of SQLite's lastrowid for the immediately preceding
            # INSERT into an identity-backed A2Z table.
            row = self._connection.execute("SELECT LASTVAL() AS id").fetchone()
            self._inserted_id = row["id"]
        return self._inserted_id

    @property
    def rowcount(self):
        return self._cursor.rowcount

    def fetchone(self):
        return self._cursor.fetchone()

    def fetchall(self):
        return self._cursor.fetchall()

    def __iter__(self):
        return iter(self._cursor)


class Connection:
    """Connection facade mirroring the SQLite operations used by A2Z."""

    def __init__(self, connection):
        self._connection = connection

    def execute(self, statement: str, parameters: tuple | list | None = None) -> Cursor:
        translated = translate_sql(statement)
        cursor = self._connection.execute(translated, parameters or ())
        inserted_id = None
        # App routes use cursor.lastrowid for inserts into tables with `id`.
        # Ask PostgreSQL for the generated id only for those particular simple
        # inserts. The retry leaves ordinary INSERT ... SELECT unchanged.
        if re.match(r"^\s*INSERT\s+INTO\s+(?:\w+)", translated, re.IGNORECASE):
            # Psycopg does not expose SQLite's lastrowid. Routes that require
            # it explicitly append RETURNING id through execute_insert().
            pass
        return Cursor(cursor, self._connection, inserted_id)

    def execute_insert(self, statement: str, parameters: tuple | list | None = None) -> Cursor:
        translated = translate_sql(statement).rstrip().rstrip(";")
        if " RETURNING " not in translated.upper():
            translated += " RETURNING id"
        cursor = self._connection.execute(translated, parameters or ())
        row = cursor.fetchone()
        return Cursor(cursor, self._connection, row["id"] if row else None)

    def executemany(self, statement: str, parameters_seq) -> Cursor:
        cursor = self._connection.cursor()
        cursor.executemany(translate_sql(statement), parameters_seq)
        return Cursor(cursor, self._connection)

    def commit(self):
        self._connection.commit()

    def rollback(self):
        self._connection.rollback()

    def close(self):
        self._connection.close()


def connect(database_url: str) -> Connection:
    return Connection(psycopg.connect(database_url, row_factory=compatible_row))
