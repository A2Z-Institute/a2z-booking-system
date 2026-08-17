"""A2Z Institute staff-operated scheduling portal.

Staff create and manage appointments while speaking with clients. Students do
not choose slots; any retained student portal is a read-only timetable.
"""

from __future__ import annotations

import hmac
import csv
import io
import json
import os
import re
import secrets
import sqlite3
from calendar import monthrange
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from functools import wraps
from pathlib import Path
from urllib.parse import urlsplit

from flask import (
    Flask,
    Response,
    abort,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    send_file,
    session,
    url_for,
)
from flask_login import (
    LoginManager,
    UserMixin,
    current_user,
    login_required,
    login_user,
    logout_user,
)
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename

from backup_database import backup_directory, verify_database
from database import database_path, get_db, init_db, seed_reference_data
from free_slots import WORK_WINDOWS, compute_free_slots, intersect_free_slots
from gemini_insights import (
    GeminiInsightsError,
    gemini_configured,
    generate_booking_insights,
)
from import_clients_xlsx import import_clients


IST = timezone(timedelta(hours=5, minutes=30))
ACTIVE_BOOKING_STATUSES = (
    "Pending",
    "Approved",
    "Not Confirmed",
    "Running Late",
    "Arrived",
    "Rescheduled",
    "No Action",
)
STAFF_DAY_START_MINUTES = 6 * 60
STAFF_DAY_END_MINUTES = (18 * 60) + 30
DEFAULT_LUNCH_START = "13:00"
DEFAULT_LUNCH_END = "14:00"
DEFAULT_LUNCH_SOURCE_PREFIX = "default-lunch"
FINAL_BOOKING_STATUSES = ("Rejected", "Cancelled", "Completed", "No-show")
MIN_PASSWORD_LENGTH = 5
DAY_NAMES = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")
MANAGED_ROLES = ("student", "booking_agent", "instructor", "admin")
PERMISSION_BITS = {
    "everyone_schedule": 1,
    "write_access": 2,
    "client_database": 4,
    "export_clients": 8,
    "export_appointments": 16,
    "contact_details": 32,
    "client_notes": 64,
}
PERMISSION_OPTIONS = (
    ("everyone_schedule", "Everyone's Schedule", "View schedules for every instructor instead of only the linked schedule."),
    ("write_access", "Write Access", "Create and save appointments and other permitted records."),
    ("client_database", "Client Database", "Open and search the client database."),
    ("export_clients", "Export Clients", "Download client data as a CSV file."),
    ("export_appointments", "Export Appointments", "Download appointment data as a CSV file."),
    ("contact_details", "Contact Details", "See client email addresses and phone numbers."),
    ("client_notes", "Client Notes", "See private client notes in staff views."),
)
ALL_STAFF_PERMISSIONS = sum(PERMISSION_BITS.values())
DEFAULT_ROLE_PERMISSIONS = {
    "admin": ALL_STAFF_PERMISSIONS,
    "booking_agent": (
        PERMISSION_BITS["everyone_schedule"]
        | PERMISSION_BITS["write_access"]
        | PERMISSION_BITS["client_database"]
        | PERMISSION_BITS["export_clients"]
        | PERMISSION_BITS["contact_details"]
        | PERMISSION_BITS["client_notes"]
    ),
    "instructor": (
        PERMISSION_BITS["client_database"]
        | PERMISSION_BITS["contact_details"]
        | PERMISSION_BITS["client_notes"]
    ),
    "student": 0,
}
BRANCH_TIMEZONE_OPTIONS = (
    ("Asia/Kolkata", "India (Asia/Kolkata)"),
    ("Europe/London", "United Kingdom (Europe/London)"),
    ("UTC", "UTC"),
    ("Asia/Dubai", "United Arab Emirates (Asia/Dubai)"),
    ("Asia/Singapore", "Singapore (Asia/Singapore)"),
    ("Asia/Colombo", "Sri Lanka (Asia/Colombo)"),
    ("Asia/Dhaka", "Bangladesh (Asia/Dhaka)"),
    ("Asia/Kathmandu", "Nepal (Asia/Kathmandu)"),
    ("America/New_York", "US Eastern (America/New_York)"),
    ("America/Chicago", "US Central (America/Chicago)"),
    ("America/Denver", "US Mountain (America/Denver)"),
    ("America/Los_Angeles", "US Pacific (America/Los_Angeles)"),
    ("Australia/Sydney", "Australia Eastern (Australia/Sydney)"),
)
BRANCH_CURRENCY_OPTIONS = (
    ("INR", "Indian rupee (INR)"),
    ("GBP", "Pound sterling (GBP)"),
    ("USD", "US dollar (USD)"),
    ("EUR", "Euro (EUR)"),
    ("AED", "UAE dirham (AED)"),
    ("SGD", "Singapore dollar (SGD)"),
    ("LKR", "Sri Lankan rupee (LKR)"),
    ("BDT", "Bangladeshi taka (BDT)"),
    ("NPR", "Nepalese rupee (NPR)"),
    ("AUD", "Australian dollar (AUD)"),
)
BOOKING_SELECT = """
    SELECT b.id, b.student_name, b.mobile_number, b.student_user_id,
           b.machine_id, b.instructor_id, b.branch_id, b.target_date,
           b.start_time, b.end_time, b.validation_status, b.notes,
           b.review_notes, b.reviewed_by, b.reviewed_at, b.cancelled_at,
           b.attendance_recorded_by, b.attendance_recorded_at,
           b.created_at, b.updated_at, b.service_id,
           COALESCE(NULLIF(b.service_name, ''), s.name, m.category)
               AS service_name,
           b.service_price_cents, b.currency,
           b.buffer_before_minutes, b.buffer_after_minutes,
           b.allow_double_booking,
           b.calendar_revision, b.series_id, b.repeat_rule,
           b.series_position, b.series_count,
           m.machine_code, m.category AS machine_category,
           m.location AS machine_location,
           i.name AS instructor_name, br.name AS branch_name,
           u.email AS student_email, s.color AS service_color
    FROM bookings b
    JOIN machines m ON m.id = b.machine_id
    JOIN instructors i ON i.id = b.instructor_id
    JOIN branches br ON br.id = b.branch_id
    LEFT JOIN users u ON u.id = b.student_user_id
    LEFT JOIN services s ON s.id = b.service_id
"""


app = Flask(__name__)
app.config.update(
    SECRET_KEY=os.environ.get("A2Z_SECRET_KEY") or secrets.token_hex(32),
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=os.environ.get("A2Z_SECURE_COOKIES", "0") == "1",
    A2Z_STUDENT_SELF_BOOKING=(
        os.environ.get("A2Z_STUDENT_SELF_BOOKING", "0") == "1"
    ),
    PERMANENT_SESSION_LIFETIME=timedelta(hours=8),
    MAX_CONTENT_LENGTH=6 * 1024 * 1024,
    CSRF_ENABLED=True,
)

login_manager = LoginManager(app)
login_manager.login_view = "login"
login_manager.login_message = "Please sign in to continue."
login_manager.login_message_category = "info"


class User(UserMixin):
    def __init__(self, row):
        self.id = int(row["id"])
        self.username = row["username"]
        self.role = row["role"]
        self.instructor_id = row["instructor_id"]
        self.full_name = row["full_name"] or row["username"]
        self.email = row["email"] or ""
        self.phone = row["phone"] or ""
        self.branch_id = row["branch_id"]
        self._active = bool(row["is_active"] and row["login_enabled"])
        self.must_change_password = bool(row["must_change_password"])
        raw_permissions = (
            row["permission_mask"] if "permission_mask" in row.keys() else None
        )
        self.permission_mask = (
            DEFAULT_ROLE_PERMISSIONS.get(self.role, 0)
            if raw_permissions is None
            else int(raw_permissions)
        )

    @property
    def is_active(self):
        return self._active

    def has_permission(self, permission):
        if permission == "administrator":
            return self.role == "admin"
        if self.role == "admin":
            return True
        bit = PERMISSION_BITS.get(permission)
        return bool(bit and self.permission_mask & bit)


@login_manager.user_loader
def load_user(user_id):
    try:
        parsed_id = int(user_id)
    except (TypeError, ValueError):
        return None
    with get_db() as conn:
        row = conn.execute("SELECT * FROM users WHERE id = ?", (parsed_id,)).fetchone()
    if not row or not row["is_active"] or not row["login_enabled"]:
        return None
    if row["role"] == "instructor":
        with get_db() as conn:
            profile = conn.execute(
                """
                SELECT is_active, verification_status FROM instructors
                WHERE id = ?
                """,
                (row["instructor_id"],),
            ).fetchone()
        if not profile or not profile["is_active"] or profile["verification_status"] != "verified":
            return None
    return User(row)


@login_manager.unauthorized_handler
def unauthorized():
    if request.path.startswith("/api/"):
        return jsonify({"error": "Please sign in to continue."}), 401
    return redirect(url_for("login", next=request.full_path))


def role_required(*roles):
    def decorator(view):
        @wraps(view)
        @login_required
        def wrapped(*args, **kwargs):
            if current_user.role not in roles:
                abort(403)
            return view(*args, **kwargs)

        return wrapped

    return decorator


def permission_required(*permissions):
    def decorator(view):
        @wraps(view)
        @login_required
        def wrapped(*args, **kwargs):
            if not all(current_user.has_permission(item) for item in permissions):
                abort(403)
            return view(*args, **kwargs)

        return wrapped

    return decorator


def _permission_mask_from_form(role):
    if role == "admin":
        return ALL_STAFF_PERMISSIONS
    selected = set(request.form.getlist("permissions"))
    return sum(
        bit for permission, bit in PERMISSION_BITS.items() if permission in selected
    )


def _require_student_self_booking():
    """Hide the retired student booking surface unless explicitly enabled."""
    if not app.config["A2Z_STUDENT_SELF_BOOKING"]:
        abort(404)


def csrf_token():
    token = session.get("csrf_token")
    if not token:
        token = secrets.token_urlsafe(32)
        session["csrf_token"] = token
    return token


@app.before_request
def protect_mutating_requests():
    if request.method not in {"POST", "PUT", "PATCH", "DELETE"}:
        return None
    if not app.config.get("CSRF_ENABLED", True):
        return None
    supplied = request.headers.get("X-CSRF-Token") or request.form.get("csrf_token", "")
    expected = session.get("csrf_token", "")
    if not supplied or not expected or not hmac.compare_digest(supplied, expected):
        if request.path.startswith("/api/"):
            return jsonify({"error": "Your session expired. Refresh the page and try again."}), 400
        abort(400, description="Your session expired. Please go back, refresh, and try again.")
    return None


@app.before_request
def require_temporary_password_change():
    """Keep administrator-issued temporary passwords genuinely temporary."""
    if not current_user.is_authenticated or not current_user.must_change_password:
        return None
    allowed = {"account_password", "logout", "static"}
    if request.endpoint in allowed:
        return None
    if request.path.startswith("/api/"):
        return jsonify({"error": "Change your temporary password before continuing."}), 403
    return redirect(url_for("account_password"))


@app.after_request
def add_security_headers(response):
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    response.headers.setdefault(
        "Permissions-Policy",
        "camera=(), microphone=(), geolocation=(), payment=(), usb=()",
    )
    response.headers.setdefault(
        "Content-Security-Policy",
        "default-src 'self'; img-src 'self' data:; style-src 'self'; "
        "script-src 'self'; connect-src 'self'; frame-ancestors 'none'; "
        "base-uri 'self'; form-action 'self'",
    )
    if current_user.is_authenticated:
        response.headers.setdefault("Cache-Control", "private, no-store")
    if app.config["SESSION_COOKIE_SECURE"]:
        response.headers.setdefault(
            "Strict-Transport-Security", "max-age=31536000; includeSubDomains"
        )
    return response


@app.context_processor
def shared_template_context():
    return {
        "csrf_token": csrf_token,
        "current_year": datetime.now(IST).year,
        "institute_phone": "+91 96335 79475",
        "student_self_booking_enabled": app.config[
            "A2Z_STUDENT_SELF_BOOKING"
        ],
    }


@app.template_filter("friendly_date")
def friendly_date(value):
    try:
        return date.fromisoformat(str(value)).strftime("%a, %d %b %Y")
    except (TypeError, ValueError):
        return value


@app.template_filter("friendly_time")
def friendly_time(value):
    try:
        return datetime.strptime(value, "%H:%M").strftime("%I:%M %p").lstrip("0")
    except (TypeError, ValueError):
        return value


def _role_home():
    if (
        current_user.role in {"admin", "booking_agent", "instructor"}
        and not app.config["A2Z_STUDENT_SELF_BOOKING"]
    ):
        return url_for("calendar_view")
    if current_user.role == "admin":
        return url_for("admin_dashboard")
    if current_user.role == "instructor":
        return url_for("instructor_dashboard")
    if current_user.role == "booking_agent":
        return url_for("calendar_view")
    return url_for("student_dashboard")


def _safe_next_url(candidate):
    if not candidate:
        return None
    parsed = urlsplit(candidate)
    if parsed.scheme or parsed.netloc or not candidate.startswith("/"):
        return None
    return candidate


def _booking_rows(conn, where="", params=(), order_by="b.target_date ASC, b.start_time ASC"):
    query = BOOKING_SELECT
    if where:
        query += f" WHERE {where}"
    query += f" ORDER BY {order_by}"
    return [dict(row) for row in conn.execute(query, tuple(params)).fetchall()]


def _audit(conn, event_type, booking_id=None, details=None):
    actor_id = current_user.id if current_user.is_authenticated else None
    conn.execute(
        """
        INSERT INTO audit_events (actor_user_id, booking_id, event_type, details)
        VALUES (?, ?, ?, ?)
        """,
        (actor_id, booking_id, event_type, json.dumps(details or {}, ensure_ascii=True)),
    )


def _parse_resource_ids(machine_value, instructor_value):
    try:
        machine_id = int(machine_value)
        instructor_id = int(instructor_value)
        if machine_id < 1 or instructor_id < 1:
            raise ValueError
        return machine_id, instructor_id
    except (TypeError, ValueError):
        raise ValueError("Choose a valid machine and instructor.") from None


def _parse_service_ids(raw_value):
    if raw_value in (None, "", []):
        return []
    if isinstance(raw_value, str):
        try:
            decoded = json.loads(raw_value)
            values = decoded if isinstance(decoded, list) else raw_value.split(",")
        except json.JSONDecodeError:
            values = raw_value.split(",")
    elif isinstance(raw_value, (list, tuple)):
        values = raw_value
    else:
        values = [raw_value]
    service_ids = []
    for value in values:
        try:
            service_id = int(value)
        except (TypeError, ValueError):
            raise ValueError("Choose valid training services.") from None
        if service_id < 1 or service_id in service_ids:
            raise ValueError("Choose valid training services.")
        service_ids.append(service_id)
    if len(service_ids) > 6:
        raise ValueError("Choose no more than six services in one appointment.")
    return service_ids


def _service_catalog(conn, branch_id, instructor_id=None):
    params = [branch_id]
    instructor_clause = ""
    if instructor_id:
        instructor_clause = """
            AND (
                NOT EXISTS (
                    SELECT 1 FROM service_instructors si0
                    WHERE si0.service_id = s.id
                )
                OR EXISTS (
                    SELECT 1 FROM service_instructors si1
                    WHERE si1.service_id = s.id AND si1.instructor_id = ?
                )
            )
        """
        params.append(instructor_id)
    rows = [
        dict(row)
        for row in conn.execute(
            f"""
            SELECT s.* FROM services s
            WHERE s.branch_id = ? AND s.is_active = 1
            {instructor_clause}
            ORDER BY lower(COALESCE(s.category, '')), lower(s.name)
            """,
            params,
        ).fetchall()
    ]
    if not rows:
        return []
    service_ids = [row["id"] for row in rows]
    placeholders = ",".join("?" for _ in service_ids)
    machine_map = {service_id: [] for service_id in service_ids}
    for row in conn.execute(
        f"""
        SELECT service_id, machine_id FROM service_machines
        WHERE service_id IN ({placeholders}) ORDER BY machine_id
        """,
        service_ids,
    ).fetchall():
        machine_map[row["service_id"]].append(row["machine_id"])
    instructor_map = {service_id: [] for service_id in service_ids}
    for row in conn.execute(
        f"""
        SELECT service_id, instructor_id FROM service_instructors
        WHERE service_id IN ({placeholders}) ORDER BY instructor_id
        """,
        service_ids,
    ).fetchall():
        instructor_map[row["service_id"]].append(row["instructor_id"])
    field_map = {service_id: [] for service_id in service_ids}
    for field in conn.execute(
        f"""
        SELECT * FROM service_intake_fields
        WHERE service_id IN ({placeholders}) AND is_active = 1
        ORDER BY service_id, sort_order, id
        """,
        service_ids,
    ).fetchall():
        item = dict(field)
        try:
            item["options"] = json.loads(item.get("options_json") or "[]")
        except json.JSONDecodeError:
            item["options"] = []
        field_map[item["service_id"]].append(item)
    for row in rows:
        row["category"] = (row.get("category") or "SERVICES").strip() or "SERVICES"
        row["machine_ids"] = machine_map[row["id"]]
        row["instructor_ids"] = instructor_map[row["id"]]
        row["intake_fields"] = field_map[row["id"]]
        row["weekday_numbers"] = [
            int(value)
            for value in (row.get("available_weekdays") or "").split(",")
            if value.strip().isdigit()
        ]
    return rows


def _selected_services(
    conn,
    branch_id,
    service_ids,
    *,
    instructor_id=None,
    machine_id=None,
    target=None,
    enforce_instructor_assignment=True,
):
    if not service_ids:
        return []
    placeholders = ",".join("?" for _ in service_ids)
    rows = [
        dict(row)
        for row in conn.execute(
            f"""
            SELECT * FROM services
            WHERE id IN ({placeholders}) AND branch_id = ? AND is_active = 1
            """,
            (*service_ids, branch_id),
        ).fetchall()
    ]
    by_id = {row["id"]: row for row in rows}
    if len(by_id) != len(service_ids):
        raise ValueError("One of those services is no longer available.")
    ordered = [by_id[service_id] for service_id in service_ids]
    for service in ordered:
        if target is not None:
            weekdays = {
                int(value)
                for value in (service.get("available_weekdays") or "").split(",")
                if value.strip().isdigit()
            }
            if target.weekday() not in weekdays:
                raise ValueError(f"{service['name']} is not bookable on that day.")
        if instructor_id is not None and enforce_instructor_assignment:
            mapped = conn.execute(
                "SELECT count(*) FROM service_instructors WHERE service_id = ?",
                (service["id"],),
            ).fetchone()[0]
            if mapped and not conn.execute(
                """
                SELECT 1 FROM service_instructors
                WHERE service_id = ? AND instructor_id = ?
                """,
                (service["id"], instructor_id),
            ).fetchone():
                raise ValueError(f"{service['name']} is not offered by that instructor.")
        if machine_id is not None:
            mapped = conn.execute(
                "SELECT count(*) FROM service_machines WHERE service_id = ?",
                (service["id"],),
            ).fetchone()[0]
            if mapped and not conn.execute(
                """
                SELECT 1 FROM service_machines
                WHERE service_id = ? AND machine_id = ?
                """,
                (service["id"], machine_id),
            ).fetchone():
                raise ValueError("Choose equipment that supports every selected service.")
    return ordered


def _validate_intake(conn, services, raw_answers):
    if not services:
        return [], 0, 0
    service_ids = [service["id"] for service in services]
    placeholders = ",".join("?" for _ in service_ids)
    fields = [
        dict(row)
        for row in conn.execute(
            f"""
            SELECT * FROM service_intake_fields
            WHERE service_id IN ({placeholders}) AND is_active = 1
            ORDER BY service_id, sort_order, id
            """,
            service_ids,
        ).fetchall()
    ]
    answers = raw_answers if isinstance(raw_answers, dict) else {}
    values = []
    duration_adjustment = 0
    price_adjustment = 0
    truthy = {"1", "true", "yes", "on"}
    for field in fields:
        raw = answers.get(str(field["id"]), answers.get(field["field_key"], ""))
        if isinstance(raw, (dict, list)):
            raw = json.dumps(raw, ensure_ascii=False)
        value = str(raw or "").strip()
        if field["field_type"] == "checkbox":
            checked = value.lower() in truthy
            value = "Yes" if checked else ""
            if field["is_required"] and not checked:
                raise ValueError(f"Complete the required field: {field['label']}.")
        elif field["is_required"] and not value:
            raise ValueError(f"Complete the required field: {field['label']}.")
        if field["field_type"] == "select" and value:
            try:
                choices = json.loads(field["options_json"] or "[]")
            except json.JSONDecodeError:
                choices = []
            if value not in choices:
                raise ValueError(f"Choose a valid option for {field['label']}.")
        if len(value) > 1500:
            raise ValueError(f"Keep {field['label']} under 1,500 characters.")
        if value:
            duration_adjustment += int(field["duration_adjustment_minutes"] or 0)
            price_adjustment += int(field["price_adjustment_cents"] or 0)
        values.append(
            {
                "field_id": field["id"],
                "field_key": field["field_key"],
                "field_label": field["label"],
                "value_text": value or None,
            }
        )
    return values, duration_adjustment, price_adjustment


def _minutes_to_time(value):
    value = max(0, min(23 * 60 + 59, int(value)))
    return f"{value // 60:02d}:{value % 60:02d}"


def _free_with_padding(bookings, work_windows, before_minutes, after_minutes):
    expanded = []
    for booking in bookings:
        start = _time_to_minutes(booking["start_time"])
        end = _time_to_minutes(booking["end_time"])
        expanded.append(
            {
                "start_time": _minutes_to_time(
                    start - int(booking.get("buffer_before_minutes") or 0)
                ),
                "end_time": _minutes_to_time(
                    end + int(booking.get("buffer_after_minutes") or 0)
                ),
            }
        )
    free = compute_free_slots(expanded, work_windows=work_windows)
    padded = []
    for window in free:
        start = _time_to_minutes(window["start"]) + before_minutes
        end = _time_to_minutes(window["end"]) - after_minutes
        start = ((start + 29) // 30) * 30
        if start < end:
            padded.append(
                {"start": _minutes_to_time(start), "end": _minutes_to_time(end)}
            )
    return padded


def _cancel_queued_booking_notifications(conn, booking_id):
    """Stop obsolete messages before an appointment changes state or timing."""
    conn.execute(
        """
        UPDATE notification_queue
        SET status = 'cancelled', locked_at = NULL, next_attempt_at = NULL
        WHERE booking_id = ? AND status = 'queued'
        """,
        (booking_id,),
    )


def _queue_booking_notifications(conn, booking_id, event_type):
    row = conn.execute(
        """
        SELECT b.*, u.email, u.phone,
               COALESCE(cp.reminders_enabled, 1) AS reminders_enabled,
               COALESCE(cp.preferred_channel, br.reminder_channel, 'email')
                   AS preferred_channel
        FROM bookings b
        LEFT JOIN users u ON u.id = b.student_user_id
        LEFT JOIN client_profiles cp ON cp.user_id = b.student_user_id
        LEFT JOIN branches br ON br.id = b.branch_id
        WHERE b.id = ?
        """,
        (booking_id,),
    ).fetchone()
    if not row:
        return
    now = datetime.now(IST)
    appointment_at = datetime.combine(
        date.fromisoformat(row["target_date"]),
        datetime.strptime(row["start_time"], "%H:%M").time(),
        IST,
    )
    _cancel_queued_booking_notifications(conn, booking_id)
    jobs = [(event_type, now)]
    if event_type in {"appointment_approved", "appointment_rescheduled"}:
        for hours in (24, 2):
            scheduled = appointment_at - timedelta(hours=hours)
            if scheduled > now:
                jobs.append((f"reminder_{hours}h", scheduled))
    destinations = {
        "email": (row["email"] or "").strip(),
        "sms": (row["phone"] or row["mobile_number"] or "").strip(),
    }
    preferred = row["preferred_channel"]
    if preferred not in destinations or not destinations[preferred]:
        preferred = "sms" if destinations["sms"] else "email"
    for job_type, scheduled_for in jobs:
        if job_type.startswith("reminder_") and not row["reminders_enabled"]:
            continue
        destination = destinations[preferred]
        if not destination:
            continue
        conn.execute(
            """
            INSERT INTO notification_queue
                (booking_id, channel, event_type, destination, scheduled_for)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(booking_id, channel, event_type, scheduled_for)
            DO UPDATE SET
                destination = excluded.destination,
                status = CASE
                    WHEN notification_queue.status = 'sent' THEN 'sent'
                    ELSE 'queued'
                END,
                attempts = CASE
                    WHEN notification_queue.status = 'sent'
                        THEN notification_queue.attempts
                    ELSE 0
                END,
                last_error = NULL,
                locked_at = NULL,
                next_attempt_at = NULL
            """,
            (
                booking_id,
                preferred,
                job_type,
                destination,
                scheduled_for.isoformat(),
            ),
        )


def _rebuild_booking_reminders(conn, booking_id):
    """Refresh future reminders after contact, channel, or opt-out changes."""
    conn.execute(
        """
        UPDATE notification_queue
        SET status = 'cancelled', locked_at = NULL, next_attempt_at = NULL
        WHERE booking_id = ? AND status = 'queued'
          AND event_type LIKE 'reminder_%'
        """,
        (booking_id,),
    )
    row = conn.execute(
        """
        SELECT b.*, u.email, u.phone,
               COALESCE(cp.reminders_enabled, 1) AS reminders_enabled,
               COALESCE(cp.preferred_channel, br.reminder_channel, 'email')
                   AS preferred_channel
        FROM bookings b
        LEFT JOIN users u ON u.id = b.student_user_id
        LEFT JOIN client_profiles cp ON cp.user_id = b.student_user_id
        LEFT JOIN branches br ON br.id = b.branch_id
        WHERE b.id = ?
        """,
        (booking_id,),
    ).fetchone()
    if (
        not row
        or row["validation_status"] != "Approved"
        or not row["reminders_enabled"]
    ):
        return

    now = datetime.now(IST)
    appointment_at = datetime.combine(
        date.fromisoformat(row["target_date"]),
        datetime.strptime(row["start_time"], "%H:%M").time(),
        IST,
    )
    destinations = {
        "email": (row["email"] or "").strip(),
        "sms": (row["phone"] or row["mobile_number"] or "").strip(),
    }
    preferred = row["preferred_channel"]
    if preferred not in destinations or not destinations[preferred]:
        preferred = "sms" if destinations["sms"] else "email"
    destination = destinations[preferred]
    if not destination:
        return

    for hours in (24, 2):
        scheduled = appointment_at - timedelta(hours=hours)
        if scheduled <= now:
            continue
        conn.execute(
            """
            INSERT INTO notification_queue
                (booking_id, channel, event_type, destination, scheduled_for)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(booking_id, channel, event_type, scheduled_for)
            DO UPDATE SET
                destination = excluded.destination,
                status = CASE
                    WHEN notification_queue.status = 'sent' THEN 'sent'
                    ELSE 'queued'
                END,
                attempts = CASE
                    WHEN notification_queue.status = 'sent'
                        THEN notification_queue.attempts
                    ELSE 0
                END,
                last_error = NULL,
                locked_at = NULL,
                next_attempt_at = NULL
            """,
            (
                booking_id,
                preferred,
                f"reminder_{hours}h",
                destination,
                scheduled.isoformat(),
            ),
        )


def _cancel_active_bookings(conn, booking_ids):
    """Cancel selected live bookings with revision and notification safety."""
    cancelled_ids = []
    for booking_id in dict.fromkeys(int(value) for value in booking_ids):
        cursor = conn.execute(
            """
            UPDATE bookings
            SET validation_status = 'Cancelled',
                cancelled_at = CURRENT_TIMESTAMP,
                calendar_revision = calendar_revision + 1,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ? AND validation_status IN ('Pending', 'Approved')
            """,
            (booking_id,),
        )
        if cursor.rowcount:
            cancelled_ids.append(booking_id)
            _queue_booking_notifications(
                conn, booking_id, "appointment_cancelled"
            )
    return cancelled_ids


def _save_intake_files(conn, booking_id):
    allowed_extensions = {".pdf", ".jpg", ".jpeg", ".png"}
    allowed_types = {"application/pdf", "image/jpeg", "image/png"}
    storage_dir = Path(app.instance_path) / "intake_uploads"
    for field_name, upload in request.files.items():
        if not field_name.startswith("intake_file_") or not upload.filename:
            continue
        try:
            field_id = int(field_name.removeprefix("intake_file_"))
        except ValueError:
            raise ValueError("One of the uploaded files is not linked to a valid question.") from None
        value_row = conn.execute(
            """
            SELECT id FROM booking_intake_values
            WHERE booking_id = ? AND field_id = ?
            """,
            (booking_id, field_id),
        ).fetchone()
        if not value_row:
            raise ValueError("One of the uploaded files is not linked to this appointment.")
        original_name = secure_filename(upload.filename)
        extension = Path(original_name).suffix.lower()
        if extension not in allowed_extensions or upload.mimetype not in allowed_types:
            raise ValueError("Upload a PDF, JPG, or PNG file.")
        content = upload.read(5 * 1024 * 1024 + 1)
        if len(content) > 5 * 1024 * 1024:
            raise ValueError("Keep each uploaded file under 5 MB.")
        storage_dir.mkdir(parents=True, exist_ok=True)
        storage_name = f"{secrets.token_urlsafe(18)}{extension}"
        storage_path = storage_dir / storage_name
        storage_path.write_bytes(content)
        conn.execute(
            """
            UPDATE booking_intake_values
            SET value_text = 'Uploaded file', file_name = ?, file_path = ?,
                mime_type = ?, file_size = ?
            WHERE id = ?
            """,
            (
                original_name,
                str(storage_path),
                upload.mimetype,
                len(content),
                value_row["id"],
            ),
        )


def _validate_booking_date(raw_date, *, enforce_online_window=True):
    try:
        target = date.fromisoformat(raw_date)
    except (TypeError, ValueError):
        raise ValueError("Choose a valid training date.") from None
    if not enforce_online_window:
        return target
    today = datetime.now(IST).date()
    if target < today:
        raise ValueError("Training cannot be booked in the past.")
    if target > today + timedelta(days=90):
        raise ValueError("Bookings open 90 days ahead.")
    return target


def _add_months(value, amount):
    """Move a date by whole months while keeping the closest valid day."""
    month_index = (value.month - 1) + amount
    year = value.year + month_index // 12
    month = (month_index % 12) + 1
    day = min(value.day, monthrange(year, month)[1])
    return date(year, month, day)


def _repeat_dates(start, raw_rule, raw_count):
    """Return bounded dates for staff-created repeating entries."""
    aliases = {
        "": "none",
        "none": "none",
        "daily": "daily",
        "weekdays": "weekdays",
        "daily_weekdays": "weekdays",
        "mwf": "mwf",
        "mon_wed_fri": "mwf",
        "tuth": "tuth",
        "tue_thu": "tuth",
        "weekly": "weekly",
        "fortnightly": "every_2_weeks",
        "every_2_weeks": "every_2_weeks",
        "every_3_weeks": "every_3_weeks",
        "every_4_weeks": "every_4_weeks",
        "every_5_weeks": "every_5_weeks",
        "every_6_weeks": "every_6_weeks",
        "every_8_weeks": "every_8_weeks",
        "monthly": "monthly",
        "every_2_months": "every_2_months",
        "yearly": "yearly",
    }
    rule = aliases.get(str(raw_rule or "none").strip().lower())
    if not rule:
        raise ValueError("Choose a valid repeat pattern.")
    try:
        count = int(raw_count or 1)
    except (TypeError, ValueError):
        raise ValueError("Choose a valid number of occurrences.") from None
    if rule == "none":
        return [start], rule
    if count < 2 or count > 52:
        raise ValueError("Repeating entries can contain between 2 and 52 occurrences.")

    dates = [start]
    current = start
    weekday_sets = {
        "weekdays": {0, 1, 2, 3, 4},
        "mwf": {0, 2, 4},
        "tuth": {1, 3},
    }
    while len(dates) < count:
        if rule == "daily":
            current += timedelta(days=1)
        elif rule in weekday_sets:
            current += timedelta(days=1)
            while current.weekday() not in weekday_sets[rule]:
                current += timedelta(days=1)
        elif rule == "weekly":
            current += timedelta(days=7)
        elif rule.startswith("every_") and rule.endswith("_weeks"):
            current += timedelta(days=7 * int(rule.split("_")[1]))
        elif rule == "monthly":
            current = _add_months(start, len(dates))
        elif rule == "every_2_months":
            current = _add_months(start, 2 * len(dates))
        elif rule == "yearly":
            current = _add_months(start, 12 * len(dates))
        dates.append(current)
    return dates, rule


def _normalise_phone(value):
    value = (value or "").strip()
    if value.startswith("+"):
        prefix, digits = "+", re.sub(r"\D", "", value)
        normalised = prefix + digits
    else:
        normalised = re.sub(r"\D", "", value)
    digit_count = len(re.sub(r"\D", "", normalised))
    if digit_count < 10 or digit_count > 15:
        raise ValueError("Enter a valid phone or WhatsApp number.")
    return normalised


def _time_to_minutes(value):
    try:
        parsed = datetime.strptime(str(value), "%H:%M")
    except (TypeError, ValueError):
        raise ValueError("Choose valid start and end times.") from None
    return parsed.hour * 60 + parsed.minute


def _validate_availability_range(start_time, end_time, *, within_hours=True):
    start_time = str(start_time or "")
    end_time = str(end_time or "")
    start_minutes = _time_to_minutes(start_time)
    end_minutes = _time_to_minutes(end_time)
    if start_minutes % 15 or end_minutes % 15:
        raise ValueError("Availability must use 15-minute increments.")
    if start_minutes >= end_minutes:
        raise ValueError("The end time must be later than the start time.")
    if within_hours and not any(
        start_minutes >= _time_to_minutes(window_start)
        and end_minutes <= _time_to_minutes(window_end)
        for window_start, window_end in WORK_WINDOWS
    ):
        raise ValueError("Keep availability inside institute hours.")
    return start_time, end_time


def _instructor_work_windows(conn, instructor_id, target):
    instructor = conn.execute(
        "SELECT uses_custom_availability FROM instructors WHERE id = ?",
        (instructor_id,),
    ).fetchone()
    if not instructor:
        return []
    if not instructor["uses_custom_availability"]:
        return list(WORK_WINDOWS)
    return [
        (row["start_time"], row["end_time"])
        for row in conn.execute(
            """
            SELECT start_time, end_time FROM instructor_weekly_availability
            WHERE instructor_id = ? AND weekday = ? ORDER BY start_time
            """,
            (instructor_id, target.weekday()),
        ).fetchall()
    ]


def _student_is_assigned(conn, student_id, instructor_id):
    return bool(
        conn.execute(
            """
            SELECT 1 FROM student_instructor_assignments
            WHERE student_user_id = ? AND instructor_id = ? AND is_active = 1
            """,
            (student_id, instructor_id),
        ).fetchone()
    )


def _validate_email(value):
    email = (value or "").strip().lower()
    if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
        raise ValueError("Enter a valid email address.")
    return email


def _validate_username(value):
    username = (value or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9._-]{3,50}", username):
        raise ValueError("Username must be 3–50 letters, numbers, dots, dashes or underscores.")
    return username


def _validate_full_name(value):
    full_name = " ".join((value or "").split())
    if len(full_name) < 2 or len(full_name) > 100:
        raise ValueError("Enter the person's full name.")
    return full_name


def _optional_email(value):
    value = (value or "").strip()
    return _validate_email(value) if value else None


def _optional_phone(value):
    value = (value or "").strip()
    return _normalise_phone(value) if value else None


def _optional_birthday(value):
    value = (value or "").strip()
    if not value:
        return None
    try:
        birthday = date.fromisoformat(value)
    except ValueError:
        raise ValueError("Enter the birthday as a valid date.") from None
    if birthday > datetime.now(IST).date():
        raise ValueError("The birthday cannot be in the future.")
    return birthday.isoformat()


def _bounded_client_text(value, label, limit):
    text = " ".join((value or "").split())
    if len(text) > limit:
        raise ValueError(f"Keep {label} under {limit} characters.")
    return text or None


class DuplicateClientError(ValueError):
    def __init__(self, record):
        self.client_id = record["id"] if record["role"] == "student" else None
        super().__init__(
            "A client or staff record already uses those contact details: "
            f"{record['full_name'] or record['username']}."
        )


class AppointmentConflictError(ValueError):
    pass


def _appointment_conflict_message(buffer_before=0, buffer_after=0):
    """Return an actionable staff-calendar conflict explanation."""
    padding = []
    if int(buffer_before or 0):
        padding.append(f"{int(buffer_before)} minutes before")
    if int(buffer_after or 0):
        padding.append(f"{int(buffer_after)} minutes after")
    if padding:
        return (
            "The visible appointment time is free, but its private padding "
            f"({ ' and '.join(padding) }) overlaps another appointment."
        )
    return "This time conflicts with the client, instructor, or equipment schedule."


def _appointment_conflict_for_range(
    conn,
    *,
    target,
    start_time,
    end_time,
    student_id,
    instructor_id,
    machine_id,
    exclude_booking_id=None,
):
    """Explain the first visible resource conflict for a staff calendar move."""
    active_placeholders = ",".join("?" for _ in ACTIVE_BOOKING_STATUSES)
    exclude_clause = ""
    base_params = [target.isoformat(), end_time, start_time, *ACTIVE_BOOKING_STATUSES]
    if exclude_booking_id is not None:
        exclude_clause = " AND b.id != ?"
        base_params.append(exclude_booking_id)

    checks = (
        ("b.instructor_id = ?", instructor_id, "The destination instructor already has an appointment during this time."),
        ("b.machine_id = ?", machine_id, "The selected equipment is already booked during this time."),
        ("b.student_user_id = ?", student_id, "This client already has another appointment during this time."),
    )
    for resource_clause, resource_id, message in checks:
        row = conn.execute(
            f"""
            SELECT b.id
            FROM bookings b
            WHERE b.target_date = ?
              AND b.start_time < ? AND b.end_time > ?
              AND b.validation_status IN ({active_placeholders})
              AND {resource_clause}
              {exclude_clause}
            LIMIT 1
            """,
            (*base_params[:-1], resource_id, base_params[-1])
            if exclude_booking_id is not None
            else (*base_params, resource_id),
        ).fetchone()
        if row:
            return message
    return _appointment_conflict_message()


def _matching_contact_record(
    conn, *, emails=(), phones=(), exclude_user_id=None
):
    email_values = sorted(
        {str(value).strip().lower() for value in emails if value}
    )
    phone_values = sorted({str(value).strip() for value in phones if value})
    contact_clauses = []
    params = [exclude_user_id or -1]
    for email in email_values:
        contact_clauses.append(
            """
            (lower(COALESCE(u.email, '')) = ?
             OR lower(u.username) = ?
             OR lower(COALESCE(cp.secondary_email, '')) = ?)
            """
        )
        params.extend((email, email, email))
    for phone in phone_values:
        contact_clauses.append(
            """
            (COALESCE(u.phone, '') = ?
             OR COALESCE(cp.secondary_phone, '') = ?)
            """
        )
        params.extend((phone, phone))
    if not contact_clauses:
        return None
    return conn.execute(
        f"""
        SELECT u.id, u.full_name, u.username, u.role
        FROM users u
        LEFT JOIN client_profiles cp ON cp.user_id = u.id
        WHERE u.id != ? AND ({" OR ".join(contact_clauses)})
        ORDER BY u.is_active DESC, u.id
        LIMIT 1
        """,
        params,
    ).fetchone()


def _client_contact_values(payload):
    email = _optional_email(payload.get("email"))
    secondary_email = _optional_email(payload.get("secondary_email"))
    phone = _optional_phone(payload.get("phone"))
    secondary_phone = _optional_phone(payload.get("secondary_phone"))
    if email and secondary_email and email == secondary_email:
        raise ValueError("Use a different secondary email address.")
    if phone and secondary_phone and phone == secondary_phone:
        raise ValueError("Use a different secondary phone number.")
    return {
        "email": email,
        "secondary_email": secondary_email,
        "phone": phone,
        "secondary_phone": secondary_phone,
    }


def _client_profile_values(payload):
    preferred_channel = (payload.get("preferred_channel") or "email").lower()
    if preferred_channel not in {"email", "sms"}:
        raise ValueError("Choose email or SMS reminders.")
    reminder_value = payload.get("reminders_enabled", True)
    if isinstance(reminder_value, str):
        reminders_enabled = reminder_value.lower() in {"1", "true", "yes", "on"}
    else:
        reminders_enabled = bool(reminder_value)
    internal_notes = (payload.get("internal_notes") or "").strip()
    tags = ", ".join(
        item.strip()
        for item in str(payload.get("tags") or "").split(",")
        if item.strip()
    )
    if len(internal_notes) > 2000 or len(tags) > 250:
        raise ValueError(
            "Keep client notes under 2,000 characters and tags under 250."
        )
    return {
        "birthday": _optional_birthday(payload.get("birthday")),
        "gender": _bounded_client_text(payload.get("gender"), "gender", 50),
        "zip_code": _bounded_client_text(payload.get("zip_code"), "postcode", 20),
        "city": _bounded_client_text(payload.get("city"), "city", 100),
        "street": _bounded_client_text(payload.get("street"), "street address", 300),
        "internal_notes": internal_notes or None,
        "tags": tags or None,
        "reminders_enabled": 1 if reminders_enabled else 0,
        "preferred_channel": preferred_channel,
    }


def _ensure_identity_available(conn, username, email, *, exclude_user_id=None):
    existing = conn.execute(
        """
        SELECT id FROM users
        WHERE id != ? AND (
            lower(username) IN (lower(?), lower(?))
            OR (email IS NOT NULL AND email != ''
                AND lower(email) IN (lower(?), lower(?)))
        ) LIMIT 1
        """,
        (exclude_user_id or -1, username, email, username, email),
    ).fetchone()
    if existing:
        raise ValueError("That username or email conflicts with another account.")


def _validate_branch(conn, value):
    try:
        branch_id = int(value)
    except (TypeError, ValueError):
        raise ValueError("Choose a valid branch.") from None
    if not conn.execute(
        "SELECT 1 FROM branches WHERE id = ? AND is_active = 1", (branch_id,)
    ).fetchone():
        raise ValueError("Choose a valid branch.")
    return branch_id


def _temporary_password():
    # Easy to transcribe while still carrying more entropy than a typical
    # administrator-chosen starter password. It is shown once and only its
    # hash is stored.
    return f"A2Z-{secrets.token_hex(5)}!"


def _available_slots(
    conn,
    branch_id,
    machine_id,
    instructor_id,
    target,
    student_id=None,
    duration_minutes=30,
    buffer_before_minutes=0,
    buffer_after_minutes=0,
    exclude_booking_id=None,
    require_student_assignment=True,
    enforce_advance_notice=True,
    respect_working_hours=True,
):
    resource = conn.execute(
        """
        SELECT m.id
        FROM machines m
        JOIN instructors i ON i.id = ?
        WHERE m.id = ? AND m.branch_id = ? AND i.branch_id = ?
          AND m.is_active = 1 AND i.is_active = 1
          AND i.verification_status = 'verified'
        """,
        (instructor_id, machine_id, branch_id, branch_id),
    ).fetchone()
    if not resource:
        raise ValueError("That machine or instructor is not available at your branch.")
    if (
        student_id
        and require_student_assignment
        and not _student_is_assigned(conn, student_id, instructor_id)
    ):
        raise ValueError("That instructor is not assigned to your account.")

    status_placeholders = ",".join("?" for _ in ACTIVE_BOOKING_STATUSES)
    base_params = (branch_id, target.isoformat(), *ACTIVE_BOOKING_STATUSES)
    exclude_clause = ""
    exclude_params = ()
    if exclude_booking_id is not None:
        exclude_clause = " AND id != ?"
        exclude_params = (exclude_booking_id,)
    machine_bookings = conn.execute(
        f"""
        SELECT start_time, end_time, buffer_before_minutes, buffer_after_minutes
        FROM bookings
        WHERE branch_id = ? AND target_date = ?
          AND validation_status IN ({status_placeholders}) AND machine_id = ?
          {exclude_clause}
        """,
        (*base_params, machine_id, *exclude_params),
    ).fetchall()
    instructor_bookings = conn.execute(
        f"""
        SELECT start_time, end_time, buffer_before_minutes, buffer_after_minutes
        FROM bookings
        WHERE branch_id = ? AND target_date = ?
          AND validation_status IN ({status_placeholders}) AND instructor_id = ?
          {exclude_clause}
        """,
        (*base_params, instructor_id, *exclude_params),
    ).fetchall()

    time_off = conn.execute(
        """
        SELECT start_time, end_time, 0 AS buffer_before_minutes,
               0 AS buffer_after_minutes
        FROM instructor_time_off
        WHERE instructor_id = ? AND target_date = ?
        """,
        (instructor_id, target.isoformat()),
    ).fetchall()

    staff_managed_windows = WORK_WINDOWS if respect_working_hours else [("06:00", "18:30")]
    machine_free = _free_with_padding(
        [dict(row) for row in machine_bookings],
        staff_managed_windows,
        buffer_before_minutes,
        buffer_after_minutes,
    )
    instructor_windows = (
        _instructor_work_windows(conn, instructor_id, target)
        if respect_working_hours
        else staff_managed_windows
    )
    instructor_busy = [dict(row) for row in instructor_bookings] + [
        dict(row) for row in time_off
    ]
    instructor_free = _free_with_padding(
        instructor_busy,
        instructor_windows,
        buffer_before_minutes,
        buffer_after_minutes,
    )
    available = intersect_free_slots(machine_free, instructor_free, duration_minutes)

    if student_id:
        student_exclude_clause = ""
        student_exclude_params = ()
        if exclude_booking_id is not None:
            student_exclude_clause = " AND id != ?"
            student_exclude_params = (exclude_booking_id,)
        student_bookings = conn.execute(
            f"""
            SELECT start_time, end_time FROM bookings
            WHERE target_date = ? AND student_user_id = ?
              AND validation_status IN ({status_placeholders})
              {student_exclude_clause}
            """,
            (
                target.isoformat(),
                student_id,
                *ACTIVE_BOOKING_STATUSES,
                *student_exclude_params,
            ),
        ).fetchall()
        student_free = compute_free_slots(
            [dict(row) for row in student_bookings],
            staff_managed_windows,
        )
        # ``available`` is already expressed as concrete sessions. Retain only
        # sessions fully contained inside one of the student's free windows.
        available = [
            slot
            for slot in available
            if any(
                slot["start"] >= window["start"] and slot["end"] <= window["end"]
                for window in student_free
            )
        ]

    if enforce_advance_notice and target == datetime.now(IST).date():
        earliest = datetime.now(IST) + timedelta(minutes=30)
        available = [
            slot
            for slot in available
            if datetime.combine(target, datetime.strptime(slot["start"], "%H:%M").time(), IST)
            >= earliest
        ]
    return available


@app.route("/")
def index():
    if not current_user.is_authenticated:
        return redirect(url_for("login"))
    return redirect(_role_home())


@app.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(_role_home())
    error = None
    if request.method == "POST":
        identity = (request.form.get("identity") or request.form.get("username") or "").strip()
        password = request.form.get("password") or ""
        with get_db() as conn:
            row = conn.execute(
                """
                SELECT * FROM users
                WHERE lower(username) = lower(?) OR lower(email) = lower(?)
                LIMIT 1
                """,
                (identity, identity),
            ).fetchone()
            instructor_ready = True
            if row and row["role"] == "instructor":
                profile = conn.execute(
                    """
                    SELECT is_active, verification_status FROM instructors
                    WHERE id = ?
                    """,
                    (row["instructor_id"],),
                ).fetchone()
                instructor_ready = bool(
                    profile
                    and profile["is_active"]
                    and profile["verification_status"] == "verified"
                )
        if (
            row
            and row["is_active"]
            and row["login_enabled"]
            and instructor_ready
            and check_password_hash(row["password_hash"], password)
        ):
            login_user(User(row), remember=False)
            session.permanent = True
            session.pop("csrf_token", None)
            csrf_token()
            next_url = _safe_next_url(request.args.get("next"))
            if row["must_change_password"]:
                flash("Create a private password before using your account.", "warning")
                return redirect(url_for("account_password"))
            return redirect(next_url or _role_home())
        error = "We could not match those sign-in details. Please try again."
    return render_template("login.html", error=error)


@app.route("/signup", methods=["GET", "POST"])
def signup():
    # Access is institution-controlled. Keeping the old URL as a clean 404
    # prevents bookmarked public-registration forms from being used.
    abort(404)


@app.route("/account/password", methods=["GET", "POST"])
@login_required
def account_password():
    error = None
    if request.method == "POST":
        current_password = request.form.get("current_password") or ""
        new_password = request.form.get("new_password") or ""
        confirmation = request.form.get("confirm_password") or ""
        with get_db() as conn:
            row = conn.execute(
                "SELECT password_hash FROM users WHERE id = ?", (current_user.id,)
            ).fetchone()
            if not row or not check_password_hash(row["password_hash"], current_password):
                error = "Your current password is not correct."
            elif len(new_password) < MIN_PASSWORD_LENGTH:
                error = f"Use at least {MIN_PASSWORD_LENGTH} characters for your new password."
            elif new_password != confirmation:
                error = "The two new passwords do not match."
            elif check_password_hash(row["password_hash"], new_password):
                error = "Choose a password you have not just been using."
            else:
                conn.execute(
                    """
                    UPDATE users SET password_hash = ?, must_change_password = 0,
                        updated_at = CURRENT_TIMESTAMP WHERE id = ?
                    """,
                    (generate_password_hash(new_password), current_user.id),
                )
                _audit(conn, "account_password_changed", details={"user_id": current_user.id})
        if not error:
            current_user.must_change_password = False
            flash("Your password has been updated.", "success")
            return redirect(_role_home())
    return render_template("account_password.html", error=error)


@app.post("/logout")
@login_required
def logout():
    logout_user()
    session.clear()
    flash("You have been signed out safely.", "success")
    return redirect(url_for("login"))


def _admin_users_context(conn, *, editing_user_id=None):
    all_users = [
        dict(row)
        for row in conn.execute(
            """
            SELECT u.*, br.name AS branch_name, i.name AS instructor_name,
                   i.specialty, i.verification_status,
                   (
                       SELECT group_concat(ai.name, ', ')
                       FROM student_instructor_assignments a
                       JOIN instructors ai ON ai.id = a.instructor_id
                       WHERE a.student_user_id = u.id AND a.is_active = 1
                   ) AS assigned_instructor_names,
                   (
                       SELECT count(*) FROM student_instructor_assignments a
                       WHERE a.student_user_id = u.id AND a.is_active = 1
                   ) AS assignment_count
            FROM users u
            LEFT JOIN branches br ON br.id = u.branch_id
            LEFT JOIN instructors i ON i.id = u.instructor_id
            ORDER BY u.is_active DESC,
                     CASE u.role WHEN 'admin' THEN 0 WHEN 'booking_agent' THEN 1 WHEN 'instructor' THEN 2 ELSE 3 END,
                     lower(COALESCE(u.full_name, u.username))
            """
        ).fetchall()
    ]
    for managed_user in all_users:
        managed_user["effective_permission_mask"] = (
            DEFAULT_ROLE_PERMISSIONS.get(managed_user["role"], 0)
            if managed_user.get("permission_mask") is None
            else int(managed_user["permission_mask"])
        )
        managed_user["effective_permissions"] = [
            permission
            for permission, bit in PERMISSION_BITS.items()
            if managed_user["effective_permission_mask"] & bit
        ]
    query = " ".join((request.args.get("q") or "").split()).lower()[:100]
    role_filter = (request.args.get("role") or "").lower()
    status_filter = (request.args.get("status") or "").lower()
    branch_filter = request.args.get("branch", "")
    account_users = (
        [user for user in all_users if user["role"] != "student"]
        if not app.config["A2Z_STUDENT_SELF_BOOKING"]
        else all_users
    )
    managed_users = account_users
    if query:
        managed_users = [
            user
            for user in managed_users
            if query
            in " ".join(
                str(user.get(field) or "").lower()
                for field in ("full_name", "username", "email", "phone")
            )
        ]
    if role_filter in MANAGED_ROLES:
        managed_users = [user for user in managed_users if user["role"] == role_filter]
    if status_filter in {"active", "inactive"}:
        expected = status_filter == "active"
        managed_users = [user for user in managed_users if bool(user["is_active"]) == expected]
    if branch_filter:
        try:
            selected_branch_id = int(branch_filter)
            managed_users = [
                user for user in managed_users if user["branch_id"] == selected_branch_id
            ]
        except ValueError:
            pass
    branches = [
        dict(row)
        for row in conn.execute(
            "SELECT id, name FROM branches WHERE is_active = 1 ORDER BY name"
        ).fetchall()
    ]
    available_instructors = [
        dict(row)
        for row in conn.execute(
            """
            SELECT i.id, i.name, i.branch_id, i.specialty,
                   i.verification_status, br.name AS branch_name
            FROM instructors i
            JOIN branches br ON br.id = i.branch_id
            WHERE i.is_active = 1 AND i.verification_status = 'verified'
            ORDER BY br.name, i.name
            """
        ).fetchall()
    ]
    assignments = [
        dict(row)
        for row in conn.execute(
            """
            SELECT a.id, a.student_user_id, a.instructor_id, a.assigned_at,
                   s.full_name AS student_name, i.name AS instructor_name
            FROM student_instructor_assignments a
            JOIN users s ON s.id = a.student_user_id
            JOIN instructors i ON i.id = a.instructor_id
            WHERE a.is_active = 1 AND s.is_active = 1 AND i.is_active = 1
              AND i.verification_status = 'verified'
            ORDER BY s.full_name, i.name
            """
        ).fetchall()
    ]
    unlinked_instructors = [
        dict(row)
        for row in conn.execute(
            """
            SELECT i.id, i.name, i.branch_id, i.specialty, i.verification_status,
                   br.name AS branch_name
            FROM instructors i
            JOIN branches br ON br.id = i.branch_id
            LEFT JOIN users u ON u.instructor_id = i.id
            WHERE u.id IS NULL AND i.is_active = 1
            ORDER BY i.verification_status, br.name, i.name
            """
        ).fetchall()
    ]
    linking_instructor = None
    try:
        linking_instructor_id = int(request.args.get("link_instructor", ""))
    except (TypeError, ValueError):
        linking_instructor_id = None
    if linking_instructor_id:
        linking_instructor = next(
            (item for item in unlinked_instructors if item["id"] == linking_instructor_id),
            None,
        )
        if linking_instructor:
            base_username = re.sub(
                r"[^a-z0-9._-]+",
                ".",
                linking_instructor["name"].strip().lower(),
            ).strip("._-") or f"instructor{linking_instructor['id']}"
            if len(base_username) < 3:
                base_username = f"staff.{base_username}"
            username = base_username[:50]
            suffix = 2
            while conn.execute(
                "SELECT 1 FROM users WHERE lower(username) = lower(?)", (username,)
            ).fetchone():
                tail = str(suffix)
                username = f"{base_username[:50-len(tail)]}{tail}"
                suffix += 1
            linking_instructor["suggested_username"] = username
    editing_user = None
    if editing_user_id is not None:
        editing_user = next(
            (user for user in managed_users if user["id"] == editing_user_id), None
        )
    return {
        "managed_users": managed_users,
        "branches": branches,
        "available_instructors": available_instructors,
        "assignments": (
            assignments if app.config["A2Z_STUDENT_SELF_BOOKING"] else []
        ),
        "unlinked_instructors": unlinked_instructors,
        "linking_instructor": linking_instructor,
        "editing_user": editing_user,
        "roles": (
            MANAGED_ROLES
            if app.config["A2Z_STUDENT_SELF_BOOKING"]
            else ("booking_agent", "instructor", "admin")
        ),
        "permission_options": PERMISSION_OPTIONS,
        "permission_bits": PERMISSION_BITS,
        "default_permission_masks": DEFAULT_ROLE_PERMISSIONS,
        "stats": {
            "total": len(account_users),
            "students": sum(
                user["role"] == "student" and user["is_active"]
                for user in account_users
            ),
            "instructors": sum(
                user["role"] == "instructor" and user["is_active"]
                for user in account_users
            ),
            "booking_agents": sum(
                user["role"] == "booking_agent" and user["is_active"]
                for user in account_users
            ),
            "admins": sum(
                user["role"] == "admin" and user["is_active"]
                for user in account_users
            ),
            "inactive": sum(not user["is_active"] for user in account_users),
            "unverified": sum(
                user["role"] == "instructor"
                and user.get("verification_status") != "verified"
                for user in account_users
            ),
        },
    }


def _render_admin_users(*, editing_user_id=None, error=None, temporary_password=None,
                        temporary_username=None, status_code=200):
    with get_db() as conn:
        context = _admin_users_context(conn, editing_user_id=editing_user_id)
    context.update(
        error=error,
        temporary_password=temporary_password,
        temporary_username=temporary_username,
    )
    return render_template("admin_users.html", **context), status_code


@app.route("/admin/users", methods=["GET", "POST"])
@role_required("admin")
def admin_users():
    if request.method == "GET":
        return _render_admin_users()

    role = (request.form.get("role") or "").strip().lower()
    generated_password = None
    try:
        if role not in MANAGED_ROLES:
            raise ValueError(
                "Choose student, Booking, instructor or administrator access."
            )
        if role == "student" and not app.config["A2Z_STUDENT_SELF_BOOKING"]:
            raise ValueError(
                "Add clients from the client database. Client records do not need sign-in details."
            )
        full_name = _validate_full_name(request.form.get("full_name"))
        username = _validate_username(request.form.get("username"))
        email = _validate_email(request.form.get("email"))
        phone = (request.form.get("phone") or "").strip()
        if role in {"student", "instructor"}:
            phone = _normalise_phone(phone)
        elif phone:
            phone = _normalise_phone(phone)
        password = request.form.get("password") or ""
        if not password:
            password = generated_password = _temporary_password()
        if len(password) < MIN_PASSWORD_LENGTH:
            raise ValueError(
                f"Temporary passwords must be at least {MIN_PASSWORD_LENGTH} characters."
            )

        with get_db() as conn:
            conn.execute("BEGIN IMMEDIATE")
            branch_id = _validate_branch(conn, request.form.get("branch_id"))
            _ensure_identity_available(conn, username, email)
            instructor_id = None
            permission_mask = _permission_mask_from_form(role)
            if role == "instructor":
                if request.form.get("verify_instructor") != "1":
                    raise ValueError(
                        "Confirm that the instructor's identity and employment details were verified."
                    )
                specialty = " ".join((request.form.get("specialty") or "").split())[:120]
                existing = conn.execute(
                    """
                    SELECT i.id,
                           (SELECT count(*) FROM users u WHERE u.instructor_id = i.id) AS linked
                    FROM instructors i
                    WHERE lower(i.name) = lower(?) AND i.branch_id = ?
                    """,
                    (full_name, branch_id),
                ).fetchone()
                if existing and existing["linked"]:
                    raise ValueError("An instructor account already exists for that person.")
                if existing:
                    instructor_id = existing["id"]
                    conn.execute(
                        """
                        UPDATE instructors SET specialty = ?, is_active = 1,
                            verification_status = 'verified', verified_at = CURRENT_TIMESTAMP,
                            verified_by = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?
                        """,
                        (specialty or None, current_user.id, instructor_id),
                    )
                else:
                    instructor_id = conn.execute(
                        """
                        INSERT INTO instructors
                            (name, branch_id, specialty, verification_status,
                             verified_at, verified_by)
                        VALUES (?, ?, ?, 'verified', CURRENT_TIMESTAMP, ?)
                        """,
                        (full_name, branch_id, specialty or None, current_user.id),
                    ).lastrowid

            cursor = conn.execute(
                """
                INSERT INTO users
                    (username, password_hash, role, instructor_id, full_name,
                     email, phone, branch_id, login_enabled,
                     must_change_password, permission_mask)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?)
                """,
                (
                    username,
                    generate_password_hash(password),
                    role,
                    instructor_id,
                    full_name,
                    email,
                    phone or None,
                    branch_id,
                    (
                        1
                        if role != "student"
                        or app.config["A2Z_STUDENT_SELF_BOOKING"]
                        else 0
                    ),
                    permission_mask,
                ),
            )
            user_id = cursor.lastrowid

            if role == "student":
                for raw_instructor_id in request.form.getlist("instructor_ids"):
                    try:
                        assigned_instructor_id = int(raw_instructor_id)
                    except (TypeError, ValueError):
                        raise ValueError("Choose valid assigned instructors.") from None
                    instructor = conn.execute(
                        """
                        SELECT id FROM instructors
                        WHERE id = ? AND branch_id = ? AND is_active = 1
                          AND verification_status = 'verified'
                        """,
                        (assigned_instructor_id, branch_id),
                    ).fetchone()
                    if not instructor:
                        raise ValueError("Assigned instructors must be verified and in the same branch.")
                    conn.execute(
                        """
                        INSERT INTO student_instructor_assignments
                            (student_user_id, instructor_id, assigned_by)
                        VALUES (?, ?, ?)
                        """,
                        (user_id, assigned_instructor_id, current_user.id),
                    )
            _audit(
                conn,
                "user_created",
                details={"target_user_id": user_id, "role": role},
            )
        flash(f"{full_name}'s {role} account is ready.", "success")
        return _render_admin_users(
            temporary_password=generated_password,
            temporary_username=username if generated_password else None,
        )
    except sqlite3.IntegrityError:
        return _render_admin_users(
            error="That username or email is already in use.", status_code=400
        )
    except (TypeError, ValueError) as exc:
        return _render_admin_users(error=str(exc), status_code=400)


@app.route("/admin/users/<int:user_id>/edit", methods=["GET", "POST"])
@role_required("admin")
def admin_user_edit(user_id):
    if request.method == "GET":
        with get_db() as conn:
            if not conn.execute("SELECT 1 FROM users WHERE id = ?", (user_id,)).fetchone():
                abort(404)
        return _render_admin_users(editing_user_id=user_id)
    try:
        with get_db() as conn:
            conn.execute("BEGIN IMMEDIATE")
            user = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
            if not user:
                abort(404)
            requested_role = (request.form.get("role") or user["role"]).strip().lower()
            permission_mask = _permission_mask_from_form(requested_role)
            scheduling_roles = {"admin", "booking_agent"}
            if user["role"] in scheduling_roles:
                if requested_role not in scheduling_roles:
                    raise ValueError(
                        "Scheduling accounts can be Administrator or Booking."
                    )
                if user["role"] == "admin" and requested_role == "booking_agent":
                    other_admin = conn.execute(
                        """
                        SELECT 1 FROM users
                        WHERE id != ? AND role = 'admin' AND is_active = 1
                          AND login_enabled = 1
                        LIMIT 1
                        """,
                        (user_id,),
                    ).fetchone()
                    if not other_admin:
                        raise ValueError(
                            "Create or activate another administrator before changing "
                            "the last administrator to Booking."
                        )
            elif requested_role != user["role"]:
                raise ValueError(
                    "Instructor and student roles cannot be changed after creation."
                )
            full_name = _validate_full_name(request.form.get("full_name"))
            username = _validate_username(request.form.get("username"))
            email = _validate_email(request.form.get("email"))
            phone = (request.form.get("phone") or "").strip()
            if user["role"] in {"student", "instructor"}:
                phone = _normalise_phone(phone)
            elif phone:
                phone = _normalise_phone(phone)
            branch_id = _validate_branch(conn, request.form.get("branch_id"))
            _ensure_identity_available(
                conn, username, email, exclude_user_id=user_id
            )
            if branch_id != user["branch_id"]:
                active_booking = conn.execute(
                    """
                    SELECT 1 FROM bookings
                    WHERE (student_user_id = ? OR instructor_id = ?)
                      AND validation_status IN ('Pending', 'Approved')
                      AND target_date >= ? LIMIT 1
                    """,
                    (user_id, user["instructor_id"] or -1, datetime.now(IST).date().isoformat()),
                ).fetchone()
                if active_booking:
                    raise ValueError("Cancel this person's future bookings before changing branch.")
            conn.execute(
                """
                UPDATE users SET username = ?, full_name = ?, email = ?, phone = ?,
                    branch_id = ?, role = ?, permission_mask = ?,
                    updated_at = CURRENT_TIMESTAMP WHERE id = ?
                """,
                (
                    username,
                    full_name,
                    email,
                    phone or None,
                    branch_id,
                    requested_role,
                    permission_mask,
                    user_id,
                ),
            )
            if user["role"] == "instructor":
                verification_status = (
                    "verified" if request.form.get("verify_instructor") == "1" else "unverified"
                )
                specialty = " ".join((request.form.get("specialty") or "").split())[:120]
                conn.execute(
                    """
                    UPDATE instructors SET name = ?, branch_id = ?, specialty = ?,
                        verification_status = ?,
                        verified_at = CASE WHEN ? = 'verified' THEN CURRENT_TIMESTAMP ELSE NULL END,
                        verified_by = CASE WHEN ? = 'verified' THEN ? ELSE NULL END,
                        updated_at = CURRENT_TIMESTAMP WHERE id = ?
                    """,
                    (
                        full_name,
                        branch_id,
                        specialty or None,
                        verification_status,
                        verification_status,
                        verification_status,
                        current_user.id,
                        user["instructor_id"],
                    ),
                )
                if verification_status == "unverified":
                    conn.execute(
                        """
                        UPDATE student_instructor_assignments
                        SET is_active = 0, ended_at = CURRENT_TIMESTAMP
                        WHERE instructor_id = ? AND is_active = 1
                        """,
                        (user["instructor_id"],),
                    )
                    affected_booking_ids = [
                        row["id"]
                        for row in conn.execute(
                            """
                            SELECT id FROM bookings
                            WHERE instructor_id = ? AND target_date >= ?
                              AND validation_status IN ('Pending', 'Approved')
                            """,
                            (
                                user["instructor_id"],
                                datetime.now(IST).date().isoformat(),
                            ),
                        ).fetchall()
                    ]
                    _cancel_active_bookings(conn, affected_booking_ids)
            if user["role"] == "instructor":
                conn.execute(
                    """
                    UPDATE student_instructor_assignments
                    SET is_active = 0, ended_at = CURRENT_TIMESTAMP
                    WHERE instructor_id = ? AND is_active = 1
                      AND student_user_id IN (
                          SELECT id FROM users WHERE branch_id != ?
                      )
                    """,
                    (user["instructor_id"], branch_id),
                )
            elif user["role"] == "student":
                conn.execute(
                    """
                    UPDATE student_instructor_assignments
                    SET is_active = 0, ended_at = CURRENT_TIMESTAMP
                    WHERE student_user_id = ? AND is_active = 1
                      AND instructor_id IN (
                          SELECT id FROM instructors WHERE branch_id != ?
                      )
                    """,
                    (user_id, branch_id),
                )
            _audit(
                conn,
                "user_updated",
                details={
                    "target_user_id": user_id,
                    "old_role": user["role"],
                    "new_role": requested_role,
                    "permission_mask": permission_mask,
                },
            )
        flash(f"{full_name}'s details have been updated.", "success")
        return redirect(url_for("admin_users"))
    except sqlite3.IntegrityError:
        return _render_admin_users(
            editing_user_id=user_id,
            error="That username, email or instructor record is already in use.",
            status_code=400,
        )
    except (TypeError, ValueError) as exc:
        return _render_admin_users(
            editing_user_id=user_id, error=str(exc), status_code=400
        )


@app.post("/admin/users/<int:user_id>/toggle")
@role_required("admin")
def admin_user_toggle(user_id):
    today = datetime.now(IST).date().isoformat()
    with get_db() as conn:
        conn.execute("BEGIN IMMEDIATE")
        user = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        if not user:
            abort(404)
        deactivating = bool(user["is_active"])
        if deactivating and user_id == current_user.id:
            flash("You cannot archive the account you are currently using.", "warning")
            return redirect(url_for("admin_users"))
        if deactivating and user["role"] == "admin":
            active_admins = conn.execute(
                "SELECT count(*) FROM users WHERE role = 'admin' AND is_active = 1"
            ).fetchone()[0]
            if active_admins <= 1:
                flash("Keep at least one active administrator account.", "warning")
                return redirect(url_for("admin_users"))
        next_active = 0 if deactivating else 1
        conn.execute(
            """
            UPDATE users SET is_active = ?,
                deactivated_at = CASE WHEN ? = 0 THEN CURRENT_TIMESTAMP ELSE NULL END,
                updated_at = CURRENT_TIMESTAMP WHERE id = ?
            """,
            (next_active, next_active, user_id),
        )
        if user["instructor_id"]:
            conn.execute(
                "UPDATE instructors SET is_active = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (next_active, user["instructor_id"]),
            )
        if deactivating:
            if user["role"] == "student":
                conn.execute(
                    """
                    UPDATE student_instructor_assignments
                    SET is_active = 0, ended_at = CURRENT_TIMESTAMP
                    WHERE student_user_id = ? AND is_active = 1
                    """,
                    (user_id,),
                )
            elif user["role"] == "instructor":
                conn.execute(
                    """
                    UPDATE student_instructor_assignments
                    SET is_active = 0, ended_at = CURRENT_TIMESTAMP
                    WHERE instructor_id = ? AND is_active = 1
                    """,
                    (user["instructor_id"],),
                )
            booking_clause = (
                "student_user_id = ?" if user["role"] == "student" else "instructor_id = ?"
            )
            booking_value = user_id if user["role"] == "student" else user["instructor_id"]
            if user["role"] in {"student", "instructor"}:
                affected_booking_ids = [
                    row["id"]
                    for row in conn.execute(
                        f"""
                        SELECT id FROM bookings
                        WHERE {booking_clause} AND target_date >= ?
                          AND validation_status IN ('Pending', 'Approved')
                        """,
                        (booking_value, today),
                    ).fetchall()
                ]
                _cancel_active_bookings(conn, affected_booking_ids)
        _audit(
            conn,
            "user_archived" if deactivating else "user_reactivated",
            details={"target_user_id": user_id},
        )
    flash(
        "Account archived; future bookings and assignments were closed."
        if deactivating
        else "Account reactivated.",
        "success",
    )
    return redirect(url_for("admin_users"))


@app.post("/admin/users/<int:user_id>/reset-password")
@role_required("admin")
def admin_user_reset_password(user_id):
    password = _temporary_password()
    with get_db() as conn:
        user = conn.execute("SELECT username FROM users WHERE id = ?", (user_id,)).fetchone()
        if not user:
            abort(404)
        conn.execute(
            """
            UPDATE users SET password_hash = ?, must_change_password = 1,
                updated_at = CURRENT_TIMESTAMP WHERE id = ?
            """,
            (generate_password_hash(password), user_id),
        )
        _audit(conn, "temporary_password_issued", details={"target_user_id": user_id})
    return _render_admin_users(
        temporary_password=password, temporary_username=user["username"]
    )


@app.post("/admin/assignments")
@role_required("admin")
def admin_assignment_add():
    try:
        student_id = int(request.form.get("student_user_id", ""))
        instructor_id = int(request.form.get("instructor_id", ""))
        with get_db() as conn:
            conn.execute("BEGIN IMMEDIATE")
            student = conn.execute(
                """
                SELECT id, branch_id FROM users
                WHERE id = ? AND role = 'student' AND is_active = 1
                """,
                (student_id,),
            ).fetchone()
            instructor = conn.execute(
                """
                SELECT id, branch_id FROM instructors
                WHERE id = ? AND is_active = 1 AND verification_status = 'verified'
                """,
                (instructor_id,),
            ).fetchone()
            if not student or not instructor or student["branch_id"] != instructor["branch_id"]:
                raise ValueError("Choose an active student and verified instructor in the same branch.")
            conn.execute(
                """
                INSERT INTO student_instructor_assignments
                    (student_user_id, instructor_id, assigned_by)
                VALUES (?, ?, ?)
                ON CONFLICT(student_user_id, instructor_id) DO UPDATE SET
                    is_active = 1, assigned_by = excluded.assigned_by,
                    assigned_at = CURRENT_TIMESTAMP, ended_at = NULL
                """,
                (student_id, instructor_id, current_user.id),
            )
            _audit(
                conn,
                "instructor_assigned",
                details={"student_user_id": student_id, "instructor_id": instructor_id},
            )
        flash("Instructor assigned to the student.", "success")
    except (TypeError, ValueError) as exc:
        flash(str(exc), "error")
    return redirect(url_for("admin_users"))


@app.post("/admin/assignments/<int:assignment_id>/remove")
@role_required("admin")
def admin_assignment_remove(assignment_id):
    today = datetime.now(IST).date().isoformat()
    with get_db() as conn:
        conn.execute("BEGIN IMMEDIATE")
        assignment = conn.execute(
            "SELECT * FROM student_instructor_assignments WHERE id = ? AND is_active = 1",
            (assignment_id,),
        ).fetchone()
        if not assignment:
            abort(404)
        upcoming = conn.execute(
            """
            SELECT 1 FROM bookings
            WHERE student_user_id = ? AND instructor_id = ? AND target_date >= ?
              AND validation_status IN ('Pending', 'Approved') LIMIT 1
            """,
            (assignment["student_user_id"], assignment["instructor_id"], today),
        ).fetchone()
        if upcoming:
            flash("Cancel or complete this pair's future bookings before removing the assignment.", "warning")
            return redirect(url_for("admin_users"))
        conn.execute(
            """
            UPDATE student_instructor_assignments
            SET is_active = 0, ended_at = CURRENT_TIMESTAMP WHERE id = ?
            """,
            (assignment_id,),
        )
        _audit(
            conn,
            "instructor_unassigned",
            details={
                "student_user_id": assignment["student_user_id"],
                "instructor_id": assignment["instructor_id"],
            },
        )
    flash("Instructor assignment removed.", "success")
    return redirect(url_for("admin_users"))


@app.get("/student/dashboard")
@role_required("student")
def student_dashboard():
    now = datetime.now(IST)
    today = now.date().isoformat()
    with get_db() as conn:
        bookings = _booking_rows(
            conn,
            "b.student_user_id = ?",
            (current_user.id,),
            "CASE WHEN b.target_date >= date('now') THEN 0 ELSE 1 END, "
            "b.target_date ASC, b.start_time ASC",
        )
        branch_row = conn.execute(
            "SELECT * FROM branches WHERE id = ?", (current_user.branch_id,)
        ).fetchone()
        stats = {
            "pending": conn.execute(
                "SELECT count(*) FROM bookings WHERE student_user_id = ? AND validation_status = 'Pending'",
                (current_user.id,),
            ).fetchone()[0],
            "upcoming": conn.execute(
                """
                SELECT count(*) FROM bookings
                WHERE student_user_id = ? AND validation_status = 'Approved' AND target_date >= ?
                """,
                (current_user.id, today),
            ).fetchone()[0],
            "completed": conn.execute(
                """
                SELECT count(*) FROM bookings
                WHERE student_user_id = ? AND validation_status = 'Completed'
                """,
                (current_user.id,),
            ).fetchone()[0],
            "attendance_due": conn.execute(
                """
                SELECT count(*) FROM bookings
                WHERE student_user_id = ? AND validation_status = 'Approved'
                  AND target_date < ?
                """,
                (current_user.id, today),
            ).fetchone()[0],
        }
    return render_template(
        "student_dashboard.html",
        bookings=bookings,
        stats=stats,
        branch=dict(branch_row) if branch_row else None,
        today=today,
        current_time=now.strftime("%H:%M"),
    )


@app.get("/student/book")
@role_required("student")
def new_booking():
    _require_student_self_booking()
    with get_db() as conn:
        machines = [
            dict(row)
            for row in conn.execute(
                """
                SELECT id, machine_code, category, location FROM machines
                WHERE branch_id = ? AND is_active = 1
                ORDER BY category, machine_code
                """,
                (current_user.branch_id,),
            ).fetchall()
        ]
        instructors = [
            dict(row)
            for row in conn.execute(
                """
                SELECT i.id, i.name, i.specialty FROM instructors i
                JOIN student_instructor_assignments a
                  ON a.instructor_id = i.id
                 AND a.student_user_id = ? AND a.is_active = 1
                WHERE i.branch_id = ? AND i.is_active = 1
                  AND i.verification_status = 'verified'
                ORDER BY i.name
                """,
                (current_user.id, current_user.branch_id),
            ).fetchall()
        ]
        services = _service_catalog(conn, current_user.branch_id)
        branch_row = conn.execute(
            "SELECT * FROM branches WHERE id = ?", (current_user.branch_id,)
        ).fetchone()
    return render_template(
        "booking.html",
        machines=machines,
        instructors=instructors,
        services=services,
        student_contact={
            "full_name": current_user.full_name,
            "email": current_user.email,
            "phone": current_user.phone,
        },
        branch=dict(branch_row) if branch_row else None,
        work_windows=WORK_WINDOWS,
        min_date=datetime.now(IST).date().isoformat(),
        max_date=(datetime.now(IST).date() + timedelta(days=90)).isoformat(),
    )


@app.get("/api/available-slots")
@role_required("student")
def api_available_slots():
    _require_student_self_booking()
    try:
        machine_id, instructor_id = _parse_resource_ids(
            request.args.get("machine_id"), request.args.get("instructor_id")
        )
        target = _validate_booking_date(request.args.get("date"))
        service_ids = _parse_service_ids(
            request.args.getlist("service_id") or request.args.get("service_ids")
        )
        with get_db() as conn:
            services = _selected_services(
                conn,
                current_user.branch_id,
                service_ids,
                instructor_id=instructor_id,
                machine_id=machine_id,
                target=target,
            )
            if services:
                try:
                    intake_payload = json.loads(request.args.get("intake") or "{}")
                except json.JSONDecodeError:
                    raise ValueError("Check the service questions and try again.") from None
                _, duration_adjustment, price_adjustment = _validate_intake(
                    conn, services, intake_payload
                )
                duration = sum(int(service["duration_minutes"]) for service in services)
                duration += duration_adjustment
                price_cents = sum(int(service["price_cents"]) for service in services)
                price_cents += price_adjustment
                buffer_before = int(services[0]["buffer_before_minutes"] or 0)
                buffer_after = int(services[-1]["buffer_after_minutes"] or 0)
            else:
                try:
                    duration = int(request.args.get("duration", "30"))
                except (TypeError, ValueError):
                    raise ValueError("Choose a valid session length.") from None
                price_cents = 0
                buffer_before = 0
                buffer_after = 0
            if duration < 30 or duration > 240 or duration % 30:
                raise ValueError("The selected services need a 30-minute to 4-hour slot.")
            slots = _available_slots(
                conn,
                current_user.branch_id,
                machine_id,
                instructor_id,
                target,
                current_user.id,
                duration,
                buffer_before,
                buffer_after,
            )
        message = None if slots else "No matching times remain for this selection."
        return jsonify(
            {
                "slots": slots,
                "available_slots": slots,
                "message": message,
                "duration_minutes": duration,
                "price_cents": price_cents,
                "currency": services[0]["currency"] if services else "INR",
            }
        )
    except ValueError as exc:
        return jsonify({"slots": [], "available_slots": [], "error": str(exc)}), 400


@app.post("/api/bookings")
@role_required("student")
def api_create_booking():
    _require_student_self_booking()
    payload = request.get_json(silent=True) if request.is_json else request.form.to_dict()
    payload = payload or {}
    try:
        machine_id, instructor_id = _parse_resource_ids(
            payload.get("machine_id"), payload.get("instructor_id")
        )
        target = _validate_booking_date(payload.get("target_date") or payload.get("date"))
        raw_service_ids = (
            payload.get("service_ids")
            if request.is_json
            else request.form.getlist("service_id") or payload.get("service_ids")
        )
        service_ids = _parse_service_ids(raw_service_ids)
        start_time = str(payload.get("start_time") or "")
        end_time = str(payload.get("end_time") or "")
        notes = " ".join(
            str(payload.get("notes") or payload.get("student_notes") or "").split()
        )
        if len(notes) > 500:
            raise ValueError("Keep your note under 500 characters.")

        with get_db() as conn:
            conn.execute("BEGIN IMMEDIATE")
            services = _selected_services(
                conn,
                current_user.branch_id,
                service_ids,
                instructor_id=instructor_id,
                machine_id=machine_id,
                target=target,
            )
            raw_intake = payload.get("intake") or {}
            if isinstance(raw_intake, str):
                try:
                    raw_intake = json.loads(raw_intake)
                except json.JSONDecodeError:
                    raise ValueError("Check the service questions and try again.") from None
            if not request.is_json:
                raw_intake = {
                    key.removeprefix("intake_"): value
                    for key, value in request.form.items()
                    if key.startswith("intake_")
                }
                raw_intake.update(
                    {
                        key.removeprefix("intake_file_"): upload.filename
                        for key, upload in request.files.items()
                        if key.startswith("intake_file_") and upload.filename
                    }
                )
            intake_values, duration_adjustment, price_adjustment = _validate_intake(
                conn, services, raw_intake
            )
            if services:
                duration = sum(int(service["duration_minutes"]) for service in services)
                duration += duration_adjustment
                price_cents = sum(int(service["price_cents"]) for service in services)
                price_cents += price_adjustment
                currency = services[0]["currency"]
                buffer_before = int(services[0]["buffer_before_minutes"] or 0)
                buffer_after = int(services[-1]["buffer_after_minutes"] or 0)
                next_status = (
                    "Pending"
                    if any(service["requires_approval"] for service in services)
                    else "Approved"
                )
            else:
                try:
                    duration = int(payload.get("duration", 30))
                except (TypeError, ValueError):
                    raise ValueError("Choose a valid session length.") from None
                price_cents = 0
                currency = "INR"
                buffer_before = 0
                buffer_after = 0
                next_status = "Pending"
            if duration < 30 or duration > 240 or duration % 30:
                raise ValueError("The selected services need a 30-minute to 4-hour slot.")
            try:
                start_dt = datetime.strptime(start_time, "%H:%M")
                end_dt = datetime.strptime(end_time, "%H:%M")
            except ValueError:
                raise ValueError("Choose one of the available training times.") from None
            if int((end_dt - start_dt).total_seconds() // 60) != duration:
                raise ValueError("The selected time does not match the services.")
            slots = _available_slots(
                conn,
                current_user.branch_id,
                machine_id,
                instructor_id,
                target,
                current_user.id,
                duration,
                buffer_before,
                buffer_after,
            )
            if {"start": start_time, "end": end_time} not in slots:
                raise ValueError("That slot is no longer available. Choose another time.")
            service_name = (
                ", ".join(service["name"] for service in services) if services else None
            )
            cursor = conn.execute(
                """
                INSERT INTO bookings
                    (student_name, mobile_number, student_user_id, machine_id,
                     instructor_id, branch_id, target_date, start_time,
                     end_time, validation_status, notes, service_id,
                     service_name, service_price_cents, currency,
                     buffer_before_minutes, buffer_after_minutes, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                        CURRENT_TIMESTAMP)
                """,
                (
                    current_user.full_name,
                    current_user.phone,
                    current_user.id,
                    machine_id,
                    instructor_id,
                    current_user.branch_id,
                    target.isoformat(),
                    start_time,
                    end_time,
                    next_status,
                    notes or None,
                    services[0]["id"] if services else None,
                    service_name,
                    price_cents,
                    currency,
                    buffer_before,
                    buffer_after,
                ),
            )
            booking_id = cursor.lastrowid
            for position, service in enumerate(services):
                conn.execute(
                    """
                    INSERT INTO booking_services
                        (booking_id, service_id, service_name, duration_minutes,
                         price_cents, currency, sort_order)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        booking_id,
                        service["id"],
                        service["name"],
                        service["duration_minutes"],
                        service["price_cents"],
                        service["currency"],
                        position,
                    ),
                )
            for value in intake_values:
                conn.execute(
                    """
                    INSERT INTO booking_intake_values
                        (booking_id, field_id, field_key, field_label, value_text)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        booking_id,
                        value["field_id"],
                        value["field_key"],
                        value["field_label"],
                        value["value_text"],
                    ),
                )
            _save_intake_files(conn, booking_id)
            _audit(
                conn,
                "booking_requested"
                if next_status == "Pending"
                else "booking_confirmed",
                booking_id,
                {
                    "target_date": target.isoformat(),
                    "start_time": start_time,
                    "service_ids": service_ids,
                },
            )
            _queue_booking_notifications(
                conn,
                booking_id,
                "booking_requested"
                if next_status == "Pending"
                else "appointment_approved",
            )
        confirmation_message = (
            "Appointment confirmed and added to your schedule."
            if next_status == "Approved"
            else "Request sent to your instructor for approval."
        )
        return jsonify(
            {
                "success": True,
                "booking_id": booking_id,
                "status": next_status,
                "message": confirmation_message,
                "redirect": url_for("student_dashboard"),
            }
        ), 201
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except sqlite3.IntegrityError:
        return jsonify({"error": "That slot was just taken. Please choose another time."}), 409


@app.post("/bookings/<int:booking_id>/cancel")
@login_required
def cancel_booking(booking_id):
    now = datetime.now(IST)
    today = now.date().isoformat()
    with get_db() as conn:
        conn.execute("BEGIN IMMEDIATE")
        booking = conn.execute("SELECT * FROM bookings WHERE id = ?", (booking_id,)).fetchone()
        if not booking:
            abort(404)
        student_owner = (
            current_user.role == "student"
            and app.config["A2Z_STUDENT_SELF_BOOKING"]
            and booking["student_user_id"] == current_user.id
        )
        instructor_owner = (
            current_user.role == "instructor"
            and booking["instructor_id"] == current_user.instructor_id
        )
        if current_user.role not in {"admin", "instructor", "student"}:
            abort(403)
        if current_user.role == "instructor" and not instructor_owner:
            abort(404)
        if current_user.role == "student" and not student_owner:
            abort(403)
        if booking["validation_status"] not in ACTIVE_BOOKING_STATUSES:
            flash("This booking is already closed and cannot be cancelled.", "warning")
        elif current_user.role == "student" and (
            booking["target_date"] < today
            or (
                booking["target_date"] == today
                and booking["start_time"] <= now.strftime("%H:%M")
            )
        ):
            flash("A session cannot be cancelled after its scheduled start.", "warning")
        else:
            conn.execute(
                """
                UPDATE bookings SET validation_status = 'Cancelled',
                    cancelled_at = CURRENT_TIMESTAMP,
                    calendar_revision = calendar_revision + 1,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (booking_id,),
            )
            _audit(conn, "booking_cancelled", booking_id)
            _queue_booking_notifications(conn, booking_id, "appointment_cancelled")
            flash("The booking has been cancelled.", "success")
    return redirect(_role_home())


def _calendar_instructors(conn):
    if current_user.role == "instructor" and not current_user.has_permission(
        "everyone_schedule"
    ):
        params = (current_user.instructor_id,)
        where = "i.id = ?"
    else:
        params = ()
        where = "i.is_active = 1 AND i.verification_status = 'verified'"
    return [
        dict(row)
        for row in conn.execute(
            f"""
            SELECT i.id, i.name, i.branch_id, i.specialty, br.name AS branch_name
            FROM instructors i
            JOIN branches br ON br.id = i.branch_id
            WHERE {where}
            -- Staff order is operational and matches the imported Smart
            -- Scheduling calendar instead of alphabetising the columns.
            ORDER BY br.name, i.id
            """,
            params,
        ).fetchall()
    ]


def _calendar_event(row):
    can_view_contacts = current_user.has_permission("contact_details")
    can_view_notes = current_user.has_permission("client_notes")
    phone = row["mobile_number"] or ""
    email = row["student_email"] or ""
    if not can_view_contacts:
        phone = ("•" * max(0, len(phone) - 3)) + phone[-3:] if phone else ""
        if email and "@" in email:
            local, domain = email.split("@", 1)
            email = (local[:1] + "•••@" + domain) if local else "•••@" + domain
    return {
        "type": "appointment",
        "id": row["id"],
        "title": row["service_name"] or row["machine_category"],
        "client_id": row["student_user_id"],
        "student_user_id": row["student_user_id"],
        "student_name": row["student_name"],
        "student_phone": phone,
        "student_email": email,
        "service_name": row["service_name"] or row["machine_category"],
        "service_price_cents": int(row["service_price_cents"] or 0),
        "currency": row["currency"] or "INR",
        "service_id": row["service_id"],
        "service_ids": row.get("service_ids") or (
            [row["service_id"]] if row["service_id"] else []
        ),
        "service_color": row["service_color"] or "#C8141B",
        "machine_id": row["machine_id"],
        "machine_name": row["machine_code"],
        "instructor_id": row["instructor_id"],
        "instructor_name": row["instructor_name"],
        "branch_id": row["branch_id"],
        "branch_name": row["branch_name"],
        "date": row["target_date"],
        "start_time": row["start_time"],
        "end_time": row["end_time"],
        "status": row["validation_status"],
        "notes": (row["notes"] or "") if can_view_notes else "",
        "revision": row["calendar_revision"],
        "buffer_before_minutes": row["buffer_before_minutes"],
        "buffer_after_minutes": row["buffer_after_minutes"],
        "allow_double_booking": bool(row["allow_double_booking"]),
        "series_id": row.get("series_id"),
        "repeat_rule": row.get("repeat_rule") or "none",
        "series_position": row.get("series_position") or 1,
        "series_count": row.get("series_count") or 1,
        "can_edit": (
            current_user.has_permission("write_access")
            and row["validation_status"] != "Cancelled"
        ),
    }


def _calendar_busy_event(row):
    reason = " ".join(str(row["reason"] or "Busy time").split())
    break_kind = {
        "breakfast": "breakfast",
        "lunch": "lunch",
        "tea break": "tea",
    }.get(reason.lower(), "busy")
    return {
        "type": "busy",
        "id": row["id"],
        "title": reason,
        "busy_kind": break_kind,
        "notes": row["notes"] or "",
        "instructor_id": row["instructor_id"],
        "instructor_name": row["instructor_name"],
        "branch_id": row["branch_id"],
        "date": row["target_date"],
        "start_time": row["start_time"],
        "end_time": row["end_time"],
        "status": "Break" if break_kind != "busy" else "Busy",
        "revision": row["calendar_revision"],
        "buffer_before_minutes": 0,
        "buffer_after_minutes": 0,
        "service_color": "#667085",
        "series_id": row.get("series_id"),
        "repeat_rule": row.get("repeat_rule") or "none",
        "series_position": row.get("series_position") or 1,
        "series_count": row.get("series_count") or 1,
        "can_edit": current_user.role == "admin",
    }


def _default_lunch_source(instructor_id, target):
    return f"{DEFAULT_LUNCH_SOURCE_PREFIX}:{instructor_id}:{target.isoformat()}"


def _ensure_default_lunch_breaks(
    conn, start, end, *, instructor_id=None, branch_id=None
):
    """Create editable 1–2 pm lunch breaks when a calendar date is first viewed."""
    instructor_clauses = [
        "is_active = 1",
        "verification_status = 'verified'",
    ]
    instructor_params = []
    if instructor_id:
        instructor_clauses.append("id = ?")
        instructor_params.append(instructor_id)
    if branch_id:
        instructor_clauses.append("branch_id = ?")
        instructor_params.append(branch_id)
    instructor_ids = [
        row["id"]
        for row in conn.execute(
            f"SELECT id FROM instructors WHERE {' AND '.join(instructor_clauses)}",
            instructor_params,
        ).fetchall()
    ]
    if not instructor_ids:
        return

    lunch_start_minutes = _time_to_minutes(DEFAULT_LUNCH_START)
    lunch_end_minutes = _time_to_minutes(DEFAULT_LUNCH_END)
    active_placeholders = ",".join("?" for _ in ACTIVE_BOOKING_STATUSES)
    target = start
    while target <= end:
        target_text = target.isoformat()
        for current_instructor_id in instructor_ids:
            source_reference = _default_lunch_source(current_instructor_id, target)
            if conn.execute(
                """
                SELECT 1 FROM default_lunch_exceptions
                WHERE instructor_id = ? AND target_date = ?
                """,
                (current_instructor_id, target_text),
            ).fetchone():
                continue
            if conn.execute(
                """
                SELECT 1 FROM instructor_time_off
                WHERE source_reference = ?
                   OR (instructor_id = ? AND target_date = ?
                       AND (lower(trim(reason)) = 'lunch'
                            OR (start_time < ? AND end_time > ?)))
                LIMIT 1
                """,
                (
                    source_reference,
                    current_instructor_id,
                    target_text,
                    DEFAULT_LUNCH_END,
                    DEFAULT_LUNCH_START,
                ),
            ).fetchone():
                continue
            if conn.execute(
                f"""
                SELECT 1 FROM bookings
                WHERE instructor_id = ? AND target_date = ?
                  AND validation_status IN ({active_placeholders})
                  AND start_time < ? AND end_time > ?
                LIMIT 1
                """,
                (
                    current_instructor_id,
                    target_text,
                    *ACTIVE_BOOKING_STATUSES,
                    _minutes_to_time(lunch_end_minutes),
                    _minutes_to_time(lunch_start_minutes),
                ),
            ).fetchone():
                continue
            conn.execute(
                """
                INSERT OR IGNORE INTO instructor_time_off
                    (instructor_id, target_date, start_time, end_time, reason,
                     notes, calendar_revision, source_reference, updated_at)
                VALUES (?, ?, ?, ?, 'Lunch',
                        'Default lunch break; administrators can edit this slot.',
                        1, ?, CURRENT_TIMESTAMP)
                """,
                (
                    current_instructor_id,
                    target_text,
                    DEFAULT_LUNCH_START,
                    DEFAULT_LUNCH_END,
                    source_reference,
                ),
            )
        target += timedelta(days=1)


def _calendar_slot_event(row):
    machine_name = (row["machine_code"] or row["machine_category"] or "Slot").replace("-", " ")
    return {
        "type": "slot",
        "id": row["id"],
        "title": f"SLOT - {machine_name.upper()}",
        "notes": row["notes"] or "",
        "machine_id": row["machine_id"],
        "machine_name": machine_name,
        "machine_category": row.get("machine_category") or "",
        "instructor_id": row["instructor_id"],
        "instructor_name": row["instructor_name"],
        "branch_id": row["branch_id"],
        "date": row["target_date"],
        "start_time": row["start_time"],
        "end_time": row["end_time"],
        "status": "Booking slot",
        "revision": row["calendar_revision"],
        "buffer_before_minutes": 0,
        "buffer_after_minutes": 0,
        "service_color": "#79c5df",
        "series_id": row.get("series_id"),
        "repeat_rule": row.get("repeat_rule") or "none",
        "series_position": row.get("series_position") or 1,
        "series_count": row.get("series_count") or 1,
        "can_edit": current_user.role == "admin",
    }


@app.get("/calendar")
@role_required("booking_agent", "instructor", "admin")
def calendar_view():
    requested_date = request.args.get("date", "")
    try:
        calendar_date = date.fromisoformat(requested_date) if requested_date else datetime.now(IST).date()
    except ValueError:
        calendar_date = datetime.now(IST).date()
    try:
        requested_client_id = int(request.args.get("client", ""))
    except (TypeError, ValueError):
        requested_client_id = None
    with get_db() as conn:
        instructors = _calendar_instructors(conn)
        if current_user.role == "instructor" and not current_user.has_permission(
            "everyone_schedule"
        ):
            branch_ids = [current_user.branch_id]
        else:
            branch_ids = sorted({item["branch_id"] for item in instructors})
        # Client lookup is type-ahead. Loading tens of thousands of clients as
        # <option> elements made restored Smart Scheduling databases slow and
        # memory-heavy; only a deep-linked client needs to be preloaded.
        students = []
        if requested_client_id:
            params = [requested_client_id]
            branch_clause = ""
            if current_user.role == "instructor":
                branch_clause = " AND branch_id = ?"
                params.append(current_user.branch_id)
            students = [
                dict(row)
                for row in conn.execute(
                    f"""
                    SELECT id, full_name, branch_id FROM users
                    WHERE id = ? AND role = 'student' AND is_active = 1
                    {branch_clause}
                    """,
                    params,
                ).fetchall()
            ]
        if branch_ids:
            placeholders = ",".join("?" for _ in branch_ids)
            machines = [
                dict(row)
                for row in conn.execute(
                    f"""
                    SELECT id, machine_code, category, branch_id FROM machines
                    WHERE is_active = 1 AND branch_id IN ({placeholders})
                    ORDER BY category, machine_code
                    """,
                    branch_ids,
                ).fetchall()
            ]
            services = []
            for branch_id in branch_ids:
                services.extend(_service_catalog(conn, branch_id))
        else:
            machines = []
            services = []
    selected_client_id = (
        requested_client_id
        if requested_client_id
        and any(client["id"] == requested_client_id for client in students)
        else None
    )
    selected_instructor = (
        current_user.instructor_id
        if current_user.role == "instructor"
        and not current_user.has_permission("everyone_schedule")
        else (instructors[0]["id"] if len(instructors) == 1 else None)
    )
    return render_template(
        "calendar.html",
        calendar_date=calendar_date.isoformat(),
        instructors=instructors,
        students=students,
        machines=machines,
        services=services,
        selected_instructor=selected_instructor,
        selected_client_id=selected_client_id,
    )


@app.get("/api/calendar/events")
@role_required("booking_agent", "instructor", "admin")
def api_calendar_events():
    try:
        start = date.fromisoformat(request.args.get("start", ""))
        end = date.fromisoformat(request.args.get("end", ""))
    except ValueError:
        return jsonify({"error": "Choose a valid calendar range."}), 400
    if end < start or (end - start).days > 35:
        return jsonify({"error": "Calendar ranges can cover up to 36 days."}), 400
    clauses = ["b.target_date BETWEEN ? AND ?"]
    params = [start.isoformat(), end.isoformat()]
    selected_instructor_id = None
    selected_branch_id = None
    if current_user.role == "instructor" and not current_user.has_permission(
        "everyone_schedule"
    ):
        selected_instructor_id = current_user.instructor_id
        clauses.append("b.instructor_id = ?")
        params.append(selected_instructor_id)
    else:
        instructor_value = request.args.get("instructor_id", "")
        branch_value = request.args.get("branch_id", "")
        if instructor_value:
            try:
                selected_instructor_id = int(instructor_value)
                clauses.append("b.instructor_id = ?")
                params.append(selected_instructor_id)
            except ValueError:
                return jsonify({"error": "Choose a valid instructor."}), 400
        if branch_value:
            try:
                selected_branch_id = int(branch_value)
                clauses.append("b.branch_id = ?")
                params.append(selected_branch_id)
            except ValueError:
                return jsonify({"error": "Choose a valid branch."}), 400
    status_lookup = {
        "pending": "Pending",
        "approved": "Approved",
        "rejected": "Rejected",
        "cancelled": "Cancelled",
        "completed": "Completed",
        "no-show": "No-show",
        "no-action": "No Action",
    }
    selected_status = status_lookup.get(
        (request.args.get("status") or "").strip().lower(), ""
    )
    valid_statuses = {*ACTIVE_BOOKING_STATUSES, *FINAL_BOOKING_STATUSES}
    if request.args.get("status") and selected_status not in valid_statuses:
        return jsonify({"error": "Choose a valid appointment status."}), 400
    if selected_status:
        clauses.append("b.validation_status = ?")
        params.append(selected_status)
    with get_db() as conn:
        _ensure_default_lunch_breaks(
            conn,
            start,
            end,
            instructor_id=selected_instructor_id,
            branch_id=selected_branch_id,
        )
        rows = _booking_rows(
            conn,
            " AND ".join(clauses),
            params,
            "b.target_date, b.start_time, i.name",
        )
        booking_ids = [row["id"] for row in rows]
        service_map = {booking_id: [] for booking_id in booking_ids}
        if booking_ids:
            placeholders = ",".join("?" for _ in booking_ids)
            for service_row in conn.execute(
                f"""
                SELECT booking_id, service_id
                FROM booking_services
                WHERE booking_id IN ({placeholders}) AND service_id IS NOT NULL
                ORDER BY booking_id, sort_order, id
                """,
                booking_ids,
            ).fetchall():
                service_map[service_row["booking_id"]].append(service_row["service_id"])
        for row in rows:
            row["service_ids"] = service_map.get(row["id"], [])

        busy_clauses = ["t.target_date BETWEEN ? AND ?"]
        busy_params = [start.isoformat(), end.isoformat()]
        if selected_instructor_id:
            busy_clauses.append("t.instructor_id = ?")
            busy_params.append(selected_instructor_id)
        if selected_branch_id:
            busy_clauses.append("i.branch_id = ?")
            busy_params.append(selected_branch_id)
        busy_rows = [
            dict(row)
            for row in conn.execute(
                f"""
                SELECT t.*, i.name AS instructor_name, i.branch_id
                FROM instructor_time_off t
                JOIN instructors i ON i.id = t.instructor_id
                WHERE {" AND ".join(busy_clauses)}
                ORDER BY t.target_date, t.start_time, i.name
                """,
                busy_params,
            ).fetchall()
        ]
        slot_clauses = ["s.target_date BETWEEN ? AND ?"]
        slot_params = [start.isoformat(), end.isoformat()]
        if selected_instructor_id:
            slot_clauses.append("s.instructor_id = ?")
            slot_params.append(selected_instructor_id)
        if selected_branch_id:
            slot_clauses.append("s.branch_id = ?")
            slot_params.append(selected_branch_id)
        slot_rows = [
            dict(row)
            for row in conn.execute(
                f"""
                SELECT s.*, i.name AS instructor_name,
                       m.machine_code, m.category AS machine_category
                FROM booking_slots s
                JOIN instructors i ON i.id = s.instructor_id
                JOIN machines m ON m.id = s.machine_id
                WHERE {" AND ".join(slot_clauses)}
                ORDER BY s.target_date, s.start_time, i.name
                """,
                slot_params,
            ).fetchall()
        ]
    events = [_calendar_event(row) for row in rows]
    events.extend(_calendar_busy_event(row) for row in busy_rows)
    events.extend(_calendar_slot_event(row) for row in slot_rows)
    events.sort(key=lambda item: (item["date"], item["start_time"], str(item["id"])))
    return jsonify({"events": events})


def _staff_booking_resources(conn, student_id, instructor_id, machine_id):
    row = conn.execute(
        """
        SELECT s.id AS student_id, s.full_name, s.phone, s.branch_id,
               i.id AS instructor_id, i.name AS instructor_name,
               m.id AS machine_id
        FROM users s
        JOIN instructors i ON i.id = ?
        JOIN machines m ON m.id = ?
        WHERE s.id = ? AND s.role = 'student' AND s.is_active = 1
          AND i.is_active = 1 AND i.verification_status = 'verified'
          AND m.is_active = 1
          AND s.branch_id = i.branch_id AND i.branch_id = m.branch_id
        """,
        (instructor_id, machine_id, student_id),
    ).fetchone()
    if not row:
        raise ValueError(
            "Choose an active client, instructor, and equipment from the same branch."
        )
    if current_user.role == "instructor" and instructor_id != current_user.instructor_id:
        abort(403)
    return row


def _busy_time_range(start_value, end_value):
    start_time = str(start_value or "")
    end_time = str(end_value or "")
    start_minutes = _time_to_minutes(start_time)
    end_minutes = _time_to_minutes(end_time)
    if start_minutes % 5 or end_minutes % 5:
        raise ValueError("Busy time must use 5-minute increments.")
    if start_minutes >= end_minutes:
        raise ValueError("The finish time must be later than the start time.")
    if end_minutes - start_minutes > 12 * 60:
        raise ValueError("A busy period cannot be longer than 12 hours.")
    return start_time, end_time, start_minutes, end_minutes


def _validate_staff_day_range(start_minutes, end_minutes, item_name="Booking"):
    if start_minutes < STAFF_DAY_START_MINUTES or end_minutes > STAFF_DAY_END_MINUTES:
        raise ValueError(f"{item_name} must be between 6:00 am and 6:30 pm.")
    if start_minutes >= STAFF_DAY_END_MINUTES:
        raise ValueError(f"{item_name} must start before 6:30 pm.")


def _assert_active_appointment_not_past(target, start_minutes, status, *, action):
    """Prevent staff APIs and drag/drop from placing active work in elapsed time."""
    if status not in ACTIVE_BOOKING_STATUSES:
        return
    now = datetime.now(IST)
    if target < now.date() or (
        target == now.date()
        and start_minutes < (now.hour * 60 + now.minute)
    ):
        past_action = "created in" if action == "created" else "moved into"
        raise ValueError(
            f"Active appointments cannot be {past_action} the past."
        )


def _assert_appointment_outside_breaks(
    conn, instructor_id, target, start_minutes, end_minutes
):
    """Breaks and recorded busy time are absolute, even for double bookings."""
    busy = conn.execute(
        """
        SELECT reason, start_time, end_time
        FROM instructor_time_off
        WHERE instructor_id = ? AND target_date = ?
          AND start_time < ? AND end_time > ?
        ORDER BY start_time
        LIMIT 1
        """,
        (
            instructor_id,
            target.isoformat(),
            _minutes_to_time(end_minutes),
            _minutes_to_time(start_minutes),
        ),
    ).fetchone()
    if busy:
        label = " ".join(str(busy["reason"] or "Staff break").split())
        raise AppointmentConflictError(
            f"Appointments cannot overlap {label} "
            f"({busy['start_time']}–{busy['end_time']})."
        )


def _assert_busy_time_available(
    conn, instructor_id, target, start_minutes, end_minutes, *, exclude_id=None
):
    active_placeholders = ",".join("?" for _ in ACTIVE_BOOKING_STATUSES)
    bookings = conn.execute(
        f"""
        SELECT start_time, end_time, buffer_before_minutes, buffer_after_minutes
        FROM bookings
        WHERE instructor_id = ? AND target_date = ?
          AND validation_status IN ({active_placeholders})
        """,
        (instructor_id, target.isoformat(), *ACTIVE_BOOKING_STATUSES),
    ).fetchall()
    for booking in bookings:
        occupied_start = _time_to_minutes(booking["start_time"]) - int(
            booking["buffer_before_minutes"] or 0
        )
        occupied_end = _time_to_minutes(booking["end_time"]) + int(
            booking["buffer_after_minutes"] or 0
        )
        if start_minutes < occupied_end and end_minutes > occupied_start:
            raise AppointmentConflictError(
                "That busy time overlaps an existing appointment or its private padding."
            )
    params = [instructor_id, target.isoformat()]
    exclude_clause = ""
    if exclude_id is not None:
        exclude_clause = " AND id != ?"
        params.append(exclude_id)
    existing = conn.execute(
        f"""
        SELECT 1 FROM instructor_time_off
        WHERE instructor_id = ? AND target_date = ?
          AND start_time < ? AND end_time > ? {exclude_clause}
        LIMIT 1
        """,
        (*params[:2], _minutes_to_time(end_minutes), _minutes_to_time(start_minutes), *params[2:]),
    ).fetchone()
    if existing:
        raise AppointmentConflictError("That busy time overlaps another busy period.")


@app.post("/api/calendar/busy-times")
@role_required("admin")
def api_calendar_create_busy_time():
    payload = request.get_json(silent=True) or {}
    try:
        instructor_id = int(payload.get("instructor_id"))
        if current_user.role == "instructor":
            if instructor_id != current_user.instructor_id:
                abort(403)
        target = _validate_booking_date(
            payload.get("target_date"), enforce_online_window=False
        )
        if target < datetime.now(IST).date():
            raise ValueError("Busy time cannot be added in the past.")
        start_time, end_time, start_minutes, end_minutes = _busy_time_range(
            payload.get("start_time"), payload.get("end_time")
        )
        break_type = str(payload.get("break_type") or "busy").strip().lower()
        break_titles = {
            "breakfast": "Breakfast",
            "lunch": "Lunch",
            "tea": "Tea Break",
        }
        if break_type not in {"busy", *break_titles}:
            raise ValueError("Choose Breakfast, Lunch, Tea Break, or Busy time.")
        title = (
            break_titles.get(break_type)
            or " ".join(str(payload.get("title") or "").split())[:120]
            or "Busy time"
        )
        notes = str(payload.get("notes") or "").strip()[:500]
        dates, repeat_rule = _repeat_dates(
            target, payload.get("repeat"), payload.get("repeat_count")
        )
        series_id = secrets.token_urlsafe(12) if len(dates) > 1 else None
        with get_db() as conn:
            conn.execute("BEGIN IMMEDIATE")
            instructor = conn.execute(
                """
                SELECT id, name, branch_id FROM instructors
                WHERE id = ? AND is_active = 1
                  AND verification_status = 'verified'
                """,
                (instructor_id,),
            ).fetchone()
            if not instructor:
                raise ValueError("Choose an active, verified instructor.")
            if (
                current_user.role == "instructor"
                and instructor["branch_id"] != current_user.branch_id
            ):
                abort(403)
            created = []
            for position, occurrence_date in enumerate(dates, start=1):
                _assert_busy_time_available(
                    conn,
                    instructor_id,
                    occurrence_date,
                    start_minutes,
                    end_minutes,
                )
                time_off_id = conn.execute(
                    """
                    INSERT INTO instructor_time_off
                        (instructor_id, target_date, start_time, end_time,
                         reason, notes, series_id, repeat_rule, series_position,
                         series_count, calendar_revision, created_by, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?,
                            CURRENT_TIMESTAMP)
                    """,
                    (
                        instructor_id,
                        occurrence_date.isoformat(),
                        start_time,
                        end_time,
                        title,
                        notes or None,
                        series_id,
                        repeat_rule,
                        position,
                        len(dates),
                        current_user.id,
                    ),
                ).lastrowid
                row = conn.execute(
                    """
                    SELECT t.*, i.name AS instructor_name, i.branch_id
                    FROM instructor_time_off t
                    JOIN instructors i ON i.id = t.instructor_id
                    WHERE t.id = ?
                    """,
                    (time_off_id,),
                ).fetchone()
                created.append(_calendar_busy_event(dict(row)))
            _audit(
                conn,
                "busy_time_created",
                details={
                    "instructor_id": instructor_id,
                    "start_date": target.isoformat(),
                    "repeat_rule": repeat_rule,
                    "created_count": len(created),
                },
            )
        return jsonify(
            {
                "success": True,
                "event": created[0],
                "events": created,
                "created_count": len(created),
            }
        ), 201
    except AppointmentConflictError as exc:
        return jsonify({"error": str(exc)}), 409
    except (TypeError, ValueError) as exc:
        return jsonify({"error": str(exc)}), 400


@app.patch("/api/calendar/busy-times/<int:time_off_id>")
@role_required("admin")
def api_calendar_update_busy_time(time_off_id):
    payload = request.get_json(silent=True) or {}
    try:
        revision = int(payload.get("revision"))
        with get_db() as conn:
            conn.execute("BEGIN IMMEDIATE")
            existing = conn.execute(
                "SELECT * FROM instructor_time_off WHERE id = ?",
                (time_off_id,),
            ).fetchone()
            if not existing:
                abort(404)
            if (
                current_user.role == "instructor"
                and existing["instructor_id"] != current_user.instructor_id
            ):
                abort(404)
            if revision != existing["calendar_revision"]:
                return jsonify(
                    {
                        "error": "This busy time changed in another window. The calendar has been refreshed."
                    }
                ), 409

            instructor_id = int(
                payload.get("instructor_id") or existing["instructor_id"]
            )
            if (
                current_user.role == "instructor"
                and instructor_id != current_user.instructor_id
            ):
                abort(403)
            target = _validate_booking_date(
                payload.get("target_date") or existing["target_date"],
                enforce_online_window=False,
            )
            if (
                target < datetime.now(IST).date()
                and target.isoformat() != existing["target_date"]
            ):
                raise ValueError("Busy time cannot be moved into the past.")
            start_time, end_time, start_minutes, end_minutes = _busy_time_range(
                payload.get("start_time") or existing["start_time"],
                payload.get("end_time") or existing["end_time"],
            )
            break_type = str(payload.get("break_type") or "busy").strip().lower()
            break_titles = {
                "breakfast": "Breakfast",
                "lunch": "Lunch",
                "tea": "Tea Break",
            }
            if break_type not in {"busy", *break_titles}:
                raise ValueError("Choose Breakfast, Lunch, Tea Break, or Busy time.")
            title_source = payload.get("title") if "title" in payload else existing["reason"]
            title = (
                break_titles.get(break_type)
                or " ".join(str(title_source or "").split())[:120]
                or "Busy time"
            )
            notes = (
                str(payload.get("notes") or "").strip()[:500]
                if "notes" in payload
                else existing["notes"]
            )
            instructor = conn.execute(
                """
                SELECT id, name, branch_id FROM instructors
                WHERE id = ? AND is_active = 1
                  AND verification_status = 'verified'
                """,
                (instructor_id,),
            ).fetchone()
            if not instructor:
                raise ValueError("Choose an active, verified instructor.")
            if (
                current_user.role == "instructor"
                and instructor["branch_id"] != current_user.branch_id
            ):
                abort(403)
            _assert_busy_time_available(
                conn,
                instructor_id,
                target,
                start_minutes,
                end_minutes,
                exclude_id=time_off_id,
            )
            cursor = conn.execute(
                """
                UPDATE instructor_time_off
                SET instructor_id = ?, target_date = ?, start_time = ?,
                    end_time = ?, reason = ?, notes = ?,
                    calendar_revision = calendar_revision + 1,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ? AND calendar_revision = ?
                """,
                (
                    instructor_id,
                    target.isoformat(),
                    start_time,
                    end_time,
                    title,
                    notes or None,
                    time_off_id,
                    revision,
                ),
            )
            if not cursor.rowcount:
                return jsonify(
                    {
                        "error": "This busy time changed in another window. The calendar has been refreshed."
                    }
                ), 409
            _audit(
                conn,
                "busy_time_updated",
                details={
                    "time_off_id": time_off_id,
                    "instructor_id": instructor_id,
                    "target_date": target.isoformat(),
                },
            )
            row = conn.execute(
                """
                SELECT t.*, i.name AS instructor_name, i.branch_id
                FROM instructor_time_off t
                JOIN instructors i ON i.id = t.instructor_id
                WHERE t.id = ?
                """,
                (time_off_id,),
            ).fetchone()
        return jsonify(
            {"success": True, "event": _calendar_busy_event(dict(row))}
        )
    except AppointmentConflictError as exc:
        return jsonify({"error": str(exc)}), 409
    except (TypeError, ValueError) as exc:
        return jsonify({"error": str(exc)}), 400


@app.delete("/api/calendar/busy-times/<int:time_off_id>")
@role_required("admin")
def api_calendar_delete_busy_time(time_off_id):
    with get_db() as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            "SELECT * FROM instructor_time_off WHERE id = ?", (time_off_id,)
        ).fetchone()
        if not row:
            abort(404)
        if (
            current_user.role == "instructor"
            and row["instructor_id"] != current_user.instructor_id
        ):
            abort(404)
        if str(row["source_reference"] or "").startswith(
            f"{DEFAULT_LUNCH_SOURCE_PREFIX}:"
        ):
            conn.execute(
                """
                INSERT OR IGNORE INTO default_lunch_exceptions
                    (instructor_id, target_date)
                VALUES (?, ?)
                """,
                (row["instructor_id"], row["target_date"]),
            )
        conn.execute("DELETE FROM instructor_time_off WHERE id = ?", (time_off_id,))
        _audit(
            conn,
            "busy_time_deleted",
            details={
                "time_off_id": time_off_id,
                "instructor_id": row["instructor_id"],
                "target_date": row["target_date"],
            },
        )
    return jsonify({"success": True})


def _slot_resource(conn, instructor_id, machine_id):
    row = conn.execute(
        """
        SELECT i.id AS instructor_id, i.name AS instructor_name, i.branch_id,
               m.id AS machine_id, m.machine_code, m.category AS machine_category
        FROM instructors i JOIN machines m ON m.id = ?
        WHERE i.id = ? AND i.is_active = 1 AND m.is_active = 1
          AND i.verification_status = 'verified' AND i.branch_id = m.branch_id
        """,
        (machine_id, instructor_id),
    ).fetchone()
    if not row:
        raise ValueError("Choose active staff and equipment from the same branch.")
    if current_user.role == "instructor" and instructor_id != current_user.instructor_id:
        abort(403)
    return row


@app.post("/api/calendar/booking-slots")
@role_required("admin")
def api_calendar_create_booking_slot():
    payload = request.get_json(silent=True) or {}
    try:
        instructor_id = int(payload.get("instructor_id"))
        machine_id = int(payload.get("machine_id"))
        target = _validate_booking_date(payload.get("target_date"), enforce_online_window=False)
        start_time, end_time, start_minutes, end_minutes = _busy_time_range(payload.get("start_time"), payload.get("end_time"))
        _validate_staff_day_range(start_minutes, end_minutes, "Booking slots")
        dates, repeat_rule = _repeat_dates(target, payload.get("repeat"), payload.get("repeat_count"))
        notes = str(payload.get("notes") or "").strip()[:500]
        series_id = secrets.token_urlsafe(12) if len(dates) > 1 else None
        with get_db() as conn:
            conn.execute("BEGIN IMMEDIATE")
            resource = _slot_resource(conn, instructor_id, machine_id)
            created = []
            for position, occurrence_date in enumerate(dates, start=1):
                slot_id = conn.execute(
                    """
                    INSERT INTO booking_slots
                        (instructor_id, machine_id, branch_id, target_date,
                         start_time, end_time, notes, series_id, repeat_rule,
                         series_position, series_count, created_by)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (instructor_id, machine_id, resource["branch_id"], occurrence_date.isoformat(),
                     start_time, end_time, notes or None, series_id, repeat_rule,
                     position, len(dates), current_user.id),
                ).lastrowid
                row = dict(conn.execute(
                    """SELECT s.*, i.name AS instructor_name, m.machine_code,
                              m.category AS machine_category
                       FROM booking_slots s JOIN instructors i ON i.id=s.instructor_id
                       JOIN machines m ON m.id=s.machine_id WHERE s.id=?""",
                    (slot_id,),
                ).fetchone())
                created.append(_calendar_slot_event(row))
            _audit(conn, "booking_slot_created", details={"created_count": len(created)})
        return jsonify({"success": True, "event": created[0], "events": created, "created_count": len(created)}), 201
    except (TypeError, ValueError) as exc:
        return jsonify({"error": str(exc)}), 400


@app.patch("/api/calendar/booking-slots/<int:slot_id>")
@role_required("admin")
def api_calendar_update_booking_slot(slot_id):
    payload = request.get_json(silent=True) or {}
    try:
        revision = int(payload.get("revision"))
        with get_db() as conn:
            conn.execute("BEGIN IMMEDIATE")
            existing = conn.execute("SELECT * FROM booking_slots WHERE id=?", (slot_id,)).fetchone()
            if not existing:
                abort(404)
            if current_user.role == "instructor" and existing["instructor_id"] != current_user.instructor_id:
                abort(404)
            if revision != existing["calendar_revision"]:
                return jsonify({"error": "This slot changed in another window. Refresh and try again."}), 409
            instructor_id = int(payload.get("instructor_id") or existing["instructor_id"])
            machine_id = int(payload.get("machine_id") or existing["machine_id"])
            target = _validate_booking_date(payload.get("target_date") or existing["target_date"], enforce_online_window=False)
            start_time, end_time, start_minutes, end_minutes = _busy_time_range(payload.get("start_time") or existing["start_time"], payload.get("end_time") or existing["end_time"])
            _validate_staff_day_range(start_minutes, end_minutes, "Booking slots")
            notes = str(payload.get("notes") if "notes" in payload else existing["notes"] or "").strip()[:500]
            resource = _slot_resource(conn, instructor_id, machine_id)
            cursor = conn.execute(
                """UPDATE booking_slots SET instructor_id=?, machine_id=?, branch_id=?,
                   target_date=?, start_time=?, end_time=?, notes=?,
                   calendar_revision=calendar_revision+1, updated_at=CURRENT_TIMESTAMP
                   WHERE id=? AND calendar_revision=?""",
                (instructor_id, machine_id, resource["branch_id"], target.isoformat(),
                 start_time, end_time, notes or None, slot_id, revision),
            )
            if not cursor.rowcount:
                return jsonify({"error": "This slot changed in another window. Refresh and try again."}), 409
            row = dict(conn.execute(
                """SELECT s.*, i.name AS instructor_name, m.machine_code,
                          m.category AS machine_category
                   FROM booking_slots s JOIN instructors i ON i.id=s.instructor_id
                   JOIN machines m ON m.id=s.machine_id WHERE s.id=?""", (slot_id,)
            ).fetchone())
            _audit(conn, "booking_slot_updated", details={"slot_id": slot_id})
        return jsonify({"success": True, "event": _calendar_slot_event(row)})
    except (TypeError, ValueError) as exc:
        return jsonify({"error": str(exc)}), 400


@app.delete("/api/calendar/booking-slots/<int:slot_id>")
@role_required("admin")
def api_calendar_delete_booking_slot(slot_id):
    with get_db() as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute("SELECT * FROM booking_slots WHERE id=?", (slot_id,)).fetchone()
        if not row:
            abort(404)
        if current_user.role == "instructor" and row["instructor_id"] != current_user.instructor_id:
            abort(404)
        conn.execute("DELETE FROM booking_slots WHERE id=?", (slot_id,))
        _audit(conn, "booking_slot_deleted", details={"slot_id": slot_id})
    return jsonify({"success": True})


@app.post("/api/calendar/appointments")
@permission_required("write_access")
def api_calendar_create_appointment():
    payload = request.get_json(silent=True) or {}
    try:
        note = str(payload.get("notes") or "").strip()[:500]
        if not note:
            raise ValueError("Appointment notes are required.")
        student_id = int(payload.get("student_id"))
        machine_id, instructor_id = _parse_resource_ids(
            payload.get("machine_id"), payload.get("instructor_id")
        )
        target = _validate_booking_date(
            payload.get("target_date"), enforce_online_window=False
        )
        start_time = str(payload.get("start_time") or "")
        start_minutes = _time_to_minutes(start_time)
        service_ids = _parse_service_ids(payload.get("service_ids"))
        requested_status = str(payload.get("status") or "Approved").strip()
        allowed_statuses = {
            "Pending",
            "Approved",
            "Not Confirmed",
            "Rejected",
            "Completed",
            "No-show",
            "Running Late",
            "Arrived",
            "Rescheduled",
            "Cancelled",
            "No Action",
        }
        if requested_status not in allowed_statuses:
            raise ValueError("Choose a valid appointment status.")
        if current_user.role == "instructor" and requested_status not in {
            "Approved",
            "Pending",
            "Completed",
        }:
            raise ValueError(
                "Instructors may create appointments only as Confirmed, Pending, or Completed."
            )
        dates, repeat_rule = _repeat_dates(
            target, payload.get("repeat"), payload.get("repeat_count")
        )
        with get_db() as conn:
            conn.execute("BEGIN IMMEDIATE")
            resource = _staff_booking_resources(
                conn, student_id, instructor_id, machine_id
            )
            if not str(resource["full_name"] or "").strip():
                raise ValueError("Client name is required.")
            if not str(resource["phone"] or "").strip():
                raise ValueError(
                    "Client phone number is required. Update Client Details before booking."
                )
            services = _selected_services(
                conn,
                resource["branch_id"],
                service_ids,
                instructor_id=instructor_id,
                machine_id=machine_id,
                enforce_instructor_assignment=False,
            )
            if not services:
                raise ValueError("Choose at least one service.")
            service_duration = sum(
                int(service["duration_minutes"]) for service in services
            )
            requested_end = str(payload.get("end_time") or "")
            if requested_end:
                end_minutes = _time_to_minutes(requested_end)
                duration = end_minutes - start_minutes
            else:
                duration = service_duration
                end_minutes = start_minutes + duration
            if duration < 15 or duration > 480 or duration % 15:
                raise ValueError(
                    "Appointments must last 15 minutes to 8 hours in 15-minute steps."
                )
            _validate_staff_day_range(start_minutes, end_minutes, "Appointments")
            end_time = _minutes_to_time(end_minutes)
            for occurrence_date in dates:
                _assert_active_appointment_not_past(
                    occurrence_date,
                    start_minutes,
                    requested_status,
                    action="created",
                )
                if requested_status in ACTIVE_BOOKING_STATUSES:
                    _assert_appointment_outside_breaks(
                        conn,
                        instructor_id,
                        occurrence_date,
                        start_minutes,
                        end_minutes,
                    )
            # A2Z operates on the visible appointment range only. Private
            # padding was removed because it made visibly free slots fail.
            buffer_before = 0
            buffer_after = 0
            allow_double_booking = bool(payload.get("allow_double_booking")) if current_user.role == "admin" else False
            if (
                buffer_before < 0
                or buffer_after < 0
                or buffer_before > 120
                or buffer_after > 120
                or buffer_before % 5
                or buffer_after % 5
            ):
                raise ValueError("Private padding must use 5-minute steps up to 2 hours.")
            if requested_status in ACTIVE_BOOKING_STATUSES and not allow_double_booking:
                for occurrence_date in dates:
                    slots = _available_slots(
                        conn,
                        resource["branch_id"],
                        machine_id,
                        instructor_id,
                        occurrence_date,
                        student_id,
                        duration,
                        buffer_before,
                        buffer_after,
                        require_student_assignment=False,
                        enforce_advance_notice=False,
                        respect_working_hours=False,
                    )
                    if {"start": start_time, "end": end_time} not in slots:
                        raise AppointmentConflictError(
                            f"{occurrence_date.isoformat()} at {start_time}: "
                            + _appointment_conflict_for_range(
                                conn,
                                target=occurrence_date,
                                start_time=start_time,
                                end_time=end_time,
                                student_id=student_id,
                                instructor_id=instructor_id,
                                machine_id=machine_id,
                            )
                        )
            service_name = ", ".join(service["name"] for service in services)
            price_cents = sum(int(service["price_cents"]) for service in services)
            series_id = secrets.token_urlsafe(12) if len(dates) > 1 else None
            created_rows = []
            for series_position, occurrence_date in enumerate(dates, start=1):
                cursor = conn.execute(
                    """
                    INSERT INTO bookings
                        (student_name, mobile_number, student_user_id, machine_id,
                         instructor_id, branch_id, target_date, start_time, end_time,
                         validation_status, notes, service_id, service_name,
                         service_price_cents, currency, buffer_before_minutes,
                         buffer_after_minutes, reviewed_by, reviewed_at,
                         cancelled_at, series_id, repeat_rule, series_position,
                         series_count, allow_double_booking, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                            ?, CURRENT_TIMESTAMP, ?, ?, ?, ?, ?,
                            ?, CURRENT_TIMESTAMP)
                    """,
                    (
                        resource["full_name"],
                        resource["phone"] or "",
                        student_id,
                        machine_id,
                        instructor_id,
                        resource["branch_id"],
                        occurrence_date.isoformat(),
                        start_time,
                        end_time,
                        requested_status,
                        note,
                        services[0]["id"],
                        service_name,
                        price_cents,
                        services[0]["currency"],
                        buffer_before,
                        buffer_after,
                        current_user.id,
                        (
                            datetime.now(timezone.utc).isoformat()
                            if requested_status == "Cancelled"
                            else None
                        ),
                        series_id,
                        repeat_rule,
                        series_position,
                        len(dates),
                        int(allow_double_booking),
                    ),
                )
                booking_id = cursor.lastrowid
                for position, service in enumerate(services):
                    conn.execute(
                        """
                        INSERT INTO booking_services
                            (booking_id, service_id, service_name, duration_minutes,
                             price_cents, currency, sort_order)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            booking_id,
                            service["id"],
                            service["name"],
                            service["duration_minutes"],
                            service["price_cents"],
                            service["currency"],
                            position,
                        ),
                    )
                _audit(
                    conn,
                    "booking_created_by_staff",
                    booking_id,
                    {
                        "target_date": occurrence_date.isoformat(),
                        "start_time": start_time,
                        "repeat_rule": repeat_rule,
                    },
                )
                if requested_status == "Approved":
                    _queue_booking_notifications(
                        conn, booking_id, "appointment_approved"
                    )
                elif requested_status == "Rejected":
                    _queue_booking_notifications(
                        conn, booking_id, "appointment_rejected"
                    )
                elif requested_status == "Cancelled":
                    _queue_booking_notifications(
                        conn, booking_id, "appointment_cancelled"
                    )
                created_rows.append(_booking_rows(conn, "b.id = ?", (booking_id,))[0])
        created_events = [_calendar_event(row) for row in created_rows]
        for event in created_events:
            event["service_ids"] = service_ids
        return jsonify(
            {
                "success": True,
                "event": created_events[0],
                "events": created_events,
                "created_count": len(created_events),
            }
        ), 201
    except AppointmentConflictError as exc:
        return jsonify(
            {
                "error": str(exc),
                "conflict_type": "schedule",
                "can_override": current_user.role == "admin",
            }
        ), 409
    except (TypeError, ValueError) as exc:
        return jsonify({"error": str(exc)}), 400
    except sqlite3.IntegrityError:
        return jsonify({"error": "That time now conflicts with another appointment."}), 409


@app.patch("/api/calendar/appointments/<int:booking_id>")
@permission_required("write_access")
def api_calendar_reschedule_appointment(booking_id):
    payload = request.get_json(silent=True) or {}
    try:
        revision = int(payload.get("revision"))
        with get_db() as conn:
            conn.execute("BEGIN IMMEDIATE")
            booking = conn.execute(
                "SELECT * FROM bookings WHERE id = ?", (booking_id,)
            ).fetchone()
            if not booking:
                abort(404)
            if (
                current_user.role == "instructor"
                and booking["instructor_id"] != current_user.instructor_id
            ):
                abort(404)
            if booking["calendar_revision"] != revision:
                return jsonify(
                    {
                        "error": "This appointment changed in another window. The calendar has been refreshed."
                    }
                ), 409
            target = _validate_booking_date(
                payload.get("target_date") or booking["target_date"],
                enforce_online_window=False,
            )
            start_time = str(payload.get("start_time") or booking["start_time"])
            start_minutes = _time_to_minutes(start_time)
            instructor_id = (
                current_user.instructor_id
                if current_user.role == "instructor"
                else int(payload.get("instructor_id") or booking["instructor_id"])
            )
            machine_id = int(payload.get("machine_id") or booking["machine_id"])
            student_id = int(payload.get("student_id") or booking["student_user_id"])
            resource = _staff_booking_resources(
                conn,
                student_id,
                instructor_id,
                machine_id,
            )
            if "notes" in payload:
                if not str(resource["full_name"] or "").strip():
                    raise ValueError("Client name is required.")
                if not str(resource["phone"] or "").strip():
                    raise ValueError(
                        "Client phone number is required. Update Client Details before saving."
                    )
                if not str(payload.get("notes") or "").strip():
                    raise ValueError("Appointment notes are required.")
            existing_service_ids = [
                row["service_id"]
                for row in conn.execute(
                    """
                    SELECT service_id FROM booking_services
                    WHERE booking_id = ? AND service_id IS NOT NULL
                    ORDER BY sort_order, id
                    """,
                    (booking_id,),
                ).fetchall()
            ]
            if not existing_service_ids and booking["service_id"]:
                existing_service_ids = [booking["service_id"]]
            service_ids = (
                _parse_service_ids(payload.get("service_ids"))
                if "service_ids" in payload
                else list(existing_service_ids)
            )
            services = _selected_services(
                conn,
                resource["branch_id"],
                service_ids,
                instructor_id=instructor_id,
                machine_id=machine_id,
                enforce_instructor_assignment=False,
            )
            if not services and "service_ids" in payload:
                raise ValueError("Choose at least one service.")
            requested_end = str(payload.get("end_time") or "")
            if requested_end:
                end_minutes = _time_to_minutes(requested_end)
                duration = end_minutes - start_minutes
            else:
                duration = _time_to_minutes(booking["end_time"]) - _time_to_minutes(
                    booking["start_time"]
                )
                end_minutes = start_minutes + duration
            if duration < 15 or duration > 480 or duration % 15:
                raise ValueError(
                    "Appointments must last 15 minutes to 8 hours in 15-minute steps."
                )
            _validate_staff_day_range(start_minutes, end_minutes, "Appointments")
            end_time = _minutes_to_time(end_minutes)
            next_status = str(
                payload.get("status") or booking["validation_status"]
            ).strip()
            allowed_statuses = {
                "Pending",
                "Approved",
                "Not Confirmed",
                "Rejected",
                "Completed",
                "No-show",
                "Running Late",
                "Arrived",
                "Rescheduled",
                "Cancelled",
                "No Action",
            }
            if next_status not in allowed_statuses:
                raise ValueError("Choose a valid appointment status.")
            if current_user.role == "instructor" and next_status not in {
                booking["validation_status"],
                "Pending",
                "Completed",
            }:
                raise ValueError(
                    "Instructors may update appointment status only to Pending or Completed."
                )
            _assert_active_appointment_not_past(
                target,
                start_minutes,
                next_status,
                action="moved",
            )
            if next_status in ACTIVE_BOOKING_STATUSES:
                _assert_appointment_outside_breaks(
                    conn,
                    instructor_id,
                    target,
                    start_minutes,
                    end_minutes,
                )
            # Availability is based only on the visible appointment range.
            next_buffer_before = 0
            next_buffer_after = 0
            allow_double_booking = (
                bool(payload.get("allow_double_booking", booking["allow_double_booking"]))
                if current_user.role == "admin"
                else bool(booking["allow_double_booking"])
            )
            if (
                next_buffer_before < 0
                or next_buffer_after < 0
                or next_buffer_before > 120
                or next_buffer_after > 120
                or next_buffer_before % 5
                or next_buffer_after % 5
            ):
                raise ValueError("Private padding must use 5-minute steps up to 2 hours.")
            if next_status in ACTIVE_BOOKING_STATUSES and not allow_double_booking:
                slots = _available_slots(
                    conn,
                    resource["branch_id"],
                    machine_id,
                    instructor_id,
                    target,
                    student_id,
                    duration,
                    next_buffer_before,
                    next_buffer_after,
                    booking_id,
                    require_student_assignment=False,
                    enforce_advance_notice=False,
                    respect_working_hours=False,
                )
                if {"start": start_time, "end": end_time} not in slots:
                    raise AppointmentConflictError(
                        _appointment_conflict_for_range(
                            conn,
                            target=target,
                            start_time=start_time,
                            end_time=end_time,
                            student_id=student_id,
                            instructor_id=instructor_id,
                            machine_id=machine_id,
                            exclude_booking_id=booking_id,
                        )
                    )
            if services:
                primary_service_id = services[0]["id"]
                service_name = ", ".join(service["name"] for service in services)
                price_cents = sum(int(service["price_cents"]) for service in services)
                currency = services[0]["currency"]
            else:
                primary_service_id = booking["service_id"]
                service_name = booking["service_name"]
                price_cents = int(booking["service_price_cents"] or 0)
                currency = booking["currency"] or "INR"
            notes = (
                str(payload.get("notes") or "").strip()[:500]
                if "notes" in payload
                else booking["notes"]
            )
            old_values = {
                "date": booking["target_date"],
                "start": booking["start_time"],
                "end": booking["end_time"],
                "instructor_id": booking["instructor_id"],
                "machine_id": booking["machine_id"],
                "student_user_id": booking["student_user_id"],
                "status": booking["validation_status"],
                "service_ids": existing_service_ids,
            }
            cursor = conn.execute(
                """
                UPDATE bookings
                SET target_date = ?, start_time = ?, end_time = ?,
                    instructor_id = ?, machine_id = ?, branch_id = ?,
                    student_user_id = ?, student_name = ?, mobile_number = ?,
                    validation_status = ?, notes = ?, service_id = ?,
                    service_name = ?, service_price_cents = ?, currency = ?,
                    buffer_before_minutes = ?, buffer_after_minutes = ?,
                    allow_double_booking = ?,
                    cancelled_at = ?,
                    calendar_revision = calendar_revision + 1,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ? AND calendar_revision = ?
                """,
                (
                    target.isoformat(),
                    start_time,
                    end_time,
                    instructor_id,
                    machine_id,
                    resource["branch_id"],
                    student_id,
                    resource["full_name"],
                    resource["phone"] or "",
                    next_status,
                    notes or None,
                    primary_service_id,
                    service_name,
                    price_cents,
                    currency,
                    next_buffer_before,
                    next_buffer_after,
                    int(allow_double_booking),
                    (
                        datetime.now(timezone.utc).isoformat()
                        if next_status == "Cancelled"
                        else None
                    ),
                    booking_id,
                    revision,
                ),
            )
            if not cursor.rowcount:
                return jsonify({"error": "This appointment changed in another window."}), 409
            conn.execute("DELETE FROM booking_services WHERE booking_id = ?", (booking_id,))
            for position, service in enumerate(services):
                conn.execute(
                    """
                    INSERT INTO booking_services
                        (booking_id, service_id, service_name, duration_minutes,
                         price_cents, currency, sort_order)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        booking_id,
                        service["id"],
                        service["name"],
                        service["duration_minutes"],
                        service["price_cents"],
                        service["currency"],
                        position,
                    ),
                )
            _audit(
                conn,
                "booking_updated_by_staff",
                booking_id,
                {
                    "old": old_values,
                    "new": {
                        "date": target.isoformat(),
                        "start": start_time,
                        "end": end_time,
                        "instructor_id": instructor_id,
                        "machine_id": machine_id,
                        "student_user_id": student_id,
                        "status": next_status,
                        "service_ids": service_ids,
                    },
                },
            )
            client_visible_changed = any(
                (
                    old_values["date"] != target.isoformat(),
                    old_values["start"] != start_time,
                    old_values["end"] != end_time,
                    old_values["instructor_id"] != instructor_id,
                    old_values["machine_id"] != machine_id,
                    old_values["student_user_id"] != student_id,
                    old_values["service_ids"] != service_ids,
                )
            )
            if next_status == "Cancelled":
                _queue_booking_notifications(
                    conn, booking_id, "appointment_cancelled"
                )
            elif next_status == "Approved":
                if old_values["status"] != "Approved":
                    _queue_booking_notifications(
                        conn, booking_id, "appointment_approved"
                    )
                elif client_visible_changed:
                    _queue_booking_notifications(
                        conn, booking_id, "appointment_rescheduled"
                    )
            elif next_status == "Rejected":
                if old_values["status"] != "Rejected":
                    _queue_booking_notifications(
                        conn, booking_id, "appointment_rejected"
                    )
            elif (
                next_status in {"Completed", "No-show"}
                or old_values["status"] == "Approved"
            ):
                _cancel_queued_booking_notifications(conn, booking_id)
            row = _booking_rows(conn, "b.id = ?", (booking_id,))[0]
        event = _calendar_event(row)
        event["service_ids"] = service_ids
        return jsonify({"success": True, "event": event})
    except AppointmentConflictError as exc:
        return jsonify(
            {
                "error": str(exc),
                "conflict_type": "schedule",
                "can_override": current_user.role == "admin",
            }
        ), 409
    except (TypeError, ValueError) as exc:
        return jsonify({"error": str(exc)}), 400
    except sqlite3.IntegrityError:
        return jsonify({"error": "That time now conflicts with another appointment."}), 409


@app.delete("/api/calendar/appointments/<int:booking_id>")
@permission_required("write_access")
def api_calendar_cancel_appointment(booking_id):
    payload = request.get_json(silent=True) or {}
    with get_db() as conn:
        conn.execute("BEGIN IMMEDIATE")
        booking = conn.execute(
            "SELECT * FROM bookings WHERE id = ?", (booking_id,)
        ).fetchone()
        if not booking:
            abort(404)
        if (
            current_user.role == "instructor"
            and booking["instructor_id"] != current_user.instructor_id
        ):
            abort(404)
        if payload.get("revision") is not None:
            try:
                supplied_revision = int(payload["revision"])
            except (TypeError, ValueError):
                return jsonify({"error": "Refresh the calendar and try again."}), 400
            if supplied_revision != booking["calendar_revision"]:
                return jsonify(
                    {
                        "error": "This appointment changed in another window. The calendar has been refreshed."
                    }
                ), 409
        if booking["validation_status"] not in ACTIVE_BOOKING_STATUSES:
            return jsonify({"error": "This appointment is already closed."}), 409
        conn.execute(
            """
            UPDATE bookings
            SET validation_status = 'Cancelled',
                cancelled_at = CURRENT_TIMESTAMP,
                calendar_revision = calendar_revision + 1,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (booking_id,),
        )
        _audit(conn, "booking_cancelled", booking_id)
        _queue_booking_notifications(conn, booking_id, "appointment_cancelled")
        row = _booking_rows(conn, "b.id = ?", (booking_id,))[0]
    return jsonify({"success": True, "event": _calendar_event(row)})


@app.delete("/api/calendar/appointments/<int:booking_id>/permanent")
@role_required("admin")
def api_calendar_delete_appointment(booking_id):
    payload = request.get_json(silent=True) or {}
    with get_db() as conn:
        conn.execute("BEGIN IMMEDIATE")
        booking = conn.execute(
            "SELECT id, calendar_revision FROM bookings WHERE id = ?", (booking_id,)
        ).fetchone()
        if not booking:
            abort(404)
        if payload.get("revision") is not None:
            try:
                supplied_revision = int(payload["revision"])
            except (TypeError, ValueError):
                return jsonify({"error": "Refresh the calendar and try again."}), 400
            if supplied_revision != booking["calendar_revision"]:
                return jsonify(
                    {"error": "This appointment changed in another window. Refresh and try again."}
                ), 409
        conn.execute("DELETE FROM audit_events WHERE booking_id = ?", (booking_id,))
        conn.execute("DELETE FROM bookings WHERE id = ?", (booking_id,))
        _audit(conn, "appointment_permanently_deleted", details={"booking_id": booking_id})
    return jsonify({"success": True})


@app.patch("/api/calendar/appointments/<int:booking_id>/instructor-status")
@role_required("instructor")
def api_calendar_instructor_status(booking_id):
    """Allow an instructor to update only the appointment status dropdown."""
    payload = request.get_json(silent=True) or {}
    next_status = str(payload.get("status") or "").strip()
    if next_status not in {"No Action", "Pending", "Completed"}:
        return jsonify(
            {"error": "Instructors may select No Action, Pending, or Completed."}
        ), 400
    try:
        revision = int(payload.get("revision"))
    except (TypeError, ValueError):
        return jsonify({"error": "Refresh the calendar and try again."}), 400
    with get_db() as conn:
        conn.execute("BEGIN IMMEDIATE")
        booking = conn.execute(
            """
            SELECT b.*, u.is_active AS client_is_active
            FROM bookings b
            JOIN users u ON u.id = b.student_user_id
            WHERE b.id = ? AND b.instructor_id = ?
            """,
            (booking_id, current_user.instructor_id),
        ).fetchone()
        if not booking:
            abort(404)
        if not booking["client_is_active"]:
            return jsonify({"error": "This customer is no longer active."}), 409
        if booking["validation_status"] in {"Cancelled", "Rejected"}:
            return jsonify({"error": "This appointment is already closed."}), 409
        if revision != booking["calendar_revision"]:
            return jsonify(
                {"error": "This appointment changed in another window. Refresh and try again."}
            ), 409
        conn.execute(
            """
            UPDATE bookings
            SET validation_status = ?, reviewed_by = ?,
                reviewed_at = CURRENT_TIMESTAMP,
                calendar_revision = calendar_revision + 1,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (next_status, current_user.id, booking_id),
        )
        _audit(conn, "instructor_status_updated", booking_id, {"status": next_status})
        row = _booking_rows(conn, "b.id = ?", (booking_id,))[0]
    return jsonify({"success": True, "event": _calendar_event(row)})


@app.get("/instructor/dashboard")
@role_required("instructor")
def instructor_dashboard():
    if not current_user.instructor_id:
        abort(403)
    today = datetime.now(IST).date()
    current_time = datetime.now(IST).strftime("%H:%M")
    history_start = today - timedelta(days=30)
    week_end = today + timedelta(days=7)
    with get_db() as conn:
        pending_bookings = _booking_rows(
            conn,
            "b.instructor_id = ? AND b.validation_status = 'Pending' AND b.target_date >= ?",
            (current_user.instructor_id, today.isoformat()),
        )
        schedule_bookings = _booking_rows(
            conn,
            "b.instructor_id = ? AND b.validation_status = 'Approved' "
            "AND b.target_date BETWEEN ? AND ?",
            (current_user.instructor_id, history_start.isoformat(), week_end.isoformat()),
        )
        stats = {
            "pending": len(pending_bookings),
            "today": sum(1 for booking in schedule_bookings if booking["target_date"] == today.isoformat()),
            "this_week": sum(
                1 for booking in schedule_bookings if booking["target_date"] >= today.isoformat()
            ),
            "attendance_due": sum(
                1
                for booking in schedule_bookings
                if booking["target_date"] < today.isoformat()
                or (
                    booking["target_date"] == today.isoformat()
                    and booking["end_time"] <= current_time
                )
            ),
        }
        assigned_students = _assigned_students(conn, current_user.instructor_id)
        instructor_profile = conn.execute(
            "SELECT * FROM instructors WHERE id = ?", (current_user.instructor_id,)
        ).fetchone()
    return render_template(
        "instructor_dashboard.html",
        pending_bookings=pending_bookings,
        schedule_bookings=schedule_bookings,
        assigned_students=assigned_students[:5],
        assigned_student_count=len(assigned_students),
        instructor_profile=dict(instructor_profile) if instructor_profile else None,
        stats=stats,
        today=today.isoformat(),
        current_time=current_time,
    )


def _assigned_students(conn, instructor_id):
    today = datetime.now(IST).date().isoformat()
    return [
        dict(row)
        for row in conn.execute(
            """
            SELECT u.id, u.full_name, u.email, u.phone, u.branch_id,
                   br.name AS branch_name, a.id AS assignment_id, a.assigned_at,
                   sum(CASE WHEN b.validation_status = 'Pending' THEN 1 ELSE 0 END)
                       AS pending_count,
                   sum(CASE WHEN b.validation_status = 'Approved' AND b.target_date >= ?
                            THEN 1 ELSE 0 END) AS approved_count,
                   min(CASE WHEN b.validation_status = 'Approved' AND b.target_date >= ?
                            THEN b.target_date || ' ' || b.start_time END) AS next_session
            FROM student_instructor_assignments a
            JOIN users u ON u.id = a.student_user_id
            LEFT JOIN branches br ON br.id = u.branch_id
            LEFT JOIN bookings b ON b.student_user_id = u.id
                                AND b.instructor_id = a.instructor_id
            WHERE a.instructor_id = ? AND a.is_active = 1 AND u.is_active = 1
            GROUP BY u.id, a.id
            ORDER BY next_session IS NULL, next_session, lower(u.full_name)
            """,
            (today, today, instructor_id),
        ).fetchall()
    ]


@app.get("/instructor/students")
@role_required("instructor")
def instructor_students():
    if not current_user.instructor_id:
        abort(403)
    query = " ".join((request.args.get("q") or "").split()).lower()[:100]
    with get_db() as conn:
        assigned_students = _assigned_students(conn, current_user.instructor_id)
    if query:
        assigned_students = [
            student
            for student in assigned_students
            if query in (student["full_name"] or "").lower()
            or query in (student["email"] or "").lower()
        ]
    return render_template(
        "instructor_students.html", assigned_students=assigned_students, search_query=query
    )


def _create_client_record(conn, payload):
    full_name = _validate_full_name(payload.get("full_name"))
    contacts = _client_contact_values(payload)
    if not contacts["email"] and not contacts["phone"]:
        raise ValueError("Enter at least one email address or phone number.")

    raw_branch_id = payload.get("branch_id") or current_user.branch_id
    branch_id = _validate_branch(conn, raw_branch_id)
    if current_user.role == "instructor" and branch_id != current_user.branch_id:
        abort(403)

    duplicate = _matching_contact_record(
        conn,
        emails=(contacts["email"], contacts["secondary_email"]),
        phones=(contacts["phone"], contacts["secondary_phone"]),
    )
    if duplicate:
        raise DuplicateClientError(duplicate)

    profile_payload = dict(payload)
    if not profile_payload.get("preferred_channel"):
        profile_payload["preferred_channel"] = (
            "email" if contacts["email"] else "sms"
        )
    profile = _client_profile_values(profile_payload)

    for _attempt in range(10):
        username = f"client-{secrets.token_hex(8)}"
        if not conn.execute(
            "SELECT 1 FROM users WHERE lower(username) = lower(?)", (username,)
        ).fetchone():
            break
    else:
        raise RuntimeError("A unique internal client reference could not be created.")

    user_id = conn.execute(
        """
        INSERT INTO users
            (username, password_hash, role, full_name, email, phone, branch_id,
             is_active, login_enabled, must_change_password)
        VALUES (?, ?, 'student', ?, ?, ?, ?, 1, 0, 0)
        """,
        (
            username,
            generate_password_hash(secrets.token_urlsafe(32)),
            full_name,
            contacts["email"],
            contacts["phone"],
            branch_id,
        ),
    ).lastrowid
    conn.execute(
        """
        INSERT INTO client_profiles
            (user_id, secondary_phone, secondary_email, birthday, gender,
             zip_code, city, street, internal_notes, tags, reminders_enabled,
             preferred_channel, updated_by, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        """,
        (
            user_id,
            contacts["secondary_phone"],
            contacts["secondary_email"],
            profile["birthday"],
            profile["gender"],
            profile["zip_code"],
            profile["city"],
            profile["street"],
            profile["internal_notes"],
            profile["tags"],
            profile["reminders_enabled"],
            profile["preferred_channel"],
            current_user.id,
        ),
    )
    if current_user.role == "instructor":
        conn.execute(
            """
            INSERT INTO student_instructor_assignments
                (student_user_id, instructor_id, assigned_by)
            VALUES (?, ?, ?)
            ON CONFLICT(student_user_id, instructor_id) DO UPDATE SET
                is_active = 1, ended_at = NULL, assigned_by = excluded.assigned_by
            """,
            (user_id, current_user.instructor_id, current_user.id),
        )
    _audit(
        conn,
        "client_created",
        details={"client_id": user_id, "branch_id": branch_id},
    )
    return {
        "id": user_id,
        "full_name": full_name,
        "email": contacts["email"] or "",
        "phone": contacts["phone"] or "",
        "branch_id": branch_id,
        "login_enabled": False,
    }


@app.post("/api/calendar/clients")
@permission_required("client_database", "write_access")
def api_calendar_create_client():
    payload = request.get_json(silent=True) if request.is_json else request.form
    payload = payload or {}
    try:
        with get_db() as conn:
            conn.execute("BEGIN IMMEDIATE")
            client_record = _create_client_record(conn, payload)
        return jsonify({"success": True, "client": client_record}), 201
    except DuplicateClientError as exc:
        existing_client = None
        if exc.client_id:
            with get_db() as conn:
                row = conn.execute(
                    "SELECT id, full_name, COALESCE(email, '') AS email, COALESCE(phone, '') AS phone, branch_id FROM users WHERE id = ? AND role = 'student'",
                    (exc.client_id,),
                ).fetchone()
                existing_client = dict(row) if row else None
        return jsonify(
            {
                "error": str(exc),
                "existing_client_id": exc.client_id,
                "existing_client": existing_client,
            }
        ), 409
    except (TypeError, ValueError) as exc:
        return jsonify({"error": str(exc)}), 400


@app.get("/api/calendar/clients/search")
@permission_required("client_database")
def api_calendar_search_clients():
    query = " ".join((request.args.get("q") or "").split())[:100]
    if len(query) < 2:
        return jsonify({"clients": []})
    pattern = f"%{query}%"
    clauses = [
        "u.role = 'student'",
        "u.is_active = 1",
        "(lower(COALESCE(u.full_name, '')) LIKE lower(?) OR lower(COALESCE(u.email, '')) LIKE lower(?) OR COALESCE(u.phone, '') LIKE ?)",
    ]
    params = [pattern, pattern, pattern]
    if current_user.role == "instructor":
        clauses.append("u.branch_id = ?")
        params.append(current_user.branch_id)
    with get_db() as conn:
        rows = conn.execute(
            f"""
            SELECT u.id, u.full_name, COALESCE(u.email, '') AS email,
                   COALESCE(u.phone, '') AS phone, u.branch_id
            FROM users u
            WHERE {' AND '.join(clauses)}
            ORDER BY CASE WHEN lower(u.full_name) = lower(?) THEN 0 ELSE 1 END,
                     lower(u.full_name)
            LIMIT 10
            """,
            (*params, query),
        ).fetchall()
    clients = []
    for row in rows:
        record = dict(row)
        if not current_user.has_permission("contact_details"):
            phone = record.get("phone") or ""
            email = record.get("email") or ""
            record["phone"] = ("•" * max(0, len(phone) - 3)) + phone[-3:] if phone else ""
            if email and "@" in email:
                local, domain = email.split("@", 1)
                record["email"] = (local[:1] + "•••@" + domain) if local else "•••@" + domain
        parts = (record["full_name"] or "").strip().split(None, 1)
        record["first_name"] = parts[0] if parts else ""
        record["last_name"] = parts[1] if len(parts) > 1 else ""
        clients.append(record)
    return jsonify({"clients": clients})


@app.get("/api/calendar/clients/<int:client_id>/booking-summary")
@permission_required("client_database")
def api_calendar_client_booking_summary(client_id):
    today = datetime.now(IST).date().isoformat()
    with get_db() as conn:
        client = _client_access_row(conn, client_id)
        if not client:
            abort(404)
        rows = _booking_rows(
            conn,
            "b.student_user_id = ? AND b.target_date >= ? "
            "AND b.validation_status NOT IN ('Cancelled', 'Rejected')",
            (client_id, today),
            "b.target_date ASC, b.start_time ASC",
        )[:5]
    phone = client["phone"] or ""
    if not current_user.has_permission("contact_details"):
        phone = ("•" * max(0, len(phone) - 3)) + phone[-3:] if phone else ""
    return jsonify(
        {
            "client": {"id": client_id, "full_name": client["full_name"], "phone": phone},
            "upcoming": [
                {
                    "id": row["id"],
                    "date": row["target_date"],
                    "start_time": row["start_time"],
                    "end_time": row["end_time"],
                    "service_name": row["service_name"],
                    "instructor_name": row["instructor_name"],
                    "status": row["validation_status"],
                }
                for row in rows
            ],
        }
    )


@app.get("/clients/new")
@permission_required("client_database", "write_access")
def client_new():
    with get_db() as conn:
        if current_user.role in {"admin", "booking_agent"}:
            branches = [
                dict(row)
                for row in conn.execute(
                    "SELECT id, name FROM branches WHERE is_active = 1 ORDER BY name"
                ).fetchall()
            ]
        else:
            row = conn.execute(
                "SELECT id, name FROM branches WHERE id = ? AND is_active = 1",
                (current_user.branch_id,),
            ).fetchone()
            branches = [dict(row)] if row else []
    return render_template("client_new.html", branches=branches)


@app.post("/clients")
@permission_required("client_database", "write_access")
def client_create():
    try:
        with get_db() as conn:
            conn.execute("BEGIN IMMEDIATE")
            client_record = _create_client_record(conn, request.form)
        flash("Client record created.", "success")
        return redirect(url_for("client_detail", client_id=client_record["id"]))
    except DuplicateClientError as exc:
        flash(str(exc), "warning")
        if exc.client_id:
            return redirect(url_for("client_detail", client_id=exc.client_id))
    except (TypeError, ValueError) as exc:
        flash(str(exc), "error")
    return redirect(url_for("clients_directory"))


def _client_access_row(conn, client_id):
    if current_user.role in {"admin", "booking_agent"}:
        row = conn.execute(
            """
            SELECT u.*, br.name AS branch_name,
                   cp.secondary_phone, cp.secondary_email, cp.birthday,
                   cp.gender, cp.zip_code, cp.city, cp.street,
                   cp.internal_notes, cp.tags,
                   COALESCE(cp.reminders_enabled, 1) AS reminders_enabled,
                   COALESCE(cp.preferred_channel, br.reminder_channel, 'email')
                       AS preferred_channel
            FROM users u
            LEFT JOIN branches br ON br.id = u.branch_id
            LEFT JOIN client_profiles cp ON cp.user_id = u.id
            WHERE u.id = ? AND u.role = 'student'
            """,
            (client_id,),
        ).fetchone()
    else:
        row = conn.execute(
            """
            SELECT u.*, br.name AS branch_name,
                   cp.secondary_phone, cp.secondary_email, cp.birthday,
                   cp.gender, cp.zip_code, cp.city, cp.street,
                   cp.internal_notes, cp.tags,
                   COALESCE(cp.reminders_enabled, 1) AS reminders_enabled,
                       COALESCE(cp.preferred_channel, br.reminder_channel, 'email')
                           AS preferred_channel
            FROM users u
            LEFT JOIN branches br ON br.id = u.branch_id
            LEFT JOIN client_profiles cp ON cp.user_id = u.id
            WHERE u.id = ? AND u.role = 'student' AND u.is_active = 1
              AND (
                EXISTS (
                    SELECT 1 FROM student_instructor_assignments a
                    WHERE a.student_user_id = u.id AND a.instructor_id = ?
                      AND a.is_active = 1
                )
                OR EXISTS (
                    SELECT 1 FROM bookings b
                    WHERE b.student_user_id = u.id AND b.instructor_id = ?
                )
              )
            """,
            (client_id, current_user.instructor_id, current_user.instructor_id),
        ).fetchone()
    return row


@app.get("/clients")
@permission_required("client_database")
def clients_directory():
    query = " ".join((request.args.get("q") or "").split())[:100]
    params = []
    clauses = ["u.role = 'student'"]
    if current_user.role == "instructor":
        clauses.append("u.is_active = 1")
        clauses.append(
            """
            (
                EXISTS (
                    SELECT 1 FROM student_instructor_assignments a
                    WHERE a.student_user_id = u.id AND a.instructor_id = ?
                      AND a.is_active = 1
                )
                OR EXISTS (
                    SELECT 1 FROM bookings scoped_booking
                    WHERE scoped_booking.student_user_id = u.id
                      AND scoped_booking.instructor_id = ?
                )
            )
            """
        )
        params.extend((current_user.instructor_id, current_user.instructor_id))
    if query:
        pattern = f"%{query}%"
        clauses.append(
            """
            (lower(COALESCE(u.full_name, '')) LIKE lower(?)
             OR lower(COALESCE(u.email, '')) LIKE lower(?)
             OR COALESCE(u.phone, '') LIKE ?
             OR lower(COALESCE(cp.secondary_email, '')) LIKE lower(?)
             OR COALESCE(cp.secondary_phone, '') LIKE ?)
            """
        )
        params.extend((pattern, pattern, pattern, pattern, pattern))
    with get_db() as conn:
        clients = [
            dict(row)
            for row in conn.execute(
                f"""
                SELECT u.id, u.full_name, u.email, u.phone, u.is_active,
                       u.branch_id, br.name AS branch_name,
                       count(b.id) AS appointment_count,
                       sum(CASE WHEN b.validation_status = 'Approved'
                                  AND b.target_date >= date('now')
                                THEN 1 ELSE 0 END) AS upcoming_count,
                       max(CASE WHEN b.validation_status IN ('Completed', 'No-show')
                                THEN b.target_date END) AS last_visit
                FROM users u
                LEFT JOIN branches br ON br.id = u.branch_id
                LEFT JOIN client_profiles cp ON cp.user_id = u.id
                LEFT JOIN bookings b ON b.student_user_id = u.id
                WHERE {" AND ".join(clauses)}
                GROUP BY u.id
                ORDER BY u.is_active DESC, lower(u.full_name)
                LIMIT 300
                """,
                params,
            ).fetchall()
        ]
    if not current_user.has_permission("contact_details"):
        for client in clients:
            phone = client.get("phone") or ""
            email = client.get("email") or ""
            client["phone"] = ("•" * max(0, len(phone) - 3)) + phone[-3:] if phone else ""
            if email and "@" in email:
                local, domain = email.split("@", 1)
                client["email"] = (local[:1] + "•••@" + domain) if local else "•••@" + domain
    return render_template(
        "clients.html", clients=clients, search_query=query
    )


@app.get("/clients/<int:client_id>")
@permission_required("client_database")
def client_detail(client_id):
    with get_db() as conn:
        client = _client_access_row(conn, client_id)
        if not client:
            abort(404)
        bookings = _booking_rows(
            conn,
            "b.student_user_id = ?",
            (client_id,),
            "b.target_date DESC, b.start_time DESC",
        )
        intake_values = [
            dict(row)
            for row in conn.execute(
                """
                SELECT biv.*, b.target_date, b.start_time,
                       COALESCE(NULLIF(b.service_name, ''), s.name, m.category)
                           AS service_name
                FROM booking_intake_values biv
                JOIN bookings b ON b.id = biv.booking_id
                JOIN machines m ON m.id = b.machine_id
                LEFT JOIN services s ON s.id = b.service_id
                WHERE b.student_user_id = ?
                ORDER BY b.target_date DESC, b.start_time DESC, biv.id
                """,
                (client_id,),
            ).fetchall()
        ]
        branches = []
        available_instructors = []
        assigned_instructor_ids = []
        if current_user.role == "admin":
            branches = [
                dict(row)
                for row in conn.execute(
                    """
                    SELECT id, name, is_active FROM branches
                    ORDER BY is_active DESC, lower(name)
                    """
                ).fetchall()
            ]
            available_instructors = [
                dict(row)
                for row in conn.execute(
                    """
                    SELECT i.id, i.name, i.branch_id, br.name AS branch_name
                    FROM instructors i
                    JOIN branches br ON br.id = i.branch_id
                    WHERE i.is_active = 1
                      AND i.verification_status = 'verified'
                    ORDER BY br.name, lower(i.name)
                    """
                ).fetchall()
            ]
            assigned_instructor_ids = [
                row["instructor_id"]
                for row in conn.execute(
                    """
                    SELECT instructor_id FROM student_instructor_assignments
                    WHERE student_user_id = ? AND is_active = 1
                    ORDER BY instructor_id
                    """,
                    (client_id,),
                ).fetchall()
            ]
    client_record = dict(client)
    if not current_user.has_permission("contact_details"):
        for field in ("phone", "secondary_phone"):
            value = client_record.get(field) or ""
            client_record[field] = ("•" * max(0, len(value) - 3)) + value[-3:] if value else ""
        for field in ("email", "secondary_email"):
            value = client_record.get(field) or ""
            if value and "@" in value:
                local, domain = value.split("@", 1)
                client_record[field] = (local[:1] + "•••@" + domain) if local else "•••@" + domain
    if not current_user.has_permission("client_notes"):
        client_record["internal_notes"] = ""
        client_record["tags"] = ""
    today = datetime.now(IST).date().isoformat()
    upcoming_bookings = sorted(
        (booking for booking in bookings if booking["target_date"] >= today),
        key=lambda booking: (booking["target_date"], booking["start_time"]),
    )
    past_bookings = [
        booking for booking in bookings if booking["target_date"] < today
    ]
    return render_template(
        "client_detail.html",
        client=client_record,
        bookings=bookings,
        upcoming_bookings=upcoming_bookings,
        past_bookings=past_bookings,
        intake_values=intake_values,
        branches=branches,
        available_instructors=available_instructors,
        assigned_instructor_ids=assigned_instructor_ids,
        today=today,
    )


@app.post("/clients/<int:client_id>/profile")
@permission_required("client_database", "write_access")
def client_profile_update(client_id):
    try:
        with get_db() as conn:
            conn.execute("BEGIN IMMEDIATE")
            existing = _client_access_row(conn, client_id)
            if not existing:
                abort(404)

            full_name = (
                _validate_full_name(request.form.get("full_name"))
                if "full_name" in request.form
                else existing["full_name"]
            )
            contact_payload = {
                "email": (
                    request.form.get("email")
                    if "email" in request.form
                    else existing["email"]
                ),
                "phone": (
                    request.form.get("phone")
                    if "phone" in request.form
                    else existing["phone"]
                ),
                "secondary_email": (
                    request.form.get("secondary_email")
                    if "secondary_email" in request.form
                    else existing["secondary_email"]
                ),
                "secondary_phone": (
                    request.form.get("secondary_phone")
                    if "secondary_phone" in request.form
                    else existing["secondary_phone"]
                ),
            }
            contacts = _client_contact_values(contact_payload)
            if not contacts["email"] and not contacts["phone"]:
                raise ValueError("Enter at least one email address or phone number.")
            duplicate = _matching_contact_record(
                conn,
                emails=(contacts["email"], contacts["secondary_email"]),
                phones=(contacts["phone"], contacts["secondary_phone"]),
                exclude_user_id=client_id,
            )
            if duplicate:
                raise DuplicateClientError(duplicate)

            profile_payload = {
                field: (
                    request.form.get(field)
                    if field in request.form
                    else existing[field]
                )
                for field in (
                    "birthday",
                    "gender",
                    "zip_code",
                    "city",
                    "street",
                    "internal_notes",
                    "tags",
                    "preferred_channel",
                )
            }
            # HTML checkboxes are omitted when cleared, so absence means off.
            profile_payload["reminders_enabled"] = (
                request.form.get("reminders_enabled") == "1"
            )
            profile = _client_profile_values(profile_payload)

            branch_id = existing["branch_id"]
            selected_instructor_ids = None
            if current_user.role == "admin":
                branch_id = _validate_branch(
                    conn, request.form.get("branch_id", existing["branch_id"])
                )
                if "manage_instructor_assignments" in request.form:
                    selected_instructor_ids = sorted(
                        {
                            int(value)
                            for value in request.form.getlist("instructor_ids")
                            if str(value).isdigit()
                        }
                    )
                if branch_id != existing["branch_id"]:
                    active_booking = conn.execute(
                        """
                        SELECT 1 FROM bookings
                        WHERE student_user_id = ?
                          AND validation_status IN ('Pending', 'Approved')
                          AND target_date >= ? LIMIT 1
                        """,
                        (client_id, datetime.now(IST).date().isoformat()),
                    ).fetchone()
                    if active_booking:
                        raise ValueError(
                            "Cancel this client's future appointments before changing branch."
                        )
                if selected_instructor_ids:
                    placeholders = ",".join("?" for _ in selected_instructor_ids)
                    matching = conn.execute(
                        f"""
                        SELECT count(*) FROM instructors
                        WHERE id IN ({placeholders}) AND branch_id = ?
                          AND is_active = 1
                          AND verification_status = 'verified'
                        """,
                        (*selected_instructor_ids, branch_id),
                    ).fetchone()[0]
                    if matching != len(selected_instructor_ids):
                        raise ValueError(
                            "Assign only active, verified instructors from the client's branch."
                        )

            conn.execute(
                """
                UPDATE users
                SET full_name = ?, email = ?, phone = ?, branch_id = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (
                    full_name,
                    contacts["email"],
                    contacts["phone"],
                    branch_id,
                    client_id,
                ),
            )
            conn.execute(
                """
                INSERT INTO client_profiles
                    (user_id, secondary_phone, secondary_email, birthday,
                     gender, zip_code, city, street, internal_notes, tags,
                     reminders_enabled, preferred_channel, updated_by,
                     updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                        CURRENT_TIMESTAMP)
                ON CONFLICT(user_id) DO UPDATE SET
                    secondary_phone = excluded.secondary_phone,
                    secondary_email = excluded.secondary_email,
                    birthday = excluded.birthday,
                    gender = excluded.gender,
                    zip_code = excluded.zip_code,
                    city = excluded.city,
                    street = excluded.street,
                    internal_notes = excluded.internal_notes,
                    tags = excluded.tags,
                    reminders_enabled = excluded.reminders_enabled,
                    preferred_channel = excluded.preferred_channel,
                    updated_by = excluded.updated_by,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (
                    client_id,
                    contacts["secondary_phone"],
                    contacts["secondary_email"],
                    profile["birthday"],
                    profile["gender"],
                    profile["zip_code"],
                    profile["city"],
                    profile["street"],
                    profile["internal_notes"],
                    profile["tags"],
                    profile["reminders_enabled"],
                    profile["preferred_channel"],
                    current_user.id,
                ),
            )
            if selected_instructor_ids is not None:
                active_assignment_ids = {
                    row["instructor_id"]
                    for row in conn.execute(
                        """
                        SELECT instructor_id FROM student_instructor_assignments
                        WHERE student_user_id = ? AND is_active = 1
                        """,
                        (client_id,),
                    ).fetchall()
                }
                removed_instructor_ids = (
                    active_assignment_ids - set(selected_instructor_ids)
                )
                if removed_instructor_ids:
                    placeholders = ",".join("?" for _ in removed_instructor_ids)
                    active_pair_booking = conn.execute(
                        f"""
                        SELECT 1 FROM bookings
                        WHERE student_user_id = ?
                          AND instructor_id IN ({placeholders})
                          AND validation_status IN ('Pending', 'Approved')
                          AND target_date >= ? LIMIT 1
                        """,
                        (
                            client_id,
                            *sorted(removed_instructor_ids),
                            datetime.now(IST).date().isoformat(),
                        ),
                    ).fetchone()
                    if active_pair_booking:
                        raise ValueError(
                            "Keep an instructor assigned while they have a future appointment with this client."
                        )
                    conn.execute(
                        f"""
                        UPDATE student_instructor_assignments
                        SET is_active = 0, ended_at = CURRENT_TIMESTAMP
                        WHERE student_user_id = ?
                          AND instructor_id IN ({placeholders})
                          AND is_active = 1
                        """,
                        (client_id, *sorted(removed_instructor_ids)),
                    )
                for instructor_id in selected_instructor_ids:
                    conn.execute(
                        """
                        INSERT INTO student_instructor_assignments
                            (student_user_id, instructor_id, assigned_by)
                        VALUES (?, ?, ?)
                        ON CONFLICT(student_user_id, instructor_id) DO UPDATE SET
                            is_active = 1,
                            ended_at = NULL,
                            assigned_by = excluded.assigned_by,
                            assigned_at = CURRENT_TIMESTAMP
                        """,
                        (client_id, instructor_id, current_user.id),
                    )
            approved_booking_ids = [
                row["id"]
                for row in conn.execute(
                    """
                    SELECT id FROM bookings
                    WHERE student_user_id = ? AND validation_status = 'Approved'
                    """,
                    (client_id,),
                ).fetchall()
            ]
            for booking_id in approved_booking_ids:
                _rebuild_booking_reminders(conn, booking_id)
            _audit(
                conn,
                "client_profile_updated",
                details={
                    "client_id": client_id,
                    "branch_id": branch_id,
                    "instructor_ids": selected_instructor_ids,
                },
            )
        flash("Client record updated.", "success")
    except DuplicateClientError as exc:
        flash(str(exc), "warning")
    except (TypeError, ValueError) as exc:
        flash(str(exc), "error")
    return redirect(url_for("client_detail", client_id=client_id))


@app.post("/clients/<int:client_id>/toggle")
@role_required("admin")
def client_toggle(client_id):
    today = datetime.now(IST).date().isoformat()
    with get_db() as conn:
        conn.execute("BEGIN IMMEDIATE")
        client = conn.execute(
            """
            SELECT id, full_name, is_active FROM users
            WHERE id = ? AND role = 'student'
            """,
            (client_id,),
        ).fetchone()
        if not client:
            abort(404)
        deactivating = bool(client["is_active"])
        next_active = 0 if deactivating else 1
        conn.execute(
            """
            UPDATE users
            SET is_active = ?,
                deactivated_at = CASE
                    WHEN ? = 0 THEN CURRENT_TIMESTAMP ELSE NULL
                END,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (next_active, next_active, client_id),
        )
        if deactivating:
            conn.execute(
                """
                UPDATE student_instructor_assignments
                SET is_active = 0, ended_at = CURRENT_TIMESTAMP
                WHERE student_user_id = ? AND is_active = 1
                """,
                (client_id,),
            )
            booking_ids = [
                row["id"]
                for row in conn.execute(
                    """
                    SELECT id FROM bookings
                    WHERE student_user_id = ? AND target_date >= ?
                      AND validation_status IN ('Pending', 'Approved')
                    """,
                    (client_id, today),
                ).fetchall()
            ]
            _cancel_active_bookings(conn, booking_ids)
        _audit(
            conn,
            "client_archived" if deactivating else "client_reactivated",
            details={"client_id": client_id},
        )
    flash(
        "Client archived; future appointments were cancelled safely."
        if deactivating
        else "Client reactivated.",
        "success",
    )
    return redirect(url_for("client_detail", client_id=client_id))


@app.get("/intake-files/<int:value_id>")
@role_required("instructor", "admin")
def intake_file_download(value_id):
    with get_db() as conn:
        row = conn.execute(
            """
            SELECT biv.*, b.student_user_id
            FROM booking_intake_values biv
            JOIN bookings b ON b.id = biv.booking_id
            WHERE biv.id = ? AND biv.file_path IS NOT NULL
            """,
            (value_id,),
        ).fetchone()
        if not row or not _client_access_row(conn, row["student_user_id"]):
            abort(404)
    storage_root = (Path(app.instance_path) / "intake_uploads").resolve()
    file_path = Path(row["file_path"]).resolve()
    if storage_root not in file_path.parents or not file_path.is_file():
        abort(404)
    response = send_file(
        file_path,
        as_attachment=True,
        download_name=row["file_name"],
        mimetype=row["mime_type"] or "application/octet-stream",
        max_age=0,
    )
    response.headers["Cache-Control"] = "private, no-store"
    return response


def _csv_safe(value):
    text = "" if value is None else str(value)
    if text.startswith(("=", "+", "-", "@", "\t", "\r")):
        return "'" + text
    return text


def _csv_response(filename, headers, rows):
    output = io.StringIO()
    writer = csv.writer(output, lineterminator="\n")
    writer.writerow(headers)
    for row in rows:
        writer.writerow([_csv_safe(value) for value in row])
    response = Response(
        "\ufeff" + output.getvalue(),
        content_type="text/csv; charset=utf-8",
    )
    response.headers["Content-Disposition"] = f'attachment; filename="{filename}"'
    response.headers["Cache-Control"] = "private, no-store"
    return response


def _booking_insights_data(conn, days):
    """Build anonymous booking statistics; no client fields leave this function."""
    today = datetime.now(IST).date()
    start = today - timedelta(days=days - 1)
    previous_start = start - timedelta(days=days)
    statuses = {
        row["validation_status"]: row["total"]
        for row in conn.execute(
            """
            SELECT validation_status, count(*) AS total
            FROM bookings WHERE target_date BETWEEN ? AND ?
            GROUP BY validation_status
            """,
            (start.isoformat(), today.isoformat()),
        ).fetchall()
    }
    total = sum(statuses.values())
    previous_total = conn.execute(
        """
        SELECT count(*) FROM bookings
        WHERE target_date BETWEEN ? AND ?
        """,
        (previous_start.isoformat(), (start - timedelta(days=1)).isoformat()),
    ).fetchone()[0]
    services = [
        dict(row)
        for row in conn.execute(
            """
            SELECT COALESCE(NULLIF(bs.service_name, ''), NULLIF(b.service_name, ''),
                            'Unspecified service') AS name,
                   count(DISTINCT b.id) AS bookings
            FROM bookings b
            LEFT JOIN booking_services bs ON bs.booking_id = b.id
            WHERE b.target_date BETWEEN ? AND ?
              AND b.validation_status NOT IN ('Cancelled', 'Rejected')
            GROUP BY COALESCE(NULLIF(bs.service_name, ''), NULLIF(b.service_name, ''),
                              'Unspecified service')
            ORDER BY bookings DESC, name
            LIMIT 12
            """,
            (start.isoformat(), today.isoformat()),
        ).fetchall()
    ]
    equipment = [
        dict(row)
        for row in conn.execute(
            """
            SELECT COALESCE(NULLIF(m.category, ''), m.machine_code) AS name,
                   count(*) AS bookings
            FROM bookings b JOIN machines m ON m.id = b.machine_id
            WHERE b.target_date BETWEEN ? AND ?
              AND b.validation_status NOT IN ('Cancelled', 'Rejected')
            GROUP BY COALESCE(NULLIF(m.category, ''), m.machine_code)
            ORDER BY bookings DESC, name
            LIMIT 10
            """,
            (start.isoformat(), today.isoformat()),
        ).fetchall()
    ]
    instructors = [
        dict(row)
        for row in conn.execute(
            """
            SELECT i.name, count(*) AS bookings
            FROM bookings b JOIN instructors i ON i.id = b.instructor_id
            WHERE b.target_date BETWEEN ? AND ?
              AND b.validation_status NOT IN ('Cancelled', 'Rejected')
            GROUP BY i.id, i.name ORDER BY bookings DESC, i.name LIMIT 10
            """,
            (start.isoformat(), today.isoformat()),
        ).fetchall()
    ]
    weekday_rows = conn.execute(
        """
        SELECT CAST(strftime('%w', target_date) AS INTEGER) AS weekday,
               count(*) AS bookings
        FROM bookings WHERE target_date BETWEEN ? AND ?
          AND validation_status NOT IN ('Cancelled', 'Rejected')
        GROUP BY weekday ORDER BY bookings DESC
        """,
        (start.isoformat(), today.isoformat()),
    ).fetchall()
    sqlite_day_names = ("Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday")
    weekdays = [
        {"name": sqlite_day_names[int(row["weekday"])], "bookings": row["bookings"]}
        for row in weekday_rows
    ]
    time_rows = conn.execute(
        """
        SELECT CAST(substr(start_time, 1, 2) AS INTEGER) AS hour,
               count(*) AS bookings
        FROM bookings WHERE target_date BETWEEN ? AND ?
          AND validation_status NOT IN ('Cancelled', 'Rejected')
        GROUP BY hour ORDER BY bookings DESC, hour LIMIT 8
        """,
        (start.isoformat(), today.isoformat()),
    ).fetchall()
    hours = [
        {"name": f"{(int(row['hour']) % 12) or 12}:00 {'am' if int(row['hour']) < 12 else 'pm'}", "bookings": row["bookings"]}
        for row in time_rows
    ]
    unique_clients = conn.execute(
        """
        SELECT count(DISTINCT student_user_id) FROM bookings
        WHERE target_date BETWEEN ? AND ?
        """,
        (start.isoformat(), today.isoformat()),
    ).fetchone()[0]
    return {
        "period": {
            "days": days,
            "start": start.isoformat(),
            "end": today.isoformat(),
        },
        "totals": {
            "bookings": total,
            "previous_period_bookings": previous_total,
            "unique_clients": unique_clients,
            "completed": statuses.get("Completed", 0),
            "cancelled": statuses.get("Cancelled", 0),
            "no_show": statuses.get("No-show", 0),
            "approved": statuses.get("Approved", 0),
            "pending": statuses.get("Pending", 0),
        },
        "services": services,
        "equipment": equipment,
        "instructors": instructors,
        "weekdays": weekdays,
        "start_hours": hours,
    }


@app.route("/admin/booking-insights", methods=["GET", "POST"])
@role_required("admin")
def admin_booking_insights():
    try:
        days = int(request.values.get("days", 90))
    except (TypeError, ValueError):
        days = 90
    if days not in {30, 90, 180, 365}:
        days = 90
    analysis = None
    with get_db() as conn:
        insights = _booking_insights_data(conn, days)
        if request.method == "POST":
            try:
                analysis = generate_booking_insights(insights)
                _audit(
                    conn,
                    "gemini_booking_insights_generated",
                    details={"days": days, "aggregate_only": True},
                )
            except GeminiInsightsError as exc:
                flash(str(exc), "error")
    total = max(1, int(insights["totals"]["bookings"] or 0))
    change = insights["totals"]["bookings"] - insights["totals"]["previous_period_bookings"]
    return render_template(
        "booking_insights.html",
        insights=insights,
        analysis=analysis,
        gemini_ready=gemini_configured(),
        selected_days=days,
        booking_change=change,
        cancellation_rate=round(insights["totals"]["cancelled"] * 100 / total, 1),
        no_show_rate=round(insights["totals"]["no_show"] * 100 / total, 1),
    )


@app.get("/exports/appointments.csv")
@permission_required("export_appointments")
def export_appointments_csv():
    clauses = []
    params = []
    if current_user.role == "instructor":
        clauses.append("b.instructor_id = ?")
        params.append(current_user.instructor_id)
    with get_db() as conn:
        bookings = _booking_rows(
            conn,
            " AND ".join(clauses),
            params,
            "b.target_date DESC, b.start_time DESC",
        )
        _audit(
            conn,
            "appointments_exported",
            details={"record_count": len(bookings)},
        )
    rows = [
        (
            booking["id"],
            booking["target_date"],
            booking["start_time"],
            booking["end_time"],
            booking["student_name"],
            booking["service_name"],
            booking["machine_code"],
            booking["instructor_name"],
            booking["branch_name"],
            booking["validation_status"],
            booking["service_price_cents"] / 100,
            booking["currency"],
        )
        for booking in bookings
    ]
    return _csv_response(
        f"a2z-appointments-{datetime.now(IST).date().isoformat()}.csv",
        (
            "Booking ID",
            "Date",
            "Start",
            "End",
            "Client",
            "Services",
            "Equipment",
            "Instructor",
            "Branch",
            "Status",
            "Price",
            "Currency",
        ),
        rows,
    )


@app.get("/exports/clients.csv")
@permission_required("export_clients")
def export_clients_csv():
    params = []
    scope = ""
    if current_user.role == "instructor":
        scope = """
            AND EXISTS (
                SELECT 1 FROM student_instructor_assignments a
                WHERE a.student_user_id = u.id AND a.instructor_id = ?
                  AND a.is_active = 1
            )
        """
        params.append(current_user.instructor_id)
    with get_db() as conn:
        rows = conn.execute(
            f"""
            SELECT u.id, u.full_name, u.email, u.phone, br.name AS branch_name,
                   cp.secondary_email, cp.secondary_phone, cp.birthday,
                   cp.gender, cp.street, cp.city, cp.zip_code,
                   u.is_active, COALESCE(cp.reminders_enabled, 1) AS reminders_enabled,
                   COALESCE(cp.preferred_channel, br.reminder_channel, 'email')
                       AS preferred_channel
            FROM users u
            LEFT JOIN branches br ON br.id = u.branch_id
            LEFT JOIN client_profiles cp ON cp.user_id = u.id
            WHERE u.role = 'student' {scope}
            ORDER BY lower(u.full_name)
            """,
            params,
        ).fetchall()
        _audit(conn, "clients_exported", details={"record_count": len(rows)})
    return _csv_response(
        f"a2z-clients-{datetime.now(IST).date().isoformat()}.csv",
        (
            "Client ID",
            "Name",
            "Email",
            "Secondary Email",
            "Mobile",
            "Secondary Mobile",
            "Birthday",
            "Gender",
            "Street",
            "City",
            "Postcode",
            "Branch",
            "Active",
            "Reminders",
            "Channel",
        ),
        [
            (
                row["id"],
                row["full_name"],
                row["email"],
                row["secondary_email"],
                row["phone"],
                row["secondary_phone"],
                row["birthday"],
                row["gender"],
                row["street"],
                row["city"],
                row["zip_code"],
                row["branch_name"],
                "Yes" if row["is_active"] else "No",
                "Enabled" if row["reminders_enabled"] else "Disabled",
                row["preferred_channel"].title(),
            )
            for row in rows
        ],
    )


@app.route("/clients/import", methods=["GET", "POST"])
@role_required("admin")
def import_clients_view():
    if request.method == "POST":
        upload = request.files.get("client_file")
        if not upload or not upload.filename:
            flash("Choose an Excel client file.", "error")
            return redirect(url_for("import_clients_view"))
        if Path(upload.filename).suffix.lower() != ".xlsx":
            flash("Client imports must use an .xlsx file.", "error")
            return redirect(url_for("import_clients_view"))
        import_dir = Path(app.instance_path) / "imports"
        import_dir.mkdir(parents=True, exist_ok=True)
        source = import_dir / f"clients-{secrets.token_hex(8)}.xlsx"
        try:
            upload.save(source)
            added, updated = import_clients(source)
            with get_db() as conn:
                _audit(conn, "clients_imported", details={"added": added, "updated": updated})
            flash(f"Client import complete: {added} added and {updated} updated.", "success")
            return redirect(url_for("clients_directory"))
        except (ValueError, OSError, sqlite3.Error) as exc:
            flash(str(exc), "error")
        finally:
            source.unlink(missing_ok=True)
    return render_template("client_import.html")


@app.get("/admin/backups/download")
@role_required("admin")
def download_database_backup():
    backup_dir = backup_directory()
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(IST).strftime("%Y%m%d-%H%M%S")
    target = backup_dir / f"a2z-scheduler-backup-{stamp}.db"
    source_conn = sqlite3.connect(database_path())
    target_conn = sqlite3.connect(target)
    try:
        source_conn.backup(target_conn)
    finally:
        target_conn.close()
        source_conn.close()
    verify_database(target)
    with get_db() as conn:
        _audit(conn, "database_backup_downloaded", details={"file": target.name})
    return send_file(target, as_attachment=True, download_name=target.name)


@app.get("/exports/activity.csv")
@role_required("admin")
def export_activity_csv():
    with get_db() as conn:
        rows = conn.execute(
            """SELECT ae.id, ae.created_at, ae.event_type, ae.booking_id,
                      COALESCE(u.full_name, u.username, 'System') AS actor,
                      ae.details
               FROM audit_events ae LEFT JOIN users u ON u.id=ae.actor_user_id
               ORDER BY ae.created_at DESC, ae.id DESC"""
        ).fetchall()
    return _csv_response(
        "a2z-activity-log.csv",
        ("ID", "Date", "Activity", "Booking ID", "Actor", "Details"),
        [(row["id"], row["created_at"], row["event_type"], row["booking_id"] or "", row["actor"], row["details"] or "") for row in rows],
    )


def _branch_management_values(payload):
    name = " ".join((payload.get("name") or "").split())
    address = " ".join((payload.get("address") or "").split())
    phone = _optional_phone(payload.get("phone"))
    timezone_name = (payload.get("timezone") or "").strip()
    currency = (payload.get("currency") or "").strip().upper()
    reminder_channel = (payload.get("reminder_channel") or "").strip().lower()
    allowed_timezones = {value for value, _label in BRANCH_TIMEZONE_OPTIONS}
    allowed_currencies = {value for value, _label in BRANCH_CURRENCY_OPTIONS}

    if len(name) < 2 or len(name) > 100:
        raise ValueError("Enter a branch name between 2 and 100 characters.")
    if len(address) > 300:
        raise ValueError("Keep the branch address under 300 characters.")
    if timezone_name not in allowed_timezones:
        raise ValueError("Choose a supported branch timezone.")
    if currency not in allowed_currencies:
        raise ValueError("Choose a supported branch currency.")
    if reminder_channel not in {"email", "sms"}:
        raise ValueError("Choose email or SMS as the reminder channel.")
    return {
        "name": name,
        "address": address or None,
        "phone": phone,
        "timezone": timezone_name,
        "currency": currency,
        "reminder_channel": reminder_channel,
    }


def _equipment_management_values(payload):
    machine_code = " ".join((payload.get("machine_code") or "").split()).upper()
    category = " ".join((payload.get("category") or "").split())
    location = " ".join((payload.get("location") or "").split())
    if (
        len(machine_code) < 2
        or len(machine_code) > 80
        or not re.fullmatch(r"[A-Z0-9][A-Z0-9 ._()/&+-]*", machine_code)
    ):
        raise ValueError(
            "Equipment code must be 2–80 letters, numbers, spaces or common separators."
        )
    if len(category) < 2 or len(category) > 100:
        raise ValueError("Enter an equipment category between 2 and 100 characters.")
    if len(location) > 160:
        raise ValueError("Keep the equipment location under 160 characters.")
    return {
        "machine_code": machine_code,
        "category": category,
        "location": location or None,
    }


def _admin_resources_context(conn):
    today = datetime.now(IST).date().isoformat()
    branches = [
        dict(row)
        for row in conn.execute(
            """
            SELECT br.*,
                   (
                       SELECT count(*) FROM machines m
                       WHERE m.branch_id = br.id AND m.is_active = 1
                   ) AS active_machine_count,
                   (
                       SELECT count(*) FROM instructors i
                       WHERE i.branch_id = br.id AND i.is_active = 1
                   ) AS active_instructor_count,
                   (
                       SELECT count(*) FROM services s
                       WHERE s.branch_id = br.id AND s.is_active = 1
                   ) AS active_service_count,
                   (
                       SELECT count(*) FROM bookings b
                       WHERE b.branch_id = br.id AND b.target_date >= ?
                         AND b.validation_status IN ('Pending', 'Approved')
                   ) AS active_future_booking_count
            FROM branches br
            ORDER BY br.is_active DESC, lower(br.name)
            """,
            (today,),
        ).fetchall()
    ]
    machines = [
        dict(row)
        for row in conn.execute(
            """
            SELECT m.*, br.name AS branch_name, br.is_active AS branch_is_active,
                   (
                       SELECT count(*) FROM service_machines sm
                       WHERE sm.machine_id = m.id
                   ) AS service_count,
                   (
                       SELECT count(*) FROM bookings b
                       WHERE b.machine_id = m.id
                   ) AS booking_count,
                   (
                       SELECT count(*) FROM bookings b
                       WHERE b.machine_id = m.id AND b.target_date >= ?
                         AND b.validation_status IN ('Pending', 'Approved')
                   ) AS active_future_booking_count
            FROM machines m
            JOIN branches br ON br.id = m.branch_id
            ORDER BY m.is_active DESC, br.is_active DESC, lower(br.name),
                     lower(m.category), lower(m.machine_code)
            """,
            (today,),
        ).fetchall()
    ]
    return {
        "branches": branches,
        "machines": machines,
        "timezone_options": BRANCH_TIMEZONE_OPTIONS,
        "currency_options": BRANCH_CURRENCY_OPTIONS,
    }


@app.get("/admin/resources")
@role_required("admin")
def admin_resources():
    with get_db() as conn:
        context = _admin_resources_context(conn)
    return render_template("admin_resources.html", **context)


@app.post("/admin/resources/branches")
@role_required("admin")
def admin_branch_create():
    try:
        values = _branch_management_values(request.form)
        with get_db() as conn:
            conn.execute("BEGIN IMMEDIATE")
            duplicate = conn.execute(
                "SELECT 1 FROM branches WHERE lower(name) = lower(?)",
                (values["name"],),
            ).fetchone()
            if duplicate:
                raise ValueError("A branch with that name already exists.")
            branch_id = conn.execute(
                """
                INSERT INTO branches
                    (name, address, phone, timezone, currency,
                     reminder_channel, is_active)
                VALUES (?, ?, ?, ?, ?, ?, 1)
                """,
                (
                    values["name"],
                    values["address"],
                    values["phone"],
                    values["timezone"],
                    values["currency"],
                    values["reminder_channel"],
                ),
            ).lastrowid
            _audit(
                conn,
                "branch_created",
                details={"branch_id": branch_id, "name": values["name"]},
            )
        flash("Branch created.", "success")
        return redirect(url_for("admin_resources", _anchor=f"branch-{branch_id}"))
    except (sqlite3.IntegrityError, TypeError, ValueError) as exc:
        flash(str(exc), "error")
        return redirect(url_for("admin_resources", _anchor="new-branch"))


@app.post("/admin/resources/branches/<int:branch_id>/edit")
@role_required("admin")
def admin_branch_update(branch_id):
    try:
        values = _branch_management_values(request.form)
        with get_db() as conn:
            conn.execute("BEGIN IMMEDIATE")
            branch = conn.execute(
                "SELECT * FROM branches WHERE id = ?", (branch_id,)
            ).fetchone()
            if not branch:
                abort(404)
            duplicate = conn.execute(
                """
                SELECT 1 FROM branches
                WHERE id != ? AND lower(name) = lower(?)
                """,
                (branch_id, values["name"]),
            ).fetchone()
            if duplicate:
                raise ValueError("A branch with that name already exists.")
            conn.execute(
                """
                UPDATE branches
                SET name = ?, address = ?, phone = ?, timezone = ?,
                    currency = ?, reminder_channel = ?
                WHERE id = ?
                """,
                (
                    values["name"],
                    values["address"],
                    values["phone"],
                    values["timezone"],
                    values["currency"],
                    values["reminder_channel"],
                    branch_id,
                ),
            )
            _audit(
                conn,
                "branch_updated",
                details={
                    "branch_id": branch_id,
                    "old_name": branch["name"],
                    "new_name": values["name"],
                },
            )
        flash("Branch details updated.", "success")
    except (sqlite3.IntegrityError, TypeError, ValueError) as exc:
        flash(str(exc), "error")
    return redirect(url_for("admin_resources", _anchor=f"branch-{branch_id}"))


@app.post("/admin/resources/branches/<int:branch_id>/toggle")
@role_required("admin")
def admin_branch_toggle(branch_id):
    today = datetime.now(IST).date().isoformat()
    with get_db() as conn:
        conn.execute("BEGIN IMMEDIATE")
        branch = conn.execute(
            "SELECT * FROM branches WHERE id = ?", (branch_id,)
        ).fetchone()
        if not branch:
            abort(404)
        deactivating = bool(branch["is_active"])
        if deactivating:
            active_future = conn.execute(
                """
                SELECT count(*) FROM bookings
                WHERE branch_id = ? AND target_date >= ?
                  AND validation_status IN ('Pending', 'Approved')
                """,
                (branch_id, today),
            ).fetchone()[0]
            if active_future:
                flash(
                    "Cancel, complete or move this branch's future appointments before archiving it.",
                    "warning",
                )
                return redirect(
                    url_for("admin_resources", _anchor=f"branch-{branch_id}")
                )
            dependencies = conn.execute(
                """
                SELECT
                    (SELECT count(*) FROM machines
                     WHERE branch_id = ? AND is_active = 1) AS machines,
                    (SELECT count(*) FROM instructors
                     WHERE branch_id = ? AND is_active = 1) AS instructors,
                    (SELECT count(*) FROM services
                     WHERE branch_id = ? AND is_active = 1) AS services
                """,
                (branch_id, branch_id, branch_id),
            ).fetchone()
            if any(dependencies):
                flash(
                    "Archive this branch's active services, instructors and equipment first.",
                    "warning",
                )
                return redirect(
                    url_for("admin_resources", _anchor=f"branch-{branch_id}")
                )
        next_active = 0 if deactivating else 1
        conn.execute(
            "UPDATE branches SET is_active = ? WHERE id = ?",
            (next_active, branch_id),
        )
        _audit(
            conn,
            "branch_archived" if deactivating else "branch_reactivated",
            details={"branch_id": branch_id},
        )
    flash(
        "Branch archived. Historical records are retained."
        if deactivating
        else "Branch reactivated.",
        "success",
    )
    return redirect(url_for("admin_resources", _anchor=f"branch-{branch_id}"))


@app.post("/admin/resources/equipment")
@role_required("admin")
def admin_equipment_create():
    try:
        values = _equipment_management_values(request.form)
        with get_db() as conn:
            conn.execute("BEGIN IMMEDIATE")
            branch_id = _validate_branch(conn, request.form.get("branch_id"))
            duplicate = conn.execute(
                "SELECT 1 FROM machines WHERE lower(machine_code) = lower(?)",
                (values["machine_code"],),
            ).fetchone()
            if duplicate:
                raise ValueError("Equipment with that code already exists.")
            machine_id = conn.execute(
                """
                INSERT INTO machines
                    (machine_code, category, location, branch_id, is_active)
                VALUES (?, ?, ?, ?, 1)
                """,
                (
                    values["machine_code"],
                    values["category"],
                    values["location"],
                    branch_id,
                ),
            ).lastrowid
            _audit(
                conn,
                "equipment_created",
                details={
                    "machine_id": machine_id,
                    "machine_code": values["machine_code"],
                    "branch_id": branch_id,
                },
            )
        flash("Equipment added.", "success")
        return redirect(
            url_for("admin_resources", _anchor=f"equipment-{machine_id}")
        )
    except (sqlite3.IntegrityError, TypeError, ValueError) as exc:
        flash(str(exc), "error")
        return redirect(url_for("admin_resources", _anchor="new-equipment"))


@app.post("/admin/resources/equipment/<int:machine_id>/edit")
@role_required("admin")
def admin_equipment_update(machine_id):
    try:
        values = _equipment_management_values(request.form)
        with get_db() as conn:
            conn.execute("BEGIN IMMEDIATE")
            machine = conn.execute(
                "SELECT * FROM machines WHERE id = ?", (machine_id,)
            ).fetchone()
            if not machine:
                abort(404)
            try:
                branch_id = int(request.form.get("branch_id", ""))
            except (TypeError, ValueError):
                raise ValueError("Choose a valid branch.") from None
            branch = conn.execute(
                "SELECT id, is_active FROM branches WHERE id = ?", (branch_id,)
            ).fetchone()
            if not branch:
                raise ValueError("Choose a valid branch.")
            if branch_id != machine["branch_id"] and not branch["is_active"]:
                raise ValueError("Move equipment only to an active branch.")
            if machine["is_active"] and not branch["is_active"]:
                raise ValueError("Active equipment must belong to an active branch.")
            duplicate = conn.execute(
                """
                SELECT 1 FROM machines
                WHERE id != ? AND lower(machine_code) = lower(?)
                """,
                (machine_id, values["machine_code"]),
            ).fetchone()
            if duplicate:
                raise ValueError("Equipment with that code already exists.")
            if branch_id != machine["branch_id"]:
                booking_count = conn.execute(
                    "SELECT count(*) FROM bookings WHERE machine_id = ?",
                    (machine_id,),
                ).fetchone()[0]
                if booking_count:
                    raise ValueError(
                        "Equipment with appointment history cannot move to another branch."
                    )
                service_count = conn.execute(
                    "SELECT count(*) FROM service_machines WHERE machine_id = ?",
                    (machine_id,),
                ).fetchone()[0]
                if service_count:
                    raise ValueError(
                        "Remove this equipment from its services before moving it to another branch."
                    )
            conn.execute(
                """
                UPDATE machines
                SET machine_code = ?, category = ?, location = ?, branch_id = ?
                WHERE id = ?
                """,
                (
                    values["machine_code"],
                    values["category"],
                    values["location"],
                    branch_id,
                    machine_id,
                ),
            )
            _audit(
                conn,
                "equipment_updated",
                details={
                    "machine_id": machine_id,
                    "old_branch_id": machine["branch_id"],
                    "new_branch_id": branch_id,
                },
            )
        flash("Equipment details updated.", "success")
    except (sqlite3.IntegrityError, TypeError, ValueError) as exc:
        flash(str(exc), "error")
    return redirect(
        url_for("admin_resources", _anchor=f"equipment-{machine_id}")
    )


@app.post("/admin/resources/equipment/<int:machine_id>/toggle")
@role_required("admin")
def admin_equipment_toggle(machine_id):
    today = datetime.now(IST).date().isoformat()
    with get_db() as conn:
        conn.execute("BEGIN IMMEDIATE")
        machine = conn.execute(
            """
            SELECT m.*, br.is_active AS branch_is_active
            FROM machines m
            JOIN branches br ON br.id = m.branch_id
            WHERE m.id = ?
            """,
            (machine_id,),
        ).fetchone()
        if not machine:
            abort(404)
        deactivating = bool(machine["is_active"])
        if deactivating:
            active_future = conn.execute(
                """
                SELECT count(*) FROM bookings
                WHERE machine_id = ? AND target_date >= ?
                  AND validation_status IN ('Pending', 'Approved')
                """,
                (machine_id, today),
            ).fetchone()[0]
            if active_future:
                flash(
                    "Cancel, complete or move this equipment's future appointments before archiving it.",
                    "warning",
                )
                return redirect(
                    url_for("admin_resources", _anchor=f"equipment-{machine_id}")
                )
            unsupported_service = conn.execute(
                """
                SELECT s.name
                FROM services s
                JOIN service_machines sm ON sm.service_id = s.id
                WHERE sm.machine_id = ? AND s.is_active = 1
                  AND NOT EXISTS (
                      SELECT 1
                      FROM service_machines alternative
                      JOIN machines other ON other.id = alternative.machine_id
                      WHERE alternative.service_id = s.id
                        AND alternative.machine_id != ?
                        AND other.is_active = 1
                  )
                ORDER BY lower(s.name)
                LIMIT 1
                """,
                (machine_id, machine_id),
            ).fetchone()
            if unsupported_service:
                flash(
                    f"Keep this equipment active until {unsupported_service['name']} "
                    "has another active compatible machine or is archived.",
                    "warning",
                )
                return redirect(
                    url_for("admin_resources", _anchor=f"equipment-{machine_id}")
                )
        elif not machine["branch_is_active"]:
            flash("Reactivate the equipment's branch first.", "warning")
            return redirect(
                url_for("admin_resources", _anchor=f"equipment-{machine_id}")
            )
        next_active = 0 if deactivating else 1
        conn.execute(
            "UPDATE machines SET is_active = ? WHERE id = ?",
            (next_active, machine_id),
        )
        _audit(
            conn,
            "equipment_archived" if deactivating else "equipment_reactivated",
            details={"machine_id": machine_id},
        )
    flash(
        "Equipment archived. Historical appointments are retained."
        if deactivating
        else "Equipment reactivated.",
        "success",
    )
    return redirect(
        url_for("admin_resources", _anchor=f"equipment-{machine_id}")
    )


def _money_to_cents(value):
    try:
        amount = Decimal(str(value or "0")).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )
    except (InvalidOperation, ValueError):
        raise ValueError("Enter a valid price.") from None
    if amount < 0 or amount > Decimal("1000000"):
        raise ValueError("Enter a price between 0 and 1,000,000.")
    return int(amount * 100)


def _currency_code(value):
    currency = (value or "").strip().upper()
    if not re.fullmatch(r"[A-Z]{3}", currency):
        raise ValueError("Enter a three-letter currency code, such as INR or GBP.")
    return currency


def _service_field_values(form, *, default_sort_order):
    label = " ".join((form.get("label") or "").split())
    field_type = (form.get("field_type") or "text").strip().lower()
    allowed_types = {"text", "textarea", "select", "checkbox", "file"}
    if len(label) < 2 or len(label) > 120:
        raise ValueError("Enter a field label between 2 and 120 characters.")
    if field_type not in allowed_types:
        raise ValueError("Choose a supported field type.")

    options = [
        line.strip()
        for line in (form.get("options") or "").splitlines()
        if line.strip()
    ]
    if len(options) > 50 or any(len(option) > 120 for option in options):
        raise ValueError("Use no more than 50 dropdown choices of 120 characters each.")
    if field_type == "select" and not options:
        raise ValueError("Add at least one choice for a dropdown field.")

    duration_adjustment = int(form.get("duration_adjustment_minutes", "0"))
    if (
        duration_adjustment < 0
        or duration_adjustment > 120
        or duration_adjustment % 30
    ):
        raise ValueError("Duration changes must use 30-minute steps up to 2 hours.")
    price_adjustment = _money_to_cents(form.get("price_adjustment"))

    raw_sort_order = (form.get("sort_order") or "").strip()
    sort_order = int(raw_sort_order) if raw_sort_order else int(default_sort_order)
    if sort_order < 0 or sort_order > 10000:
        raise ValueError("Question order must be between 0 and 10,000.")

    return {
        "label": label,
        "field_type": field_type,
        "help_text": (form.get("help_text") or "").strip()[:300] or None,
        "placeholder": (form.get("placeholder") or "").strip()[:200] or None,
        "is_required": 1 if form.get("is_required") == "1" else 0,
        "options_json": (
            json.dumps(options, ensure_ascii=False)
            if field_type == "select"
            else None
        ),
        "price_adjustment_cents": price_adjustment,
        "duration_adjustment_minutes": duration_adjustment,
        "sort_order": sort_order,
    }


def _service_management_context(conn):
    services = [
        dict(row)
        for row in conn.execute(
            """
            SELECT s.*, br.name AS branch_name
            FROM services s JOIN branches br ON br.id = s.branch_id
            ORDER BY s.is_active DESC, br.name, lower(s.name)
            """
        ).fetchall()
    ]
    for service in services:
        service["machine_ids"] = [
            row["machine_id"]
            for row in conn.execute(
                "SELECT machine_id FROM service_machines WHERE service_id = ?",
                (service["id"],),
            ).fetchall()
        ]
        service["instructor_ids"] = [
            row["instructor_id"]
            for row in conn.execute(
                "SELECT instructor_id FROM service_instructors WHERE service_id = ?",
                (service["id"],),
            ).fetchall()
        ]
        service["weekday_numbers"] = {
            int(value)
            for value in (service["available_weekdays"] or "").split(",")
            if value.strip().isdigit()
        }
        service["intake_fields"] = []
        for row in conn.execute(
            """
            SELECT * FROM service_intake_fields
            WHERE service_id = ?
            ORDER BY sort_order, id
            """,
            (service["id"],),
        ).fetchall():
            field = dict(row)
            try:
                options = json.loads(field["options_json"] or "[]")
            except (TypeError, ValueError, json.JSONDecodeError):
                options = []
            field["options_text"] = "\n".join(
                str(option) for option in options if str(option).strip()
            )
            service["intake_fields"].append(field)
    branches = [
        dict(row)
        for row in conn.execute(
            """
            SELECT id, name, currency
            FROM branches WHERE is_active = 1 ORDER BY name
            """
        ).fetchall()
    ]
    machines = [
        dict(row)
        for row in conn.execute(
            """
            SELECT m.id, m.machine_code, m.category, m.branch_id,
                   br.name AS branch_name
            FROM machines m JOIN branches br ON br.id = m.branch_id
            WHERE m.is_active = 1
            ORDER BY br.name, m.category, m.machine_code
            """
        ).fetchall()
    ]
    instructors = [
        dict(row)
        for row in conn.execute(
            """
            SELECT i.id, i.name, i.branch_id, br.name AS branch_name
            FROM instructors i JOIN branches br ON br.id = i.branch_id
            WHERE i.is_active = 1 AND i.verification_status = 'verified'
            ORDER BY br.name, lower(i.name)
            """
        ).fetchall()
    ]
    return {
        "services": services,
        "branches": branches,
        "machines": machines,
        "instructors": instructors,
        "day_names": DAY_NAMES,
    }


@app.route("/admin/services", methods=["GET", "POST"])
@role_required("admin")
def admin_services():
    if request.method == "POST":
        try:
            raw_service_id = request.form.get("service_id", "")
            service_id = int(raw_service_id) if raw_service_id else None
            if service_id is not None and service_id < 1:
                raise ValueError("Choose a valid course.")
            name = " ".join((request.form.get("name") or "").split())
            description = (request.form.get("description") or "").strip()
            category = " ".join((request.form.get("category") or "").split())
            branch_value = request.form.get("branch_id")
            duration = int(request.form.get("duration_minutes", ""))
            price_cents = _money_to_cents(request.form.get("price"))
            raw_currency = request.form.get("currency")
            buffer_before = int(request.form.get("buffer_before_minutes", "0"))
            buffer_after = int(request.form.get("buffer_after_minutes", "0"))
            color = (request.form.get("color") or "#C8141B").strip().upper()
            weekdays = sorted(
                {
                    int(value)
                    for value in request.form.getlist("weekday")
                    if value.isdigit()
                }
            )
            if len(name) < 2 or len(name) > 100:
                raise ValueError("Enter a course name between 2 and 100 characters.")
            if len(description) > 600 or len(category) > 100:
                raise ValueError("Keep the description and category concise.")
            if duration < 30 or duration > 240 or duration % 30:
                raise ValueError("Course duration must use 30-minute steps up to 4 hours.")
            if (
                buffer_before not in range(0, 121, 5)
                or buffer_after not in range(0, 121, 5)
            ):
                raise ValueError("Padding must use 5-minute steps up to 2 hours.")
            if not re.fullmatch(r"#[0-9A-F]{6}", color):
                raise ValueError("Choose a valid course colour.")
            if not weekdays or any(value not in range(7) for value in weekdays):
                raise ValueError("Choose at least one bookable weekday.")
            machine_ids = sorted(
                {
                    int(value)
                    for value in request.form.getlist("machine_id")
                    if value.isdigit()
                }
            )
            instructor_ids = sorted(
                {
                    int(value)
                    for value in request.form.getlist("instructor_id")
                    if value.isdigit()
                }
            )
            if not machine_ids:
                raise ValueError("Choose at least one compatible piece of equipment.")
            with get_db() as conn:
                conn.execute("BEGIN IMMEDIATE")
                branch_id = _validate_branch(conn, branch_value)
                if raw_currency:
                    currency = _currency_code(raw_currency)
                else:
                    currency = conn.execute(
                        "SELECT currency FROM branches WHERE id = ?", (branch_id,)
                    ).fetchone()["currency"]
                existing_service = None
                if service_id is not None:
                    existing_service = conn.execute(
                        "SELECT id, branch_id FROM services WHERE id = ?",
                        (service_id,),
                    ).fetchone()
                    if not existing_service:
                        abort(404)
                    if existing_service["branch_id"] != branch_id:
                        future_appointment = conn.execute(
                            """
                            SELECT 1
                            FROM bookings b
                            WHERE b.target_date >= ?
                              AND b.validation_status IN (?, ?)
                              AND (
                                  b.service_id = ?
                                  OR EXISTS (
                                      SELECT 1 FROM booking_services bs
                                      WHERE bs.booking_id = b.id
                                        AND bs.service_id = ?
                                  )
                              )
                            LIMIT 1
                            """,
                            (
                                datetime.now(IST).date().isoformat(),
                                *ACTIVE_BOOKING_STATUSES,
                                service_id,
                                service_id,
                            ),
                        ).fetchone()
                        if future_appointment:
                            raise ValueError(
                                "Cancel or finish this course's future active "
                                "appointments before changing its branch."
                            )
                if machine_ids:
                    placeholders = ",".join("?" for _ in machine_ids)
                    count = conn.execute(
                        f"""
                        SELECT count(*) FROM machines
                        WHERE id IN ({placeholders}) AND branch_id = ? AND is_active = 1
                        """,
                        (*machine_ids, branch_id),
                    ).fetchone()[0]
                    if count != len(machine_ids):
                        raise ValueError("Choose equipment from the course branch.")
                if instructor_ids:
                    placeholders = ",".join("?" for _ in instructor_ids)
                    count = conn.execute(
                        f"""
                        SELECT count(*) FROM instructors
                        WHERE id IN ({placeholders}) AND branch_id = ?
                          AND is_active = 1 AND verification_status = 'verified'
                        """,
                        (*instructor_ids, branch_id),
                    ).fetchone()[0]
                    if count != len(instructor_ids):
                        raise ValueError("Choose verified instructors from the course branch.")
                values = (
                    branch_id,
                    name,
                    description or None,
                    category or None,
                    duration,
                    price_cents,
                    currency,
                    buffer_before,
                    buffer_after,
                    color,
                    ",".join(str(value) for value in weekdays),
                    1 if request.form.get("requires_approval") == "1" else 0,
                    1 if request.form.get("is_active") == "1" else 0,
                )
                if service_id:
                    cursor = conn.execute(
                        """
                        UPDATE services SET branch_id = ?, name = ?,
                            description = ?, category = ?, duration_minutes = ?,
                            price_cents = ?, currency = ?, buffer_before_minutes = ?,
                            buffer_after_minutes = ?, color = ?,
                            available_weekdays = ?, requires_approval = ?,
                            is_active = ?, updated_at = CURRENT_TIMESTAMP
                        WHERE id = ?
                        """,
                        (*values, service_id),
                    )
                    if not cursor.rowcount:
                        abort(404)
                else:
                    cursor = conn.execute(
                        """
                        INSERT INTO services
                            (branch_id, name, description, category,
                             duration_minutes, price_cents, currency,
                             buffer_before_minutes, buffer_after_minutes,
                             color, available_weekdays, requires_approval,
                             is_active)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        values,
                    )
                    service_id = cursor.lastrowid
                conn.execute(
                    "DELETE FROM service_machines WHERE service_id = ?", (service_id,)
                )
                conn.execute(
                    "DELETE FROM service_instructors WHERE service_id = ?", (service_id,)
                )
                conn.executemany(
                    """
                    INSERT INTO service_machines (service_id, machine_id)
                    VALUES (?, ?)
                    """,
                    [(service_id, machine_id) for machine_id in machine_ids],
                )
                conn.executemany(
                    """
                    INSERT INTO service_instructors (service_id, instructor_id)
                    VALUES (?, ?)
                    """,
                    [(service_id, instructor_id) for instructor_id in instructor_ids],
                )
                _audit(
                    conn,
                    "service_updated" if existing_service else "service_created",
                    details={
                        "service_id": service_id,
                        "branch_id": branch_id,
                        "currency": currency,
                    },
                )
            flash("Course saved.", "success")
            return redirect(url_for("admin_services"))
        except (TypeError, ValueError) as exc:
            flash(str(exc), "error")
        except sqlite3.IntegrityError:
            flash("A course with that name already exists at this branch.", "error")
    with get_db() as conn:
        context = _service_management_context(conn)
    return render_template("services.html", **context)


@app.post("/admin/services/<int:service_id>/fields")
@role_required("admin")
def admin_service_field_add(service_id):
    try:
        with get_db() as conn:
            conn.execute("BEGIN IMMEDIATE")
            if not conn.execute(
                "SELECT 1 FROM services WHERE id = ?", (service_id,)
            ).fetchone():
                abort(404)
            next_sort_order = conn.execute(
                """
                SELECT COALESCE(max(sort_order), 0) + 10
                FROM service_intake_fields WHERE service_id = ?
                """,
                (service_id,),
            ).fetchone()[0]
            values = _service_field_values(
                request.form, default_sort_order=next_sort_order
            )
            base_key = (
                re.sub(r"[^a-z0-9]+", "_", values["label"].lower()).strip("_")[:36]
                or "field"
            )
            field_key = f"{base_key}_{secrets.token_hex(3)}"
            cursor = conn.execute(
                """
                INSERT INTO service_intake_fields
                    (service_id, field_key, label, field_type, help_text,
                     placeholder, is_required, options_json,
                     price_adjustment_cents, duration_adjustment_minutes,
                     sort_order)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    service_id,
                    field_key,
                    values["label"],
                    values["field_type"],
                    values["help_text"],
                    values["placeholder"],
                    values["is_required"],
                    values["options_json"],
                    values["price_adjustment_cents"],
                    values["duration_adjustment_minutes"],
                    values["sort_order"],
                ),
            )
            _audit(
                conn,
                "service_field_created",
                details={"service_id": service_id, "field_id": cursor.lastrowid},
            )
        flash("Booking question added.", "success")
    except (TypeError, ValueError) as exc:
        flash(str(exc), "error")
    return redirect(url_for("admin_services", service=service_id))


@app.post("/admin/services/<int:service_id>/fields/<int:field_id>/edit")
@role_required("admin")
def admin_service_field_edit(service_id, field_id):
    try:
        with get_db() as conn:
            conn.execute("BEGIN IMMEDIATE")
            field = conn.execute(
                """
                SELECT * FROM service_intake_fields
                WHERE id = ? AND service_id = ?
                """,
                (field_id, service_id),
            ).fetchone()
            if not field:
                abort(404)
            values = _service_field_values(
                request.form, default_sort_order=field["sort_order"]
            )
            conn.execute(
                """
                UPDATE service_intake_fields
                SET label = ?, field_type = ?, help_text = ?, placeholder = ?,
                    is_required = ?, options_json = ?,
                    price_adjustment_cents = ?,
                    duration_adjustment_minutes = ?, sort_order = ?
                WHERE id = ? AND service_id = ?
                """,
                (
                    values["label"],
                    values["field_type"],
                    values["help_text"],
                    values["placeholder"],
                    values["is_required"],
                    values["options_json"],
                    values["price_adjustment_cents"],
                    values["duration_adjustment_minutes"],
                    values["sort_order"],
                    field_id,
                    service_id,
                ),
            )
            _audit(
                conn,
                "service_field_updated",
                details={
                    "service_id": service_id,
                    "field_id": field_id,
                    "sort_order": values["sort_order"],
                },
            )
        flash("Booking question updated.", "success")
    except (TypeError, ValueError) as exc:
        flash(str(exc), "error")
    return redirect(url_for("admin_services", service=service_id))


@app.post("/admin/services/<int:service_id>/fields/<int:field_id>/archive")
@role_required("admin")
def admin_service_field_archive(service_id, field_id):
    with get_db() as conn:
        cursor = conn.execute(
            """
            UPDATE service_intake_fields SET is_active = 0
            WHERE id = ? AND service_id = ? AND is_active = 1
            """,
            (field_id, service_id),
        )
        if not cursor.rowcount:
            abort(404)
        _audit(
            conn,
            "service_field_archived",
            details={"service_id": service_id, "field_id": field_id},
        )
    flash("Booking question archived. Historical answers are retained.", "success")
    return redirect(url_for("admin_services", service=service_id))


@app.post("/admin/services/<int:service_id>/fields/<int:field_id>/reactivate")
@role_required("admin")
def admin_service_field_reactivate(service_id, field_id):
    with get_db() as conn:
        cursor = conn.execute(
            """
            UPDATE service_intake_fields SET is_active = 1
            WHERE id = ? AND service_id = ? AND is_active = 0
            """,
            (field_id, service_id),
        )
        if not cursor.rowcount:
            abort(404)
        _audit(
            conn,
            "service_field_reactivated",
            details={"service_id": service_id, "field_id": field_id},
        )
    flash("Booking question reactivated.", "success")
    return redirect(url_for("admin_services", service=service_id))


@app.route("/admin/reminders", methods=["GET", "POST"])
@role_required("admin")
def admin_reminders():
    if request.method == "POST":
        channel = (request.form.get("reminder_channel") or "").lower()
        if channel not in {"email", "sms"}:
            flash("Choose email or SMS reminders.", "error")
        else:
            try:
                with get_db() as conn:
                    branch_id = _validate_branch(conn, request.form.get("branch_id"))
                    conn.execute(
                        "UPDATE branches SET reminder_channel = ? WHERE id = ?",
                        (channel, branch_id),
                    )
                    _audit(
                        conn,
                        "reminder_settings_updated",
                        details={"branch_id": branch_id, "channel": channel},
                    )
                flash("Reminder channel updated for future notifications.", "success")
            except ValueError as exc:
                flash(str(exc), "error")
        return redirect(url_for("admin_reminders"))
    with get_db() as conn:
        branches = [
            dict(row)
            for row in conn.execute(
                """
                SELECT id, name, reminder_channel FROM branches
                WHERE is_active = 1 ORDER BY name
                """
            ).fetchall()
        ]
        queue_stats = {
            row["status"]: row["count"]
            for row in conn.execute(
                """
                SELECT status, count(*) AS count FROM notification_queue
                GROUP BY status
                """
            ).fetchall()
        }
        jobs = [
            dict(row)
            for row in conn.execute(
                """
                SELECT nq.id, nq.channel, nq.event_type, nq.destination,
                       nq.scheduled_for, nq.status, nq.attempts, nq.last_error,
                       nq.sent_at, b.student_name, b.target_date, b.start_time
                FROM notification_queue nq
                JOIN bookings b ON b.id = nq.booking_id
                ORDER BY
                    CASE nq.status
                      WHEN 'failed' THEN 0
                      WHEN 'queued' THEN 1
                      WHEN 'processing' THEN 2
                      ELSE 3
                    END,
                    nq.scheduled_for DESC, nq.id DESC
                LIMIT 100
                """
            ).fetchall()
        ]
    provider_status = {
        "worker_enabled": os.environ.get("A2Z_ENABLE_NOTIFICATIONS", "0") == "1",
        "email_configured": bool(
            os.environ.get("A2Z_SMTP_HOST") and os.environ.get("A2Z_SMTP_FROM")
        ),
        "sms_configured": bool(os.environ.get("A2Z_SMS_WEBHOOK_URL")),
    }
    return render_template(
        "reminders.html",
        branches=branches,
        queue_stats=queue_stats,
        jobs=jobs,
        provider_status=provider_status,
    )


@app.post("/admin/reminders/<int:job_id>/retry")
@role_required("admin")
def admin_reminder_retry(job_id):
    with get_db() as conn:
        cursor = conn.execute(
            """
            UPDATE notification_queue
            SET status = 'queued', attempts = 0, last_error = NULL,
                next_attempt_at = ?, locked_at = NULL
            WHERE id = ? AND status = 'failed'
            """,
            (datetime.now(IST).isoformat(), job_id),
        )
        if not cursor.rowcount:
            abort(404)
        _audit(conn, "notification_retried", details={"notification_id": job_id})
    flash("Notification queued for another delivery attempt.", "success")
    return redirect(url_for("admin_reminders"))


@app.post("/admin/reminders/send-due")
@role_required("admin")
def admin_reminders_send_due():
    from notifications import dispatch_due_notifications

    result = dispatch_due_notifications(limit=25)
    flash(
        f"Delivery run finished: {result['sent']} sent, {result['failed']} need attention.",
        "success" if not result["failed"] else "warning",
    )
    return redirect(url_for("admin_reminders"))


def _availability_context(conn, instructor_id):
    profile = conn.execute(
        """
        SELECT i.*, br.name AS branch_name
        FROM instructors i JOIN branches br ON br.id = i.branch_id
        WHERE i.id = ?
        """,
        (instructor_id,),
    ).fetchone()
    weekly_availability = [
        dict(row)
        for row in conn.execute(
            """
            SELECT * FROM instructor_weekly_availability
            WHERE instructor_id = ? ORDER BY weekday, start_time
            """,
            (instructor_id,),
        ).fetchall()
    ]
    for row in weekly_availability:
        row["day_name"] = DAY_NAMES[row["weekday"]]
    today = datetime.now(IST).date().isoformat()
    time_off = [
        dict(row)
        for row in conn.execute(
            """
            SELECT * FROM instructor_time_off
            WHERE instructor_id = ? AND target_date >= ?
            ORDER BY target_date, start_time
            """,
            (instructor_id, today),
        ).fetchall()
    ]
    return {
        "instructor_profile": dict(profile) if profile else None,
        "weekly_availability": weekly_availability,
        "time_off": time_off,
        "uses_custom_availability": bool(profile["uses_custom_availability"]) if profile else False,
        "work_windows": WORK_WINDOWS,
        "day_names": DAY_NAMES[:6],
        "today": today,
    }


def _availability_target_id(conn):
    """Resolve whose schedule is being edited without widening instructor access."""
    if current_user.role == "instructor":
        if not current_user.instructor_id:
            abort(403)
        return current_user.instructor_id

    try:
        instructor_id = int(
            request.values.get("instructor_id")
            or request.args.get("instructor_id")
            or ""
        )
    except (TypeError, ValueError):
        abort(400, description="Choose an instructor to manage.")
    if not conn.execute(
        "SELECT 1 FROM instructors WHERE id = ?", (instructor_id,)
    ).fetchone():
        abort(404)
    return instructor_id


def _availability_redirect(instructor_id=None):
    if current_user.role == "admin" and instructor_id:
        return redirect(
            url_for("instructor_availability", instructor_id=instructor_id)
        )
    return redirect(url_for("instructor_availability"))


@app.get("/instructor/availability")
@role_required("instructor", "admin")
def instructor_availability():
    with get_db() as conn:
        managed_by_admin = current_user.role == "admin"
        available_instructors = []
        if managed_by_admin:
            available_instructors = [
                dict(row)
                for row in conn.execute(
                    """
                    SELECT i.id, i.name, i.is_active, i.verification_status,
                           br.name AS branch_name
                    FROM instructors i
                    JOIN branches br ON br.id = i.branch_id
                    ORDER BY i.is_active DESC, br.name, lower(i.name)
                    """
                ).fetchall()
            ]
            raw_instructor_id = request.args.get("instructor_id")
            if raw_instructor_id:
                try:
                    instructor_id = int(raw_instructor_id)
                except (TypeError, ValueError):
                    abort(400, description="Choose a valid instructor.")
                if not any(
                    item["id"] == instructor_id for item in available_instructors
                ):
                    abort(404)
            else:
                instructor_id = (
                    available_instructors[0]["id"] if available_instructors else None
                )
        else:
            if not current_user.instructor_id:
                abort(403)
            instructor_id = current_user.instructor_id

        context = _availability_context(conn, instructor_id)
        context.update(
            managed_by_admin=managed_by_admin,
            available_instructors=available_instructors,
            availability_target_id=instructor_id,
        )
    return render_template("instructor_availability.html", **context)


def _availability_overlap(conn, instructor_id, weekday, start_time, end_time, exclude_id=None):
    query = """
        SELECT 1 FROM instructor_weekly_availability
        WHERE instructor_id = ? AND weekday = ?
          AND ? < end_time AND ? > start_time
    """
    params = [instructor_id, weekday, start_time, end_time]
    if exclude_id is not None:
        query += " AND id != ?"
        params.append(exclude_id)
    return bool(conn.execute(query, tuple(params)).fetchone())


@app.post("/instructor/availability/weekly")
@role_required("admin")
def instructor_availability_add():
    instructor_id = None
    try:
        weekday = int(request.form.get("weekday", ""))
        if weekday < 0 or weekday > 5:
            raise ValueError("Choose Monday through Saturday.")
        start_time, end_time = _validate_availability_range(
            request.form.get("start_time"), request.form.get("end_time")
        )
        with get_db() as conn:
            conn.execute("BEGIN IMMEDIATE")
            instructor_id = _availability_target_id(conn)
            if _availability_overlap(
                conn, instructor_id, weekday, start_time, end_time
            ):
                raise ValueError("That time overlaps another availability range.")
            conn.execute(
                """
                INSERT INTO instructor_weekly_availability
                    (instructor_id, weekday, start_time, end_time)
                VALUES (?, ?, ?, ?)
                """,
                (instructor_id, weekday, start_time, end_time),
            )
            conn.execute(
                """
                UPDATE instructors SET uses_custom_availability = 1,
                    updated_at = CURRENT_TIMESTAMP WHERE id = ?
                """,
                (instructor_id,),
            )
            _audit(
                conn,
                "weekly_availability_added",
                details={
                    "instructor_id": instructor_id,
                    "weekday": weekday,
                    "start": start_time,
                    "end": end_time,
                },
            )
        flash("Weekly availability added.", "success")
    except (sqlite3.IntegrityError, TypeError, ValueError) as exc:
        flash(str(exc), "error")
    return _availability_redirect(instructor_id)


@app.post("/instructor/availability/weekly/<int:availability_id>/update")
@role_required("admin")
def instructor_availability_update(availability_id):
    instructor_id = None
    try:
        weekday = int(request.form.get("weekday", ""))
        if weekday < 0 or weekday > 5:
            raise ValueError("Choose Monday through Saturday.")
        start_time, end_time = _validate_availability_range(
            request.form.get("start_time"), request.form.get("end_time")
        )
        with get_db() as conn:
            conn.execute("BEGIN IMMEDIATE")
            instructor_id = _availability_target_id(conn)
            row = conn.execute(
                """
                SELECT id FROM instructor_weekly_availability
                WHERE id = ? AND instructor_id = ?
                """,
                (availability_id, instructor_id),
            ).fetchone()
            if not row:
                abort(404)
            if _availability_overlap(
                conn,
                instructor_id,
                weekday,
                start_time,
                end_time,
                exclude_id=availability_id,
            ):
                raise ValueError("That time overlaps another availability range.")
            conn.execute(
                """
                UPDATE instructor_weekly_availability
                SET weekday = ?, start_time = ?, end_time = ?,
                    updated_at = CURRENT_TIMESTAMP WHERE id = ?
                """,
                (weekday, start_time, end_time, availability_id),
            )
            _audit(
                conn,
                "weekly_availability_updated",
                details={
                    "availability_id": availability_id,
                    "instructor_id": instructor_id,
                },
            )
        flash("Availability updated.", "success")
    except (sqlite3.IntegrityError, TypeError, ValueError) as exc:
        flash(str(exc), "error")
    return _availability_redirect(instructor_id)


@app.post("/instructor/availability/weekly/<int:availability_id>/delete")
@role_required("admin")
def instructor_availability_delete(availability_id):
    with get_db() as conn:
        conn.execute("BEGIN IMMEDIATE")
        instructor_id = _availability_target_id(conn)
        cursor = conn.execute(
            """
            DELETE FROM instructor_weekly_availability
            WHERE id = ? AND instructor_id = ?
            """,
            (availability_id, instructor_id),
        )
        if not cursor.rowcount:
            abort(404)
        _audit(
            conn,
            "weekly_availability_removed",
            details={
                "availability_id": availability_id,
                "instructor_id": instructor_id,
            },
        )
    flash("Availability range removed. That time is now unavailable.", "success")
    return _availability_redirect(instructor_id)


@app.post("/instructor/availability/reset")
@role_required("admin")
def instructor_availability_reset():
    with get_db() as conn:
        conn.execute("BEGIN IMMEDIATE")
        instructor_id = _availability_target_id(conn)
        conn.execute(
            "DELETE FROM instructor_weekly_availability WHERE instructor_id = ?",
            (instructor_id,),
        )
        conn.execute(
            """
            UPDATE instructors SET uses_custom_availability = 0,
                updated_at = CURRENT_TIMESTAMP WHERE id = ?
            """,
            (instructor_id,),
        )
        _audit(
            conn,
            "weekly_availability_reset",
            details={"instructor_id": instructor_id},
        )
    flash("Institute hours restored for every open day.", "success")
    return _availability_redirect(instructor_id)


@app.post("/instructor/time-off")
@role_required("admin")
def instructor_time_off_add():
    instructor_id = None
    try:
        target = date.fromisoformat(request.form.get("target_date") or "")
        today = datetime.now(IST).date()
        if target < today:
            raise ValueError("Time off cannot be added in the past.")
        if target > today + timedelta(days=365):
            raise ValueError("Time off can be planned up to one year ahead.")
        all_day = request.form.get("all_day") == "1"
        if all_day:
            start_time, end_time = "00:00", "23:59"
            start_minutes, end_minutes = 0, (24 * 60) - 1
        else:
            start_time, end_time = _validate_availability_range(
                request.form.get("start_time"), request.form.get("end_time"), within_hours=False
            )
            start_minutes = _time_to_minutes(start_time)
            end_minutes = _time_to_minutes(end_time)
        reason = " ".join((request.form.get("reason") or "").split())[:160]
        with get_db() as conn:
            conn.execute("BEGIN IMMEDIATE")
            instructor_id = _availability_target_id(conn)
            _assert_busy_time_available(
                conn,
                instructor_id,
                target,
                start_minutes,
                end_minutes,
            )
            conn.execute(
                """
                INSERT INTO instructor_time_off
                    (instructor_id, target_date, start_time, end_time, reason)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    instructor_id,
                    target.isoformat(),
                    start_time,
                    end_time,
                    reason or None,
                ),
            )
            _audit(
                conn,
                "time_off_added",
                details={
                    "instructor_id": instructor_id,
                    "target_date": target.isoformat(),
                    "start": start_time,
                    "end": end_time,
                },
            )
        flash("Time off added to the instructor's availability.", "success")
    except (TypeError, ValueError) as exc:
        flash(str(exc), "error")
    return _availability_redirect(instructor_id)


@app.post("/instructor/time-off/<int:time_off_id>/delete")
@role_required("admin")
def instructor_time_off_delete(time_off_id):
    with get_db() as conn:
        conn.execute("BEGIN IMMEDIATE")
        instructor_id = _availability_target_id(conn)
        cursor = conn.execute(
            "DELETE FROM instructor_time_off WHERE id = ? AND instructor_id = ?",
            (time_off_id, instructor_id),
        )
        if not cursor.rowcount:
            abort(404)
        _audit(
            conn,
            "time_off_removed",
            details={"time_off_id": time_off_id, "instructor_id": instructor_id},
        )
    flash("Time off removed.", "success")
    return _availability_redirect(instructor_id)


def _approval_conflict(conn, booking):
    existing_rows = conn.execute(
        """
        SELECT machine_id, instructor_id, student_user_id, student_name,
               target_date AS date, start_time, end_time,
               buffer_before_minutes, buffer_after_minutes
        FROM bookings
        WHERE id != ? AND target_date = ? AND validation_status = 'Approved'
        """,
        (booking["id"], booking["target_date"]),
    ).fetchall()
    new_start = _time_to_minutes(booking["start_time"])
    new_end = _time_to_minutes(booking["end_time"])
    new_reserved_start = new_start - int(booking["buffer_before_minutes"] or 0)
    new_reserved_end = new_end + int(booking["buffer_after_minutes"] or 0)
    for existing in existing_rows:
        existing_start = _time_to_minutes(existing["start_time"])
        existing_end = _time_to_minutes(existing["end_time"])
        same_student = (
            booking["student_user_id"] is not None
            and existing["student_user_id"] == booking["student_user_id"]
        )
        if same_student and new_start < existing_end and new_end > existing_start:
            return True, "REJECTED - Student conflict with existing booking"
        same_machine = existing["machine_id"] == booking["machine_id"]
        same_instructor = existing["instructor_id"] == booking["instructor_id"]
        if not (same_machine or same_instructor):
            continue
        existing_reserved_start = existing_start - int(
            existing["buffer_before_minutes"] or 0
        )
        existing_reserved_end = existing_end + int(
            existing["buffer_after_minutes"] or 0
        )
        if (
            new_reserved_start < existing_reserved_end
            and new_reserved_end > existing_reserved_start
        ):
            resource = "Machine" if same_machine else "Instructor"
            return True, f"REJECTED - {resource} conflict with existing booking"
    return False, "APPROVED"


def _approval_invalid_reason(conn, booking):
    """Return why a pending request is no longer operationally valid."""
    if not booking["student_user_id"]:
        return "the request is not linked to a managed student account"
    relationship = conn.execute(
        """
        SELECT 1
        FROM users s
        JOIN instructors i ON i.id = ?
        JOIN machines m ON m.id = ?
        JOIN student_instructor_assignments a
          ON a.student_user_id = s.id AND a.instructor_id = i.id
        WHERE s.id = ? AND s.role = 'student' AND s.is_active = 1
          AND i.is_active = 1 AND i.verification_status = 'verified'
          AND m.is_active = 1 AND a.is_active = 1
          AND s.branch_id = ? AND i.branch_id = ? AND m.branch_id = ?
        """,
        (
            booking["instructor_id"],
            booking["machine_id"],
            booking["student_user_id"],
            booking["branch_id"],
            booking["branch_id"],
            booking["branch_id"],
        ),
    ).fetchone()
    if not relationship:
        return "the student, verified instructor, equipment or assignment is no longer active"
    try:
        target = date.fromisoformat(booking["target_date"])
    except (TypeError, ValueError):
        return "the training date is invalid"
    today = datetime.now(IST).date()
    if target < today:
        return "the requested session is in the past"
    start_minutes = _time_to_minutes(booking["start_time"])
    end_minutes = _time_to_minutes(booking["end_time"])
    reserved_start = start_minutes - int(booking["buffer_before_minutes"] or 0)
    reserved_end = end_minutes + int(booking["buffer_after_minutes"] or 0)
    if target == today:
        now = datetime.now(IST)
        start_at = datetime.combine(
            target, datetime.strptime(booking["start_time"], "%H:%M").time(), IST
        )
        if start_at <= now:
            return "the requested start time has already passed"
    windows = _instructor_work_windows(conn, booking["instructor_id"], target)
    if not any(
        reserved_start >= _time_to_minutes(window_start)
        and reserved_end <= _time_to_minutes(window_end)
        for window_start, window_end in windows
    ):
        return "the instructor is no longer available during that time"
    leave_rows = conn.execute(
        """
        SELECT start_time, end_time FROM instructor_time_off
        WHERE instructor_id = ? AND target_date = ?
        """,
        (booking["instructor_id"], booking["target_date"]),
    ).fetchall()
    if any(
        reserved_start < _time_to_minutes(leave["end_time"])
        and reserved_end > _time_to_minutes(leave["start_time"])
        for leave in leave_rows
    ):
        return "the instructor has recorded time off during that session"
    return None


@app.post("/bookings/<int:booking_id>/decision")
@role_required("admin")
def booking_decision(booking_id):
    decision = (request.form.get("decision") or "").strip().lower()
    review_notes = " ".join((request.form.get("review_notes") or "").split())
    status_map = {
        "approve": "Approved",
        "approved": "Approved",
        "reject": "Rejected",
        "rejected": "Rejected",
    }
    next_status = status_map.get(decision)
    if not next_status:
        abort(400, description="Choose approve or decline.")
    if len(review_notes) > 500:
        flash("Keep the review note under 500 characters.", "error")
        return redirect(_role_home())
    if next_status == "Rejected" and not review_notes:
        flash("Add a short reason so the student knows what to change.", "warning")
        return redirect(_role_home())

    try:
        with get_db() as conn:
            conn.execute("BEGIN IMMEDIATE")
            booking = conn.execute("SELECT * FROM bookings WHERE id = ?", (booking_id,)).fetchone()
            if not booking:
                abort(404)
            if current_user.role == "instructor" and booking["instructor_id"] != current_user.instructor_id:
                abort(403)
            if booking["validation_status"] != "Pending":
                flash("Another user has already reviewed this request.", "warning")
                return redirect(_role_home())
            if next_status == "Approved":
                invalid_reason = _approval_invalid_reason(conn, booking)
                if invalid_reason:
                    flash(f"This request cannot be approved because {invalid_reason}.", "error")
                    return redirect(_role_home())
                conflict, reason = _approval_conflict(conn, booking)
                if conflict:
                    flash(f"This request now conflicts with the live schedule: {reason}.", "error")
                    return redirect(_role_home())
            conn.execute(
                """
                UPDATE bookings SET validation_status = ?, review_notes = ?,
                    reviewed_by = ?, reviewed_at = CURRENT_TIMESTAMP,
                    calendar_revision = calendar_revision + 1,
                    updated_at = CURRENT_TIMESTAMP WHERE id = ?
                """,
                (next_status, review_notes or None, current_user.id, booking_id),
            )
            _audit(
                conn,
                "booking_approved" if next_status == "Approved" else "booking_rejected",
                booking_id,
                {"review_notes": review_notes},
            )
            _queue_booking_notifications(
                conn,
                booking_id,
                "appointment_approved"
                if next_status == "Approved"
                else "appointment_rejected",
            )
        flash(
            "Booking approved and added to the schedule."
            if next_status == "Approved"
            else "Request declined. The student can see your reason.",
            "success",
        )
    except sqlite3.IntegrityError:
        flash("The slot now conflicts with another approved booking.", "error")
    return redirect(_role_home())


@app.post("/bookings/<int:booking_id>/attendance")
@role_required("admin")
def booking_attendance(booking_id):
    status = (request.form.get("status") or "").strip().lower()
    status_map = {"completed": "Completed", "no-show": "No-show"}
    next_status = status_map.get(status)
    if not next_status:
        abort(400, description="Choose completed or no-show.")
    now = datetime.now(IST)
    today = now.date().isoformat()
    with get_db() as conn:
        conn.execute("BEGIN IMMEDIATE")
        booking = conn.execute("SELECT * FROM bookings WHERE id = ?", (booking_id,)).fetchone()
        if not booking:
            abort(404)
        if current_user.role == "instructor" and booking["instructor_id"] != current_user.instructor_id:
            abort(403)
        if booking["validation_status"] != "Approved" or booking["target_date"] > today:
            flash("Attendance can only be recorded for an approved session on or before today.", "warning")
            return redirect(_role_home())
        if booking["target_date"] == today:
            session_end = datetime.combine(
                now.date(), datetime.strptime(booking["end_time"], "%H:%M").time(), IST
            )
            if session_end > now:
                flash("Attendance can be recorded after the scheduled session has ended.", "warning")
                return redirect(_role_home())
        conn.execute(
            """
            UPDATE bookings SET validation_status = ?, attendance_recorded_by = ?,
                attendance_recorded_at = CURRENT_TIMESTAMP,
                calendar_revision = calendar_revision + 1,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (next_status, current_user.id, booking_id),
        )
        _cancel_queued_booking_notifications(conn, booking_id)
        _audit(conn, "attendance_recorded", booking_id, {"status": next_status})
    flash(f"Attendance recorded as {next_status.lower()}.", "success")
    return redirect(_role_home())


@app.get("/admin")
@role_required("admin")
def admin_dashboard():
    now = datetime.now(IST)
    today = now.date().isoformat()
    current_time = now.strftime("%H:%M")
    selected_status = (request.args.get("status") or "").strip().lower()
    selected_branch = request.args.get("branch", "")
    selected_date = request.args.get("date", "")
    search_query = " ".join((request.args.get("q") or "").split())[:100]
    clauses = []
    params = []
    status_values = {
        "pending": "Pending",
        "approved": "Approved",
        "rejected": "Rejected",
        "cancelled": "Cancelled",
        "completed": "Completed",
        "no-show": "No-show",
    }
    if selected_status in status_values:
        clauses.append("b.validation_status = ?")
        params.append(status_values[selected_status])
    else:
        selected_status = ""
    if selected_branch:
        try:
            branch_id = int(selected_branch)
            clauses.append("b.branch_id = ?")
            params.append(branch_id)
        except ValueError:
            selected_branch = ""
    if selected_date:
        try:
            date.fromisoformat(selected_date)
            clauses.append("b.target_date = ?")
            params.append(selected_date)
        except ValueError:
            selected_date = ""
    if search_query:
        clauses.append(
            "(lower(b.student_name) LIKE lower(?) OR lower(m.machine_code) LIKE lower(?) "
            "OR lower(i.name) LIKE lower(?))"
        )
        search_pattern = f"%{search_query}%"
        params.extend((search_pattern, search_pattern, search_pattern))

    with get_db() as conn:
        bookings = _booking_rows(
            conn,
            " AND ".join(clauses),
            params,
            "b.target_date DESC, b.start_time DESC, b.created_at DESC",
        )
        branches = [
            dict(row)
            for row in conn.execute("SELECT id, name FROM branches ORDER BY name").fetchall()
        ]
        stats = {
            "pending": conn.execute(
                "SELECT count(*) FROM bookings WHERE validation_status = 'Pending'"
            ).fetchone()[0],
            "today": conn.execute(
                "SELECT count(*) FROM bookings WHERE validation_status = 'Approved' AND target_date = ?",
                (today,),
            ).fetchone()[0],
            "students": conn.execute(
                "SELECT count(*) FROM users WHERE role = 'student' AND is_active = 1"
            ).fetchone()[0],
            "active_resources": conn.execute(
                "SELECT count(*) FROM machines WHERE is_active = 1"
            ).fetchone()[0],
            "active_users": conn.execute(
                "SELECT count(*) FROM users WHERE is_active = 1"
            ).fetchone()[0],
            "unverified_instructors": conn.execute(
                """
                SELECT count(*) FROM instructors
                WHERE is_active = 1 AND verification_status = 'unverified'
                """
            ).fetchone()[0],
        }
        recent_events = [
            dict(row)
            for row in conn.execute(
                """
                SELECT ae.event_type, ae.created_at, ae.booking_id,
                       COALESCE(u.full_name, u.username, 'System') AS actor_name,
                       b.student_name
                FROM audit_events ae
                LEFT JOIN users u ON u.id = ae.actor_user_id
                LEFT JOIN bookings b ON b.id = ae.booking_id
                ORDER BY ae.created_at DESC, ae.id DESC LIMIT 10
                """
            ).fetchall()
        ]
    return render_template(
        "admin_dashboard.html",
        bookings=bookings,
        stats=stats,
        branches=branches,
        filters={
            "status": selected_status,
            "branch": selected_branch,
            "date": selected_date,
            "q": search_query,
        },
        recent_events=recent_events,
        today=today,
        current_time=current_time,
    )


@app.get("/health")
def health():
    try:
        with get_db() as conn:
            result = conn.execute("PRAGMA quick_check(1)").fetchone()[0]
            if result != "ok":
                raise sqlite3.DatabaseError(result)
        return jsonify({"status": "ok"})
    except sqlite3.Error:
        return jsonify({"status": "unavailable"}), 503


@app.errorhandler(400)
@app.errorhandler(403)
@app.errorhandler(404)
@app.errorhandler(500)
def render_error(error):
    status = getattr(error, "code", 500) or 500
    messages = {
        400: ("We could not complete that request", getattr(error, "description", "Check the details and try again.")),
        403: ("This area is not available to your account", "Return to your dashboard or sign in with the correct role."),
        404: ("We could not find that page", "The link may be old, or the page may have moved."),
        500: ("Something went wrong", "Your data is safe. Please try again in a moment."),
    }
    title, message = messages.get(status, messages[500])
    if request.path.startswith("/api/"):
        return jsonify({"error": message}), status
    return render_template("error.html", status=status, title=title, message=message), status


def initialise_application():
    init_db()
    if os.environ.get("A2Z_SEED_REFERENCE_DATA", "1") == "1":
        seed_reference_data()


initialise_application()


if __name__ == "__main__":
    host = os.environ.get("A2Z_HOST", "127.0.0.1")
    port = int(os.environ.get("PORT", "5000"))
    app.run(host=host, port=port, debug=os.environ.get("A2Z_DEBUG", "0") == "1")
