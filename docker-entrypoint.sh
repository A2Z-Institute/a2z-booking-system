#!/bin/sh
set -eu

database_file="${A2Z_DATABASE:-/data/a2z_booking.db}"
database_directory="$(dirname "$database_file")"
backup_directory="${A2Z_BACKUP_DIR:-/data/backups}"

mkdir -p "$database_directory"
mkdir -p "$backup_directory"
chown a2z:a2z "$database_directory" "$backup_directory"

if [ -n "${A2Z_POSTGRES_URL:-}" ]; then
    # PostgreSQL deployments do not have a SQLite database file.  Never try
    # to chown the configured SQLite fallback path in that mode: with `set -e`
    # a missing /data/a2z_booking.db would stop the container before the web
    # server can start.
    A2Z_BACKUP_DIR="$backup_directory" \
    A2Z_BACKUP_ONCE_DAILY=1 \
    A2Z_BACKUP_RETENTION="${A2Z_BACKUP_RETENTION:-30}" \
      gosu a2z python /app/backup_database.py \
      || echo "A2Z backup warning: startup backup failed; the background monitor will retry." >&2
elif [ -e "$database_file" ]; then
    chown a2z:a2z "$database_file"
    A2Z_BACKUP_DIR="$backup_directory" \
    A2Z_BACKUP_ONCE_DAILY=1 \
    A2Z_BACKUP_RETENTION="${A2Z_BACKUP_RETENTION:-30}" \
      gosu a2z python /app/backup_database.py \
      || echo "A2Z backup warning: startup backup failed; the background monitor will retry." >&2
fi

exec gosu a2z "$@"
