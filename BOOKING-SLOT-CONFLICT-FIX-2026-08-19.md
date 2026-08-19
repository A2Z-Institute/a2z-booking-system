# Booking-slot conflict fix — 19 August 2026

## Cause

The calendar's blue **Booking Slot** means that an administrator has assigned
an equipment band to a specific instructor. The previous save validator did
not honour that reservation. It treated every equipment label as one globally
exclusive machine, so an appointment belonging to another instructor could
make a visibly open blue slot fail with “The selected equipment is already
booked during this time.”

The free-slot calculation also rounded the beginning of some gaps to a
30-minute boundary even though the calendar uses 15-minute intervals. A free
slot beginning at 3:15 or 3:45 could therefore be rejected.

## Corrected rule

- An appointment fully contained inside the selected instructor's matching
  blue equipment slot may use that equipment band.
- Another instructor's appointment does not invalidate that administrator-made
  reservation.
- The same instructor still cannot have overlapping appointments.
- The same client still cannot have overlapping appointments.
- Breaks, busy time, past time, and appointments outside a matching blue slot
  remain blocked.
- Equipment used outside a blue reservation remains globally conflict-checked.
- The rule is enforced by both the application validator and SQLite database
  triggers, preventing different behaviour between form saves and drag/drop.

No manual database command is needed. The corrected triggers are installed by
the normal application startup during the Coolify deployment.
