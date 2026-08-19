# Clear appointments only

Use `clear_appointments_only.py` when test appointments must be removed before
loading a new booking backup.

The script preserves clients, instructors, equipment, booking slots, breakfast,
lunch, tea breaks, and all other busy-time entries. It deletes only appointment
records and their related notifications, service rows, intake values, and
booking-specific audit entries.

Before deletion it creates and verifies a backup in `/data/backups`.

## Coolify procedure

1. Finish any staff booking activity first. Do not let anyone create an
   appointment while the clear is running.
2. In Coolify Terminal select the running **A2Z application container**.
3. Review the exact counts without changing data:

   ```sh
   python clear_appointments_only.py
   ```

4. If the preserved slot and break counts look correct, delete appointments:

   ```sh
   python clear_appointments_only.py --apply
   ```

5. Confirm the final report shows `"appointments": 0` under `after` and
   `"integrity_check": "ok"`.

Do not reset SQLite IDs and do not delete the backup created by the script.
