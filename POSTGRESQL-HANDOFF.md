# A2Z PostgreSQL migration package

This package prepares the A2Z scheduler source for a controlled migration
from SQLite to PostgreSQL.  It is **not** a direct replacement for the
currently running KVM 4 application.

## Included preparation

- PostgreSQL schema matching the current A2Z tables.
- A safe SQLite-to-PostgreSQL migration tool with source and target count
  verification.
- PostgreSQL connection support controlled only by `A2Z_POSTGRES_URL`.
- The normal SQLite database remains the default when that variable is absent.

## Do not deploy this package over the live system

Use a new `postgres-migration` Git branch and deploy it only to the new KVM 8
server.  Keep the KVM 4 system on its current SQLite database until all
acceptance tests have passed.

## Safe next steps

1. Copy this package over a fresh clone of the current A2Z repository.
2. Commit it on a new `postgres-migration` branch, not `main`.
3. Deploy that branch to a separate KVM 8 Coolify application.
4. Set `A2Z_POSTGRES_URL` only in the new KVM 8 application.
5. Load `postgres_schema.sql`, then run the migration preview against a fresh
   SQLite backup.
6. Fix any application compatibility issue found during staged testing before
   moving production traffic.

The full runbook is in `POSTGRESQL-MIGRATION.md`.
