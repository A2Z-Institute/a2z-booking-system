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
A2Z_SEED_REFERENCE_DATA=1
A2Z_SEED_DEMO_DATA=0
A2Z_SEED_DEMO_STUDENT=0
A2Z_STUDENT_SELF_BOOKING=0
A2Z_SECURE_COOKIES=1
A2Z_ENABLE_NOTIFICATIONS=0
PORT=8000
```

Do not commit the real secret key, administrator password, live database, or
database backups. The administrator password is used only when the database is
created for the first time.

## Existing production data

The uploaded production archive contains a live SQLite database and backups.
Transfer a verified database backup separately to the `/data/a2z_booking.db`
volume using an encrypted administrative channel. Stop the application while
replacing the database, then start it and verify `/health`.
