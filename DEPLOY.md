# A2Z Scheduler v12 — Client deletion and branch isolation

This update makes the existing `admin` account the only Super Admin. Other
administrator accounts remain branch administrators and are restricted to
their own branch's staff, clients, instructors, resources, services, calendar,
bookings, dashboard totals, reminders, insights, and CSV exports.

No booking, client, instructor, service, or branch records are deleted or
replaced by this update.

Administrators and booking agents can now permanently delete an unused
duplicate client from the client details page. The action is limited to their
own branch. It is automatically hidden and rejected when the client has any
appointment history; those clients must be archived instead.

## Deploy from Windows PowerShell

1. Extract this ZIP.
2. Copy its files into the root of `C:\Users\Shili\a2z-booking-system`, keeping
   the `templates` and `static\js` folders.
3. Run:

```powershell
cd C:\Users\Shili\a2z-booking-system
git add app.py database.py postgres_runtime.py postgres_schema.sql templates\admin_users.html templates\base.html templates\admin_dashboard.html templates\admin_resources.html templates\calendar.html templates\client_detail.html static\js\app.js static\js\calendar.js
git commit -m "Add protected duplicate client deletion"
git push
```

4. In Coolify, redeploy the application after the push completes.
5. Sign out and sign back in as `admin`. The account label should show
   **Super Admin**.

## Verification

- Sign in as `admin`: all branches, employees, clients, and bookings are visible.
- Sign in as `admin_drivingschool`: only A2Z Driving School records are visible.
- Sign in as `admin_technical`: only A2Z Technical records are visible.
- Open an unused client as an administrator or booking agent: **Delete duplicate** is available.
- Open a client with booking history: permanent deletion is unavailable; Archive remains safe.
- Try opening another branch's staff or booking through a copied direct URL; the
  request must be rejected.

The application sets Super Admin status during startup. By default the username
is `admin`. It can be changed later with `A2Z_SUPER_ADMIN_USERNAME`.
