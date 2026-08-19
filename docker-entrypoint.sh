#!/bin/sh
set -eu

database_file="${A2Z_DATABASE:-/data/a2z_booking.db}"
database_directory="$(dirname "$database_file")"
backup_directory="${A2Z_BACKUP_DIR:-/data/backups}"
initial_backup="${A2Z_INITIAL_BOOKING_BACKUP:-/app/data-import/booking-backup.xlsx}"
initial_activity="${A2Z_INITIAL_ACTIVITY_LOG:-/app/data-import/activity-log.xlsx}"
initial_marker="${A2Z_INITIAL_IMPORT_MARKER:-/data/.initial-backup-imported}"

mkdir -p "$database_directory"
mkdir -p "$backup_directory"
chown a2z:a2z "$database_directory" "$backup_directory"

# Initialize/upgrade the schema before the one-time historical restore.
# This preserves any existing database and its configured administrator.
if [ -f "$initial_backup" ] && [ -f "$initial_activity" ] && [ ! -f "$initial_marker" ]; then
    if [ ! -e "$database_file" ]; then
        echo "No database found; initializing A2Z database before historical restore..."
        gosu a2z python -c 'from database import init_db, seed_reference_data; init_db(); seed_reference_data()'
    else
        booking_count="$(gosu a2z python -c 'import sqlite3, os; p=os.environ.get("A2Z_DATABASE", "/data/a2z_booking.db"); c=sqlite3.connect(p); print(c.execute("SELECT COUNT(*) FROM bookings").fetchone()[0]); c.close()' 2>/dev/null || echo 1)"
        if [ "$booking_count" = "0" ]; then
            echo "Restoring historical bookings, booking slots, breaks, clients, staff and activity log..."
            gosu a2z python -c 'from database import init_db, seed_reference_data; init_db(); seed_reference_data()'
            gosu a2z python /app/import_initial_historical_backup.py
        else
            echo "Existing database contains $booking_count bookings; skipping initial historical restore."
        fi
    fi

    if [ -f "$database_file" ] && [ ! -f "$initial_marker" ]; then
        echo "Restoring historical bookings, booking slots, breaks, clients, staff and activity log..."
        gosu a2z python /app/import_initial_historical_backup.py
    fi
fi

if [ -e "$database_file" ]; then
    chown a2z:a2z "$database_file"
    A2Z_BACKUP_DIR="$backup_directory"     A2Z_BACKUP_ONCE_DAILY=1     A2Z_BACKUP_RETENTION="${A2Z_BACKUP_RETENTION:-30}"       gosu a2z python /app/backup_database.py
fi

exec gosu a2z "$@"
