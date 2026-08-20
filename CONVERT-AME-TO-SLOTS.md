# Convert AME appointments to slots

An AME placeholder such as `AME 58` can be converted into a blue **AME**
booking slot. The conversion keeps its instructor, date and time, and moves it
onto the dedicated AME slot resource shown in the administrator equipment list.
It does **not** delete any client record; it deletes only the matched
placeholder appointment.

The conversion matches names starting with `AME` followed by a number, for
example `AME 58`, `AME-58`, or `ame 58`. It will not touch regular client
appointments.

Run in the Coolify application container:

```sh
python convert_ame_appointments_to_slots.py
```

Read the displayed list. When it contains only AME placeholder rows, run:

```sh
python convert_ame_appointments_to_slots.py --apply
```

The apply step automatically creates a verified database backup in
`/data/backups` first. Slots permit several normal appointments at different
times inside the AME availability band. Normal no-overlap rules still apply to
the same instructor at the same time.
