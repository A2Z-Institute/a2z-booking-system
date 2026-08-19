# Initial historical restore

These files are the supplied historical backup sources.

On a fresh Coolify deployment, `docker-entrypoint.sh` runs
`import_initial_historical_backup.py` once when the persistent database has
zero bookings and `/data/.initial-backup-imported` does not exist.

Imported:
- historical clients
- instructor/staff roster
- services
- 60,428 appointments
- 3,998 booking slots
- 9,933 break/busy-time records
- 20,252 activity-log records

The import is skipped automatically if the persistent database already contains
bookings, so a later redeploy does not overwrite live data.

IMPORTANT: these source files contain real client/business data. Do not commit
them to a public repository. Keep the repository private or remove these files
after the initial restore if your deployment process allows it.
