# Client identity and upcoming appointment fix

## What was fixed

- Existing clients are now matched using a phone number without depending on
  spaces, dashes, brackets or a leading `+`.
- A newly saved appointment always uses the canonical client record for an
  exact matching full name and primary phone number.
- Client search no longer shows separate duplicate options for the same
  normalized full name and phone number.
- A client detail page now shows future and past appointments linked to an
  older duplicate record with the exact same normalized name and phone.

## Repair existing records

Deploy the update first. In the **A2Z application container** in Coolify run:

```sh
python relink_duplicate_client_bookings.py
python relink_duplicate_client_bookings.py --apply
```

The first command only reports what would change. The second command takes a
SQLite backup in `/data/backups` and relinks only appointments. It does not
delete clients, booking slots, breaks, instructors, equipment or services.

The matching rule is deliberately strict: exact normalized full name plus
exact normalized primary phone. It never merges people by a shared phone alone.
