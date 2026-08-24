# Importing the Smart Scheduling backup into A2Z Driving School

This is a one-time import for the **A2Z Driving School** portal. It never
changes the Heavy Equipment branch.

## What is imported

- All clients from the `Clients` sheet.
- Every instructor sheet as an active Driving School instructor.
- The Smart Scheduling service list and its provider permissions.
- One Driving School resource for each service/equipment label.
- Only calendar bookings and calendar blocks that are still in the future at
  the moment the import runs.

Past appointments are deliberately excluded. The import can be safely run a
second time: imported records are updated by their Smart Scheduling source ID
instead of duplicated.

## Before importing

1. Add the Driving School environment variables and redeploy the application.
2. Confirm that `admin_drivingschool` can sign in at the normal application
   URL.
3. Take a normal database backup in Coolify.
4. Upload the Smart Scheduling workbook to the server or copy it into the
   application container as `/data/import/backup-2026-08-24.xlsx`.

Do **not** commit the workbook to GitHub.

## Run the preview first

In Coolify Terminal, choose the A2Z application container and run:

```bash
python import_driving_school_smart_backup.py /data/import/backup-2026-08-24.xlsx
```

The preview changes nothing. It prints the number of clients, instructors,
services, and future calendar records found.

## Run the import

When the preview looks correct, run:

```bash
python import_driving_school_smart_backup.py /data/import/backup-2026-08-24.xlsx --apply
```

The importer creates an extra database backup in `/data/backups` before it
writes anything. Verify the results by signing in as `admin_drivingschool`.
