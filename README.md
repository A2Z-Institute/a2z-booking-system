# A2Z Institute Scheduling Portal

For the cleaned production client and upcoming-booking update dated
19 August 2026, follow `DATA-UPDATE-2026-08-19.md` after deployment. The data
reconciliation is deliberately manual and is not run during container startup.

The same release includes the permanent blue booking-slot conflict correction
described in `BOOKING-SLOT-CONFLICT-FIX-2026-08-19.md`.

Use `CLEAR-APPOINTMENTS-ONLY.md` when clearing dummy appointments while keeping
clients, instructors, blue booking slots, and break/busy-time entries.

A role-based scheduling system for practical training at A2Z Institute. Access is controlled by the institution: there is no public account-registration page.

## What the system does

- **Administrators** run a SmartScheduling-style day or week calendar, create and move appointments, manage the service catalogue, configure durations, prices, private padding, appointment fields, equipment and instructor compatibility, and export appointment or client records.
- **Reception and teaching staff** create every appointment while speaking to the client. They can select an existing client or add a caller during the appointment, choose one or more services, assign the instructor and equipment, and confirm the slot immediately.
- **Students do not choose or book slots.** If a student account is retained, it is a read-only timetable: arranging, changing, or cancelling an appointment is handled by staff.
- **Instructors** see their own calendar and clients, manage weekly availability and busy time, and record completed sessions or no-shows.
- **Operations staff** can search complete client histories, keep internal notes and tags, monitor queued confirmations and reminders, retry failed deliveries, and retain an audit trail of important account and booking actions.

Archiving is the normal way to remove a finished client or instructor. It blocks any account access and closes future appointments while retaining historical appointment and attendance records.

The application uses Flask, Waitress and SQLite. It is suitable for development and a modest, single-computer pilot. Read [Where to host it](#where-to-host-it) before making it available outside the institute network.

## Run it from any folder on Windows

Install Python 3.10 or newer, open PowerShell in the extracted application folder, and run:

```powershell
.\start-local.ps1
```

The launcher is location-independent. It uses its own folder, creates or repairs `.venv`, installs the packages in `requirements.txt`, and creates a private `.env` with random secrets when one does not exist. A fresh installation prints its initial administrator password once; store it privately and replace it at first sign-in.

Do not copy `.venv` between computers. Python virtual environments contain computer-specific paths. If a broken copied environment is present, the launcher replaces only that folder and rebuilds it locally.

The default mode is designed for an HTTPS tunnel: Waitress listens only on `127.0.0.1:8080` and secure session cookies are enabled. In a second PowerShell window, run:

```powershell
cloudflared tunnel --url http://127.0.0.1:8080
```

Share the generated `https://...trycloudflare.com` address, not the `127.0.0.1` address. The quick-tunnel address changes after a restart and both PowerShell windows must remain running.

On the host computer, the local health endpoint is:

- <http://127.0.0.1:8080/health>

Stop the server with `Ctrl+C`.

If PowerShell prevents `.ps1` files from running, use the included policy-safe wrapper:

```powershell
.\start-local.cmd
```

Do not use `python app.py` or Flask debug mode for normal institutional use.

### Send a clean copy to a friend and use a Cloudflare tunnel

On the original computer, run this from the A2Z folder:

```powershell
.\create-share-package.cmd
```

This rebuilds `A2Z-Scheduler-Portable.zip` from the current application files. Send that ZIP rather than copying the working folder. It excludes `.venv`, `.env`, databases, backups, tests, Git data, caches and logs, and it includes the package builder so the clean copy can be shared again later.

The clean package creates a new installation with a new administrator account and the editable starter catalogue, but no existing clients, instructors or appointments. To hand over an existing live system instead, stop the scheduler and tunnel, create a consistent database backup, and transfer that backup plus `.env` separately using an encrypted channel. Those files contain credentials and institutional personal data and should not be placed in an ordinary public file-sharing link.

On the friend's Windows computer:

1. Install Python 3.10 or newer.
2. Install Cloudflared once:

```powershell
winget install --id Cloudflare.cloudflared
```

3. Extract the entire ZIP to a normal local folder. Do not run it from inside the ZIP or from OneDrive, Dropbox or another synchronized folder.
4. Open PowerShell in the extracted folder and start A2Z:

```powershell
.\start-local.cmd
```

The first launch creates the computer's private `.venv`, `.env` and database. It also prints the initial `admin` password once. Record that password privately and leave this first PowerShell window open.

5. Open a second PowerShell window and start the HTTPS tunnel:

```powershell
cloudflared tunnel --url http://127.0.0.1:8080
```

6. Open the generated `https://...trycloudflare.com` address and sign in as `admin` with the password printed in the first window.

No application path, source file or environment setting needs editing. Both PowerShell windows must stay open while A2Z is available. Stop each command with `Ctrl+C`; the temporary Cloudflare address changes the next time the tunnel starts.

### First sign-in

For a clean portable installation, sign in as `admin` using the password printed by `start-local.cmd`. The launcher also stores that one-time bootstrap value privately in `.env`; it does not need to be edited. If no administrator password was configured before the first database was created, the administrator is forced to replace the fallback password immediately.

From **Staff** and **Clients**, the administrator should:

1. Create each staff account using verified institute records.
2. Mark an instructor verified only after confirming their identity and employment details.
3. Add clients from the client database or directly while taking a call in the calendar.
4. Give temporary passwords only to staff. Staff must replace them at first sign-in.
5. Archive records when training or employment ends; reactivate them only if operational access is required again.

Demo instructors and clients are disabled by default. If an old database contains sample records, review or archive them before real use.

## Access it from phones and other computers on the same network

For LAN-only access without Cloudflare, start the scheduler explicitly in local HTTP mode:

```powershell
.\start-local.ps1 -Listen 0.0.0.0 -LocalHttp
```

Then:

1. Connect the host computer and user devices to the same trusted router or Wi-Fi network.
2. Run `ipconfig` on the host and find its IPv4 address, for example `192.168.1.50`.
3. On another device, open `http://192.168.1.50:8080`.
4. Reserve the host's address in the router's DHCP settings so the link does not unexpectedly change.

Windows Firewall may block incoming connections. In an **Administrator PowerShell** window, add a rule limited to the private network and local subnet:

```powershell
New-NetFirewallRule -DisplayName "A2Z Scheduler - private LAN" -Direction Inbound -Action Allow -Protocol TCP -LocalPort 8080 -Profile Private -RemoteAddress LocalSubnet
```

Before adding the rule, confirm Windows identifies the institute network as **Private**, not Public. Do not create an unrestricted public-profile rule, and do not forward port 8080 through the router.

Plain HTTP is acceptable only on a trusted local network for a small pilot. A VPN or HTTPS reverse proxy is recommended even for LAN use when devices or Wi-Fi cannot be fully trusted.

## Configuration

`wsgi.py` loads `.env` before the application initializes the database.

| Variable | Purpose |
| --- | --- |
| `A2Z_SECRET_KEY` | Signs session cookies. Use a stable random value of at least 32 bytes; changing it signs everyone out. |
| `A2Z_DATABASE` | SQLite database path. An absolute path outside a synced folder is best on an always-on PC. |
| `A2Z_BACKUP_DIR` | Persistent directory for verified SQLite backups. Use `/data/backups` in Coolify. |
| `A2Z_BACKUP_RETENTION` | Number of daily backups retained; defaults to `30`. |
| `A2Z_ENABLE_BACKUPS` | Starts the hourly backup monitor, which creates at most one verified backup per day. Keep `1` in production. |
| `A2Z_ADMIN_PASSWORD` | Initial password used only when the built-in administrator is first created. |
| `A2Z_SEED_REFERENCE_DATA` | Creates the initial branch and equipment catalogue when set to `1`. |
| `A2Z_SEED_DEMO_DATA` | Creates sample instructor profiles when set to `1`; leave `0` for real use. |
| `A2Z_SEED_DEMO_STUDENT` | Creates a sample student when set to `1`; leave `0` for real use. |
| `A2Z_INSTRUCTOR_PASSWORD` | Password for sample instructors only, when demo data is enabled. |
| `A2Z_STUDENT_PASSWORD` | Password for the sample student only, when demo data is enabled. |
| `A2Z_STUDENT_SELF_BOOKING` | Legacy compatibility switch. Keep `0` in real use so only staff can create appointments. |
| `A2Z_SECURE_COOKIES` | Set to `1` for HTTPS. The launcher enforces `1` by default and uses `0` only with its explicit `-LocalHttp` switch. |
| `A2Z_ENABLE_NOTIFICATIONS` | Set to `1` only after configuring an email or SMS provider. Confirmations plus 24-hour and 2-hour reminders are otherwise kept safely queued. |
| `A2Z_SMTP_HOST`, `A2Z_SMTP_PORT`, `A2Z_SMTP_USERNAME`, `A2Z_SMTP_PASSWORD`, `A2Z_SMTP_FROM`, `A2Z_SMTP_TLS` | SMTP provider settings used when a branch sends email. |
| `A2Z_SMS_WEBHOOK_URL`, `A2Z_SMS_WEBHOOK_TOKEN`, `A2Z_SMS_SENDER` | HTTPS webhook settings used when a branch sends SMS. |
| `A2Z_GEMINI_API_KEY` | Optional Gemini API key for the admin-only Booking Insights page. Never commit this key. |
| `A2Z_GEMINI_MODEL` | Gemini model used for aggregate analysis; defaults to `gemini-2.5-flash`. |
| `A2Z_HOST`, `PORT`, `A2Z_DEBUG` | Apply only when directly running `wsgi.py`; the provided launcher uses Waitress on port 8080. Keep debug at `0`. |

### Gemini booking insights

- Administrators can open **Insights** from the main navigation.
- Booking totals, service demand, equipment demand, busy weekdays, and popular start times are calculated locally and work without Gemini.
- Selecting **Generate Gemini analysis** sends only the aggregate figures visible on that page.
- Client names, phone numbers, emails, notes, and uploaded documents are never included in the Gemini request.
- Gemini recommendations are advisory and cannot create, move, cancel, or edit appointments.
- Add `A2Z_GEMINI_API_KEY` in Coolify's environment variables, save, and redeploy to enable the button.

Changing a seed password after the database exists does not reset an account. Use the administrator's **Reset password** action, which issues a temporary password and requires the user to change it at the next sign-in.

## Day-to-day workflow

### Staff and instructor setup

- The administrator creates staff accounts and assigns the correct role and branch.
- Creating an instructor also creates their linked instructor profile.
- Only verified, active instructors can receive appointments.
- The administrator can edit details, verify an instructor, reset a password, archive an account, or reactivate it.
- Restored instructor profiles appear in **Staff & access** with a **Create login** action. The form fills the staff name, branch, speciality, and a suggested username; after creation, use **Reset password** whenever a fresh temporary password is needed.
- Instructor sign-ins open their own calendar only. Appointment details show the client's phone number as a clickable call link, and instructors may update status to **Pending** or **Completed**.
- An administrator cannot archive their own signed-in account, and the last active administrator is protected.

### Staff-created appointments

- A student calls or speaks to staff; staff opens **Calendar** and selects an empty period.
- Staff choose an existing client or add the caller without creating login details, then select one or more services, an instructor, and compatible equipment.
- Booking-agent appointments may cross the grey/nonworking display period, matching Smart Scheduling's staff calendar. Real appointments, instructor busy time, equipment use, client use, and private before/after padding still prevent accidental overlaps.
- The appointment is confirmed immediately and appears on the staff calendar.
- Collision checks protect the client, instructor, and equipment from overlapping active sessions. This deliberately improves on SmartScheduling's manual double-booking limitation.
- Students cannot access the slot finder or appointment-creation API while `A2Z_STUDENT_SELF_BOOKING=0`, which is the production default.

### Calendar, courses, resources, and clients

- The day calendar shows all visible instructors in columns. Selecting one instructor switches to their week.
- Sunday is a normal operational day: staff may create booking slots and appointments from 6:00 am through the 6:30 pm closing time, subject to the same lunch and conflict checks as other days.
- Staff can click or press an empty slot to add an appointment, and drag an active appointment to another live slot.
- **Booking Slot** creates a long equipment availability band on the left of a staff column. Appointments remain bookable beside and inside that band; the slot is an operational guide, not busy time.
- Appointment cards can be resized in 15-minute steps with a live start/finish preview. Administrators may explicitly enable **Allow Double Booking** for exceptional slots; the exception is recorded on the appointment and normal collision protection remains enabled elsewhere.
- The calendar editor includes SmartScheduling-style operational statuses: Pending, Confirmed, Not Confirmed, Completed, No-show, Running Late, Arrived, Rescheduled, Declined, and Cancelled.
- Administrators can create, edit, archive or reactivate courses and control their branch, duration, price, colour, padding, compatible equipment, assigned instructors, and appointment questions.
- Administrators can create, edit, archive or reactivate branches and equipment from **Resources**.
- Client records include editable contact details, branch and instructor assignments, appointment history, retained intake answers and files, private notes, tags, reminder preferences, and CSV export.
- Client email is optional. Smart Scheduling Excel exports can be imported with `import_clients_xlsx.py`; source IDs are retained so repeating the import updates existing imported clients rather than duplicating them.
- A complete Smart Scheduling backup (Clients, Services, and staff history sheets) can be restored idempotently with:

```powershell
.\.venv\Scripts\python.exe import_smartscheduling_backup.py backup.xlsx --database a2z_booking.db --report restore-report.json
```

  The restore keeps appointments, long booking-slot bands, breaks/busy time,
  statuses, multi-service rows, staff assignments, client contacts, manual
  start/finish times, notes, prices, and series references. Back up the current
  database before importing into a live installation.

### Confirmations and reminders

- Confirming or rescheduling an appointment creates a durable notification schedule: an immediate message, a 24-hour reminder, and a 2-hour reminder.
- Rescheduling cancels stale reminder jobs and creates a fresh schedule without duplicates.
- Delivery retries automatically and stops after five failed attempts; administrators can inspect and retry failed messages.
- Leave `A2Z_ENABLE_NOTIFICATIONS=0` until a real SMTP or SMS provider is configured. Queued appointments remain intact while sending is paused.

### Instructor availability

- Institute hours are used until an instructor creates a custom weekly schedule.
- Instructors can add, edit or remove their own weekly ranges and add full-day or partial time off.
- Administrators can select any instructor and manage the same weekly availability and time-off settings.
- Time off cannot be placed over a pending or approved booking; that request must be reviewed or cancelled first.
- Resetting availability restores the institute's standard hours.

### Attendance

- An instructor or administrator can mark an approved session on or before the current date as **Completed** or **No-show**.
- Attendance remains part of the booking history when an account is later archived.

## Backups

The database contains personal details, account records, schedules, attendance and audit events. Protect backups like the live system.

SQLite runs in WAL mode, so do not copy only the live `.db` file while the server is running. From this folder, create a consistent online backup with:

```powershell
New-Item -ItemType Directory -Force backups | Out-Null
$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$env:A2Z_BACKUP_TARGET = (Join-Path (Resolve-Path .) "backups\a2z-$stamp.db")
.\.venv\Scripts\python.exe -c "from dotenv import load_dotenv; load_dotenv(); import os, sqlite3; from database import database_path; source=sqlite3.connect(database_path()); target=sqlite3.connect(os.environ['A2Z_BACKUP_TARGET']); source.backup(target); target.close(); source.close(); print(os.environ['A2Z_BACKUP_TARGET'])"
Remove-Item Env:A2Z_BACKUP_TARGET
```

- Schedule a backup at least daily and before every upgrade.
- Copy completed backups to an encrypted location away from the host computer.
- Do not put the live SQLite database in OneDrive, Dropbox, a network drive or another synchronized folder.
- Regularly restore a backup to a separate file and run `PRAGMA integrity_check` to confirm it is usable.

## Reset the administrator password

Stop the scheduler with **Ctrl+C**, then run this inside the extracted
application folder:

```powershell
.\reset-admin-password.cmd
```

Enter the new password twice. The utility displays the exact database it is
changing and does not expose the password in PowerShell history. Restart the
scheduler after the reset.

## Start automatically after a reboot

For a dedicated local host, create a Windows Task Scheduler task that:

- starts **at system startup** under a dedicated Windows account;
- uses the extracted project folder as **Start in**;
- runs `powershell.exe` with `-NoProfile -ExecutionPolicy Bypass -File "C:\path\to\A2Z Scheduler\start-local.ps1"`;
- restarts after failure;
- runs whether or not that Windows account is interactively signed in.

Prevent the PC from sleeping. Prefer Ethernet and a UPS, keep Windows and Python dependencies updated, and verify the application after every reboot. The health check is available at `http://HOST:8080/health`.

## Where to host it

### Spare always-on computer

A spare computer is reasonable for an internal, single-site pilot when it is:

- always powered, patched and physically secured;
- connected to a trusted LAN;
- backed up automatically;
- limited to one Waitress process and one SQLite database;
- monitored by someone who can restart it after power, disk or network failures.

This option is inexpensive, but service stops if the PC, router, electricity or internet connection fails.

### Access from outside the institute

Do **not** expose Waitress directly with router port-forwarding. For private remote staff access, use a VPN such as Tailscale or WireGuard. If remote access is required, use an HTTPS reverse proxy or outbound tunnel with authentication and access controls. The default launcher already enables secure cookies and keeps Waitress bound to `127.0.0.1` behind it:

```powershell
.\start-local.ps1
```

An HTTPS tunnel hides the local port but does not make the host highly available. The computer still holds the only live database and remains responsible for updates, monitoring, backups and incident recovery.

### Recommended public production setup

For dependable internet-facing use, managed hosting is better than a local PC. Use a managed application platform, managed PostgreSQL, HTTPS, automated backups, health monitoring and secret storage. This avoids dependence on one office PC and supports safer recovery and future multi-branch growth.

The current application is SQLite-specific, so moving to PostgreSQL is a development and data-migration project, not an environment-variable change. Until that migration is complete, run exactly one application process and keep the SQLite database on the same computer as the app.

## Tests

Install the development requirements and run the automated checks:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m pytest -q
```

These checks cover access control, account lifecycle, assignments, booking conflicts, availability, attendance and database upgrades.
