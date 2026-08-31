# A2Z Scheduler v11 — Super Admin and branch isolation

This update makes the existing `admin` account the only Super Admin. Other
administrator accounts remain branch administrators and are restricted to
their own branch's staff, clients, instructors, resources, services, calendar,
bookings, dashboard totals, reminders, insights, and CSV exports.

No booking, client, instructor, service, or branch records are deleted or
replaced by this update.

## Deploy from Windows PowerShell

1. Extract this ZIP.
2. Copy its files into the root of `C:\Users\Shili\a2z-booking-system`, keeping
   the `templates` and `static\js` folders.
3. Run:

```powershell
cd C:\Users\Shili\a2z-booking-system
git add app.py database.py postgres_runtime.py postgres_schema.sql templates\admin_users.html templates\base.html templates\admin_dashboard.html templates\admin_resources.html templates\calendar.html static\js\app.js static\js\calendar.js
git commit -m "Add Super Admin and branch-level access isolation"
git push
```

4. In Coolify, redeploy the application after the push completes.
5. Sign out and sign back in as `admin`. The account label should show
   **Super Admin**.

## Verification

- Sign in as `admin`: all branches, employees, clients, and bookings are visible.
- Sign in as `admin_drivingschool`: only A2Z Driving School records are visible.
- Sign in as `admin_technical`: only A2Z Technical records are visible.
- Try opening another branch's staff or booking through a copied direct URL; the
  request must be rejected.

The application sets Super Admin status during startup. By default the username
is `admin`. It can be changed later with `A2Z_SUPER_ADMIN_USERNAME`.
