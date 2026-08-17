"""
Computes free 15-minute time slots for instructors/machines on a given date.
Instructor-specific breaks are stored as busy periods and removed separately.
"""

WORK_WINDOWS = [("06:00", "18:30")]


def _to_minutes(time_str):
    h, m = map(int, time_str.split(":"))
    return h * 60 + m


def _to_time_str(minutes):
    h = minutes // 60
    m = minutes % 60
    return f"{h:02d}:{m:02d}"


def _free_slots_in_window(bookings, start_min, end_min):
    free_slots = []
    cursor = start_min

    for b in bookings:
        b_start = _to_minutes(b["start_time"])
        b_end = _to_minutes(b["end_time"])

        b_start = max(b_start, start_min)
        b_end = min(b_end, end_min)
        if b_start >= b_end:
            continue

        if b_start > cursor:
            free_slots.append({
                "start": _to_time_str(cursor),
                "end": _to_time_str(b_start),
            })
        cursor = max(cursor, b_end)

    if cursor < end_min:
        free_slots.append({
            "start": _to_time_str(cursor),
            "end": _to_time_str(end_min),
        })

    return free_slots


def compute_free_slots(bookings, work_windows=WORK_WINDOWS):
    sorted_bookings = sorted(bookings, key=lambda b: _to_minutes(b["start_time"]))

    free_slots = []
    for work_start, work_end in work_windows:
        start_min = _to_minutes(work_start)
        end_min = _to_minutes(work_end)
        free_slots.extend(_free_slots_in_window(sorted_bookings, start_min, end_min))

    return free_slots


def chunk_slots(slots_list, duration_minutes=30, step_minutes=15):
    """Split open gaps into bookable sessions on a 15-minute start grid."""
    if duration_minutes < 15 or duration_minutes % 15 != 0:
        raise ValueError("Session duration must use 15-minute increments")
    fixed_slots = []
    for slot in slots_list:
        start_min = _to_minutes(slot["start"])
        end_min = _to_minutes(slot["end"])

        curr = start_min
        while curr + duration_minutes <= end_min:
            fixed_slots.append({
                "start": _to_time_str(curr),
                "end": _to_time_str(curr + duration_minutes)
            })
            curr += step_minutes

    return fixed_slots


def chunk_slots_30min(slots_list):
    """Backwards-compatible helper returning 30-minute sessions on a 15-minute grid."""
    return chunk_slots(slots_list, 30)


def intersect_free_slots(slots_a, slots_b, min_duration_minutes=30):
    result = []
    for a in slots_a:
        a_start, a_end = _to_minutes(a["start"]), _to_minutes(a["end"])
        for b in slots_b:
            b_start, b_end = _to_minutes(b["start"]), _to_minutes(b["end"])

            overlap_start = max(a_start, b_start)
            overlap_end = min(a_end, b_end)

            if overlap_end - overlap_start >= min_duration_minutes:
                result.append({
                    "start": _to_time_str(overlap_start),
                    "end": _to_time_str(overlap_end),
                })

    result.sort(key=lambda s: _to_minutes(s["start"]))
    return chunk_slots(result, min_duration_minutes)
