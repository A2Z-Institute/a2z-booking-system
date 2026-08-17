# A2Z Scheduler production checklist — 17 August 2026

## Release decision

Deploy only after the database verification, persistent storage, backup download,
and restore drill below pass. Run exactly **one application replica** because the
production data store is SQLite.

## Smart Scheduling comparison

| Area | A2Z release status |
| --- | --- |
| Calendar staff columns and 15-minute grid | Included |
| Booking-slot equipment bands with appointments inside | Included; slot bands do not block appointments |
| Manual start and finish time | Included |
| Drag appointment and resize duration | Included |
| Appointment services, staff, equipment, status, notes and padding | Included |
| Existing-client search and automatic detail fill | Included |
| Create a new client while booking; email optional | Included |
| Appointment edit, cancel and permanent administrator delete | Included |
| Event / busy time | Included and blocks conflicting appointments |
| Repeat appointments and repeat slot/busy records | Included |
| Day/week navigation, staff/status filters and printing | Included |
| Client directory, details, history, notes, reminders and export | Included |
| Smart Scheduling Excel client import | Included; stable source IDs prevent duplicates |
| Staff create/edit, verification, roles, reset password and archive | Included |
| Services/groups, duration, price, colour and padding | Included |
| Assigned staff and compatible equipment | Included |
| Custom service questions and files | Included |
| Reminder queue and client opt-out | Included; actual delivery requires provider configuration |
| Activity history and CSV export | Included |
| Downloadable and automatic verified daily database backups | Included; latest 30 retained by default |
| Business/branch name, phone, address, timezone and currency | Included under Resources |
| Public online booking page | Intentionally disabled: A2Z clients call the booking agent |
| Business marketing photos/description | Not included because there is no public booking page |
| Staff profile photos and external calendar-feed sync | Not included; not required for phone booking |
| Granular Smart Scheduling permission checkboxes | Included with role-specific defaults |
| Gemini booking insights | Included for administrators; aggregate statistics only and read-only |
| Custom reminder message editor/test-send | Provider-driven reminder queue is included; identical template editor is not included |

## Verified release tests

- SQLite integrity and foreign-key checks.
- 18,327 clients and 21 active staff retained.
- Administrator login and forced password-change path.
- Calendar, clients, staff, resources, courses, reminders and settings pages.
- Create/edit/delete booking slot.
- Create/move/delete appointment inside a booking-slot band.
- A 9:30 am–4:00 pm appointment crossing the grey 1:00–2:00 pm display period.
- Genuine instructor/equipment/client overlap rejection.
- Busy-time conflict rejection.
- Client search and optional email.
- Excel re-import without duplicate client creation.
- Appointment/client/activity CSV exports.
- Consistent SQLite backup download.
- Waitress startup, `/health`, sign-in page, CSRF token and security headers.

## Coolify production deployment

1. Mount a persistent Coolify volume at `/data`.
2. Set `A2Z_DATABASE=/data/a2z_booking.db` and `A2Z_BACKUP_DIR=/data/backups`.
3. Set `A2Z_ENABLE_BACKUPS=1`, `A2Z_BACKUP_RETENTION=30`, and run one replica.
4. Configure a stable 32-byte-or-longer `A2Z_SECRET_KEY` and private administrator password.
5. Keep demo data and student self-booking disabled.
6. Redeploy and confirm `/health` returns `{"status":"ok"}`.
7. In the application terminal run `python verify_production_data.py`.
8. Sign in as administrator and download a backup before importing or bulk editing data.
9. Copy at least one verified backup to storage outside the Coolify server.
10. Test one appointment create, move, resize, instructor transfer, cancellation,
    break conflict, and login for each company role before staff switch systems.

## Backup and restore drill

1. Stop the application before replacing the live database.
2. Keep the current `/data/a2z_booking.db` as a rollback copy.
3. Copy the selected verified backup to a temporary filename inside `/data`.
4. Run `A2Z_DATABASE=/data/temporary-name.db python verify_production_data.py`.
5. Only after it reports integrity and foreign keys as `ok`, replace the live
   database, retain its ownership, and restart the application.
6. Confirm `/health`, record counts, calendar totals, and a known appointment.

Backups stored only in `/data/backups` protect against application mistakes, but
not complete server or disk loss. Maintain an encrypted off-server copy according
to the company's retention policy.

For LAN-only testing, use `\.\start-local.cmd -Port 8090 -LocalHttp`. Do not use `-LocalHttp` with a public tunnel.
