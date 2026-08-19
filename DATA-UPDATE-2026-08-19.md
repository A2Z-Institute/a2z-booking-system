# Production client and booking update — 19 August 2026

This release contains the cleaned Smart Scheduling export at:

`data-import/A2Z_Clean_Upcoming_Import_2026-08-19.xlsx`

It retains 17,862 client source records and all 2,626 calendar rows dated
19 August 2026 or later. Past appointments are intentionally not imported.

## Safety behaviour

- The release does **not** import data automatically during deployment.
- A dry run checks database integrity and matches all 21 workbook sheets to
  active instructors without writing to the database.
- `--apply` creates and verifies a SQLite backup before importing.
- Smart Scheduling source references make the import repeatable without
  creating a second copy of the same exported booking.
- Existing live bookings and clients are retained.
- Strong client duplicates are merged only when normalized full name plus
  phone, or normalized full name plus email, match.
- Bookings and instructor assignments are reassigned before the duplicate
  account is deactivated.
- Exact duplicate upcoming bookings are cancelled, not deleted, preserving an
  audit trail and recoverability.
- A JSON result report is saved in `A2Z_BACKUP_DIR` (normally
  `/data/backups`).

## Production procedure

1. Extract this package into the local Git repository. Do not copy `.venv`, a
   database file, an `.env` file, or a `backups` folder into Git.
2. Commit and push the files, then redeploy the application in Coolify.
3. Confirm the new container is `healthy`.
4. In Coolify **Terminal**, select the new A2Z application container—not the
   server and not the Coolify container.
5. Run the read-only preflight:

   ```sh
   python reconcile_production_data.py
   ```

6. Continue only when both `missing` and `ambiguous` under
   `instructor_preflight` are empty.
7. Apply the update once:

   ```sh
   python reconcile_production_data.py --apply
   ```

8. Confirm the output contains:

   - `"import_errors": []`
   - `"integrity_check": "ok"`
   - a valid `pre_import_backup` path under `/data/backups`

9. Open the calendar and check several imported appointments for 19 August
   2026 and later.

## Stop conditions

Do not run `--apply` if the dry run lists a missing or ambiguous instructor.
Do not delete the pre-import backup. If `--apply` reports any import error,
keep the application online but do not manually rerun or edit the database;
review the JSON report first.
