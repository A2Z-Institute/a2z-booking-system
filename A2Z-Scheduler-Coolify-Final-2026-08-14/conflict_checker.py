"""
Conflict Checker Module
Validates whether a new booking overlaps with existing approved bookings 
for Machine, Instructor, OR Student.
"""

def _to_minutes(time_str):
    try:
        h, m = map(int, str(time_str).split(":"))
    except (TypeError, ValueError):
        raise ValueError("Time values must use HH:MM format") from None
    if not (0 <= h <= 23 and 0 <= m <= 59):
        raise ValueError("Time values must use HH:MM format")
    return h * 60 + m


def _same_id(left, right):
    try:
        return int(left) == int(right)
    except (TypeError, ValueError):
        return False


def has_conflict(new_booking, existing_bookings):
    """
    new_booking / existing_bookings: dicts with
        student_name, machine_id, instructor_id, date, start_time, end_time
    Returns: (conflict: bool, status_message: str)
    """
    new_start = _to_minutes(new_booking["start_time"])
    new_end = _to_minutes(new_booking["end_time"])
    if new_end <= new_start:
        raise ValueError("Booking end time must be after its start time")

    for b in existing_bookings:
        if b["date"] != new_booking["date"]:
            continue

        same_machine = _same_id(b["machine_id"], new_booking["machine_id"])
        same_instructor = _same_id(b["instructor_id"], new_booking["instructor_id"])
        
        existing_student_id = b.get("student_user_id")
        new_student_id = new_booking.get("student_user_id")
        if existing_student_id is not None and new_student_id is not None:
            same_student = _same_id(existing_student_id, new_student_id)
        else:
            # Legacy rows may predate student accounts, so retain the original
            # name-based safeguard only when an account id is unavailable.
            same_student = (
                b.get("student_name", "").strip().lower()
                == new_booking.get("student_name", "").strip().lower()
            )

        if not (same_machine or same_instructor or same_student):
            continue

        existing_start = _to_minutes(b["start_time"])
        existing_end = _to_minutes(b["end_time"])

        overlap = new_start < existing_end and new_end > existing_start
        if overlap:
            if same_student:
                reason = "Student"
            elif same_machine:
                reason = "Machine"
            else:
                reason = "Instructor"
            return True, f"REJECTED - {reason} conflict with existing booking"

    return False, "APPROVED"
