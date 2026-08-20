#!/usr/bin/env python3
"""Set the A2Z calendar instructor-column order.

Run the preview first, then apply it in the Coolify application terminal:

    python set_calendar_instructor_order.py
    python set_calendar_instructor_order.py --apply
"""

from __future__ import annotations

import argparse
import re

from database import get_db, init_db


# Operational order supplied by A2Z. Hints accept spacing/punctuation changes
# from imported Smart Scheduling names.
ORDERED_NAME_HINTS = [
    "JASMIN", "ASHWIN TM", "MUHAMMAD ANFAL", "ALBIN THOMAS",
    "THAHA HUSSAIN", "JITHU PRAKASH", "SHARHABIL", "ABHISHEK PP",
    "ASWANTH MP", "GOKUL BABU", "ANSON P", "ANU", "AJAY KUNJUMON",
    "ABHINATH", "ADHITHYAN S", "RENOLD", "ROSHAN", "SHARATH K",
    "ASHISH", "JITHU JAYAKRISHNAN", "NIVIN SHIBY",
]


def normalise(value: str) -> str:
    return re.sub(r"[^A-Z0-9]+", "", (value or "").upper())


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Save the configured column order")
    args = parser.parse_args()
    init_db()  # Safely adds display_order to an existing production database.
    with get_db() as conn:
        rows = [dict(row) for row in conn.execute(
            "SELECT id, name, branch_id, display_order FROM instructors WHERE is_active = 1 ORDER BY branch_id, id"
        )]
        unmatched = {row["id"]: row for row in rows}
        selected = []
        for position, hint in enumerate(ORDERED_NAME_HINTS, start=1):
            needle = normalise(hint)
            candidates = [row for row in unmatched.values() if needle in normalise(row["name"])]
            if len(candidates) == 1:
                row = candidates[0]
                selected.append((position, row))
                unmatched.pop(row["id"], None)
            elif len(candidates) > 1:
                print(f"AMBIGUOUS: {hint} -> " + ", ".join(f"{row['id']}:{row['name']}" for row in candidates))
            else:
                print(f"NOT FOUND: {hint}")
        print("\nRequested calendar order:")
        for position, row in selected:
            print(f"{position:>2}. {row['id']} | {row['name']}")
        if unmatched:
            print("\nRemaining active instructors (placed after the requested list):")
            for row in sorted(unmatched.values(), key=lambda item: (item["display_order"], item["name"])):
                print(f"    {row['id']} | {row['name']}")
        if not args.apply:
            print("\nPreview only. Run again with --apply to save this order.")
            return 0
        conn.execute("BEGIN IMMEDIATE")
        for position, row in selected:
            conn.execute("UPDATE instructors SET display_order = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?", (position, row["id"]))
        for position, row in enumerate(sorted(unmatched.values(), key=lambda item: (item["display_order"], item["name"])), start=1000):
            conn.execute("UPDATE instructors SET display_order = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?", (position, row["id"]))
    print("\nCalendar instructor order saved. Refresh the calendar once.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
