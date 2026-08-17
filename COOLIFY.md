# Coolify deployment

Deploy this repository as a Dockerfile application.

## Required settings

- Dockerfile location: `/Dockerfile`
- Exposed port: `8000`
- Health check path: `/health`
- Persistent storage: volume mounted at `/data`

## Required environment variables

Set these in Coolify before the first deployment:

```env
A2Z_SECRET_KEY=<a stable random value of at least 32 bytes>
A2Z_ADMIN_PASSWORD=<a long unique initial administrator password>
A2Z_DATABASE=/data/a2z_booking.db
A2Z_BACKUP_DIR=/data/backups
A2Z_BACKUP_RETENTION=30
A2Z_ENABLE_BACKUPS=1
A2Z_SEED_REFERENCE_DATA=1
A2Z_SEED_DEMO_DATA=0
A2Z_SEED_DEMO_STUDENT=0
A2Z_STUDENT_SELF_BOOKING=0
A2Z_SECURE_COOKIES=1
A2Z_ENABLE_NOTIFICATIONS=0
A2Z_GEMINI_MODEL=gemini-2.5-flash
PORT=8000
```

To enable the optional admin Booking Insights analysis, create a Gemini API key
in Google AI Studio and add it only in Coolify (never GitHub):

```text
A2Z_GEMINI_API_KEY=your-secret-key
```

After saving the variable, redeploy the application. Local charts work without
Gemini; the API receives anonymous aggregate counts only.

Do not commit the real secret key, administrator password, live database, or
database backups. The administrator password is used only when the database is
created for the first time.

Run exactly one application replica. SQLite does not support sharing this file
between multiple Coolify replicas. The application creates one verified backup
per day in `/data/backups` and retains 30 by default. Also copy verified backups
to encrypted storage outside this server so a complete server/disk failure does
not remove both the live database and its local backups.

After deployment, verify the live data from the application terminal:

```sh
python verify_production_data.py
```

## Existing production data

The uploaded production archive contains a live SQLite database and backups.
Transfer a verified database backup separately to the `/data/a2z_booking.db`
volume using an encrypted administrative channel. Stop the application while
replacing the database, then start it and verify `/health`.
