# A2Z PostgreSQL migration runbook

This runbook moves a **copy** of A2Z from the current SQLite/Coolify server to
a new PostgreSQL database on the new KVM 8 server. It must be followed in the
order below. The current KVM 4 application remains live until all checks pass.

## Safety rules

1. Do not cancel, reset, or deploy over KVM 4 during this migration.
2. Use a fresh copy of `/data/a2z_booking.db`, not the live mounted file.
3. Treat `--apply --replace-target` as a new-target-only command. It clears
   the target PostgreSQL database before importing.
4. Keep KVM 4 online for at least 7–14 days after the new system goes live.

## Phase 1 — prepare KVM 8

1. Create the new KVM 8 server and install Coolify.
2. Create a PostgreSQL 18 service in Coolify. Do not expose PostgreSQL to the
   public internet.
3. Create a database and user only for A2Z. Store the connection URL in the
   **new application's** environment variables as `A2Z_POSTGRES_URL`.
4. Clone this repository on KVM 8 and deploy a temporary migration utility
   container, or use the Coolify terminal.
5. Load `postgres_schema.sql` into the empty target database:

   ```bash
   psql "$A2Z_POSTGRES_URL" -f /app/postgres_schema.sql
   ```

## Phase 2 — freeze and copy SQLite safely

At a quiet time, temporarily stop new bookings for a few minutes.

1. On KVM 4, make and verify a current SQLite backup:

   ```bash
   docker exec <CURRENT_A2Z_CONTAINER> python /app/backup_database.py
   docker exec <CURRENT_A2Z_CONTAINER> ls -lh /data/backups
   ```

2. Copy the newest `.db` backup to KVM 8. Do not copy `.db-wal` or `.db-shm`.
3. On KVM 8, run the preview first:

   ```bash
   python /app/migrate_sqlite_to_postgres.py /data/import/a2z-final.db
   ```

4. Record the printed totals. They are the source-of-truth comparison.
5. Import into the **empty KVM 8 PostgreSQL database**:

   ```bash
   python /app/migrate_sqlite_to_postgres.py \
     /data/import/a2z-final.db --apply --replace-target
   ```

The importer checks SQLite integrity first and rolls back the PostgreSQL
transaction if the final table totals do not match exactly.

## Phase 3 — application switch and acceptance testing

The Flask runtime needs the PostgreSQL-ready release before it can use the new
database. Do not point the current SQLite-only release at `A2Z_POSTGRES_URL`.

Before changing DNS, test on the KVM 8 preview URL:

- Heavy Equipment and Driving School portals stay separated.
- Super admin, booking agent, and instructor sign-in work.
- Instructor/service/equipment/client/booking totals match the migration log.
- Two booking agents create appointments at the same time.
- Normal conflict checks, allowed double booking, drag/drop, and cancellation
  work correctly.
- Daily PostgreSQL backup works and a restore is tested in a separate database.

## Phase 4 — backup policy

- Daily `pg_dump` retained locally for 30 days.
- One weekly encrypted/exported backup stored outside the KVM 8 server.
- Test restoring one backup each month.

## Phase 5 — DNS cutover

Only after written sign-off:

1. Change the A record for `a2z.magicsignal.online` to KVM 8's IP.
2. Confirm HTTPS, login, both portals, and a newly-created test booking.
3. Leave KVM 4 running for the planned rollback period.
