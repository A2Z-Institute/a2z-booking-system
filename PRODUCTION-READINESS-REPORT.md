# A2Z Scheduler production-readiness report

Audit date: 17 August 2026

## Release assessment

The application code is suitable for a controlled company rollout after every
item under **Required before go-live** is completed against the live Coolify
database. No software can guarantee zero failures; the controls below are meant
to prevent a single application or server incident from becoming permanent data
loss.

## Tests passed

- Python, JavaScript, shell, and Jinja template syntax
- installed Python dependency consistency
- application startup and `/health`
- CSRF enforcement and production security headers
- administrator, booking-agent, and instructor authentication
- administrator page rendering and role isolation
- booking-agent and instructor denial from administrator functions
- appointment creation and immediate server response
- duplicate appointment rejection
- break overlap rejection
- past-time booking rejection
- administrator-only booking-slot creation/editing
- drag/resize API finish-time synchronization
- stale revision/write rejection
- cross-instructor conflict diagnostics
- notification queue claiming, dispatch, and sent-state recording
- Gemini admin-only access, structured response validation, and aggregate-only data
- migration of an existing valid backup without changing its booking-row count
- client-directory/calendar response with 18,327 imported clients
- verified daily backup creation and retention behavior
- full preservation of a test set of 25 booking rows and related tables
- corrupt live database rejection
- corrupt same-day backup replacement with a valid backup
- runtime database corruption reporting as an unhealthy application

## Confirmed corrections

- Calendar saves now update from authoritative server data immediately.
- Duplicate submit and concurrent move requests are blocked in the browser.
- Rejected drag/resize changes return to their saved position and size.
- Occupied drop targets reach server validation and show a specific conflict.
- Daily backup monitoring continues while the container remains running.
- Source and backup databases receive full SQLite integrity checks.
- Backup downloads use the persistent configured backup directory.
- The health endpoint detects SQLite corruption.
- A read-only `verify_production_data.py` command reports integrity, foreign keys,
  and important record counts.
- Production HTTPS responses include HSTS and restrictive browser permissions.

## Required before go-live

1. Run exactly one Coolify application replica.
2. Mount persistent storage at `/data`.
3. Use `/data/a2z_booking.db` and `/data/backups` for the live database/backups.
4. Download a new backup from the currently running company application.
5. Run `python verify_production_data.py` against the live database and the
   downloaded/restore copy.
6. Confirm the live booking count and a selection of known appointments.
7. Keep at least one encrypted backup outside the Coolify server.
8. Configure a stable secret key and secure cookies; never commit provider keys.
9. Test one account for each company role and the core booking workflow.
10. Keep the old system available read-only during the initial rollout window.

## Data warning

The root `a2z_booking.db` found in the working copy is malformed and must not be
deployed. Database files are excluded from Git and from the release ZIP. The
three valid local backups inspected contain 18,327 clients, 21 instructors, 22
equipment records, and zero appointments. They are not a substitute for a fresh
backup of the current Coolify `/data/a2z_booking.db` if that database contains
the company appointment history.

## Residual operational risks

- Five-character passwords remain permitted because this was an explicit
  business requirement. Longer unique passwords are strongly recommended for
  administrators and booking agents.
- WhatsApp/SMS and email delivery require real provider credentials and cannot
  be end-to-end tested without those providers.
- Gemini requires a valid API key. Local statistics remain available when the
  provider is unavailable, and Gemini cannot modify bookings.
- Local `/data/backups` do not protect against total server or disk loss. An
  off-server backup copy is mandatory for business continuity.
- Docker image construction was not available in this audit environment;
  application startup, Waitress health, entrypoint shell syntax, and Dockerfile
  configuration were checked independently. Coolify must complete the final
  image build and health check before traffic is switched.

## Go-live decision

Proceed only after the live database and a separate restore copy both report:

```text
Integrity: ok
Foreign keys: ok
```

Then compare the printed booking/client counts with the current application and
perform a restore drill before staff rely on the new deployment.
