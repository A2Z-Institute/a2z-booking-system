# Deploying A2Z Scheduler on Coolify

The repository includes a root-level `Dockerfile`. Use these settings for the
application in Coolify.

## Build settings

- Build pack: **Dockerfile**
- Base directory: `/`
- Dockerfile location: `/Dockerfile`
- Port: `8000`
- Health-check path: `/health`

If Coolify still reports `open Dockerfile: no such file or directory`, make
sure the commit containing `Dockerfile` has been pushed to the selected branch,
the base directory is `/`, and then choose **Redeploy** (a restart is not
enough for a repository/build change).

## Persistent storage

Create persistent storage before the first production deployment:

- Type: **Volume**
- Name: `a2z-data`
- Destination path: `/data`

The live SQLite file is `/data/a2z_booking.db`. Without this volume, all users,
clients, bookings and settings will be lost when Coolify replaces the
container. Keep the application at one replica because it uses SQLite.

## Environment variables

Add these in Coolify. Mark both password/secret values as secret.

```dotenv
A2Z_SECRET_KEY=GENERATE_A_LONG_RANDOM_VALUE
A2Z_ADMIN_PASSWORD=CHOOSE_A_LONG_UNIQUE_INITIAL_PASSWORD
A2Z_DATABASE=/data/a2z_booking.db
A2Z_SEED_REFERENCE_DATA=1
A2Z_SEED_DEMO_DATA=0
A2Z_SEED_DEMO_STUDENT=0
A2Z_STUDENT_SELF_BOOKING=0
A2Z_SECURE_COOKIES=1
A2Z_ENABLE_NOTIFICATIONS=0
A2Z_DEBUG=0
PORT=8000
```

Generate `A2Z_SECRET_KEY` once and keep it unchanged. For example, on a trusted
computer:

```powershell
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

`A2Z_ADMIN_PASSWORD` is used only when the database is created for the first
time. Later changes to that variable do not reset the administrator password.

## Domain and first deployment

1. Add the public HTTPS domain in Coolify.
2. Save all settings, then redeploy so the pending repository change is used.
3. Wait for the deployment and health check to succeed.
4. Open `https://YOUR-DOMAIN/health`; it should return `{"status":"ok"}`.
5. Sign in as `admin` with the initial password and change it immediately.
6. Configure regular backups of the `/data` volume.

Do not commit `.env`, the SQLite database, or downloaded backups to GitHub.
