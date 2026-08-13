# A2Z Scheduler release checklist — 12 August 2026

## Release decision

Ready for the A2Z **staff-operated phone-booking workflow** after the administrator changes the packaged temporary password and completes the deployment steps below. It is not represented as a source-code copy or exact replacement for every public Smart Scheduling account feature.

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
| Downloadable and pre-start database backups | Included |
| Business/branch name, phone, address, timezone and currency | Included under Resources |
| Public online booking page | Intentionally disabled: A2Z clients call the booking agent |
| Business marketing photos/description | Not included because there is no public booking page |
| Staff profile photos and external calendar-feed sync | Not included; not required for phone booking |
| Granular Smart Scheduling permission checkboxes | Implemented as administrator/instructor/client roles rather than identical checkboxes |
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

## Deployment steps

1. Extract the ZIP to a normal local folder.
2. Run `\.\start-local.cmd -Port 8090` for HTTPS tunnel mode.
3. Sign in as `admin` and immediately create a new private password when prompted.
4. In a second PowerShell window run `cloudflared tunnel --url http://127.0.0.1:8090`.
5. Open the generated HTTPS address and verify `/health` returns `{"status":"ok"}` locally.
6. Create and download a backup from **Settings → Download backup** before importing or changing production data.
7. Keep both PowerShell windows open. Do not expose port 8090 directly to the public internet.

For LAN-only testing, use `\.\start-local.cmd -Port 8090 -LocalHttp`. Do not use `-LocalHttp` with a public tunnel.
