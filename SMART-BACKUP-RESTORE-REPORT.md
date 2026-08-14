# Smart Scheduling backup restore report

Source tested: `backup-2026-08-12.xlsx`

## Reconciliation

| Data set | Restored |
| --- | ---: |
| Smart client rows | 18,324 |
| Staff members | 21 |
| Exported services | 27 |
| Appointment-history rows | 75,535 |
| Appointments | 61,180 |
| Booking-slot bands | 4,099 |
| Breaks / busy periods | 10,256 |
| Rejected source rows | 0 |
| Duplicate source references | 0 |
| Foreign-key violations | 0 |

The appointment total includes 32,226 Completed, 17,889 Confirmed/Approved,
9,968 Pending/Not Confirmed, 582 Cancelled, 489 No-show, 17 Rescheduled,
8 Running Late, and 1 Arrived record.

## Comparison-day verification

For 12 August 2026 the restored calendar returns:

- 239 appointments
- 18 booking slots
- 39 breaks/busy periods

The JASMIN JCB booking slot is restored as 06:30–17:30, with individual
appointments retained inside the slot band as in Smart Scheduling.

## Functional checks passed

- database integrity and foreign-key checks
- repeat import without duplicate source records
- calendar day rendering with appointment, slot, and busy event layers
- 15-minute grid and 12-hour time labels
- long booking slots containing shorter appointments
- live existing-client type-ahead search
- creation of a new client using a phone number without an email address
- manual appointment finish time
- appointment creation and editing
- cancellation and permanent deletion, including imported appointments
- status, service, instructor, equipment, price, note, and series preservation
- CSRF, role, revision, and collision responses on calendar APIs

The application intentionally remains an A2Z-owned implementation; no source
code, protected assets, or private implementation details were copied from the
Smart Scheduling service.
