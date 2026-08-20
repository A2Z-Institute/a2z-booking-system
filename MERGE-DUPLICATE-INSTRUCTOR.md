# Merge duplicate instructor: Ajay Kunjumon

The duplicate calendar entry must be merged in the production database after
deployment. The merge script keeps the chosen instructor record and moves all
of the duplicate record's appointments, booking slots, breaks/busy time,
availability, services and client assignments to it. The duplicate entry and
its duplicate login are deactivated rather than deleted.

In the **A2Z application container terminal** in Coolify run:

```sh
python merge_duplicate_instructors.py --find "AJAY KUNJUMON"
```

This prints both instructor IDs. Keep the normal **AJAY KUNJUMON** row and use
the `(20 TRAILER)` row as the source only after checking the IDs, for example:

```sh
python merge_duplicate_instructors.py --source-id SOURCE_ID --target-id TARGET_ID
python merge_duplicate_instructors.py --source-id SOURCE_ID --target-id TARGET_ID --apply
```

The first merge command is a dry run. The `--apply` command creates a verified
backup under `/data/backups` before changing anything. If it reports existing
approved overlaps, stop and review them before deciding whether to use the
explicit `--allow-overlaps` option.
