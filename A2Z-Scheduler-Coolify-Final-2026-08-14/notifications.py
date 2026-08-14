"""Durable email/SMS delivery for A2Z appointment notifications."""

from __future__ import annotations

import json
import os
import smtplib
import ssl
import threading
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from database import get_db


IST = timezone(timedelta(hours=5, minutes=30))


def _notification_copy(row):
    labels = {
        "booking_requested": "Booking request received",
        "appointment_approved": "Appointment confirmed",
        "appointment_rejected": "Appointment request declined",
        "appointment_cancelled": "Appointment cancelled",
        "appointment_rescheduled": "Appointment rescheduled",
        "reminder_24h": "Appointment reminder",
        "reminder_2h": "Appointment reminder",
    }
    subject = labels.get(row["event_type"], "A2Z appointment update")
    service = row["service_name"] or row["machine_category"] or "Practical training"
    lines = [
        f"Hello {row['student_name']},",
        "",
        subject + ".",
        f"Service: {service}",
        f"Date: {row['target_date']}",
        f"Time: {row['start_time']}–{row['end_time']} (India Standard Time)",
        f"Instructor: {row['instructor_name']}",
        f"Equipment: {row['machine_code']}",
        "",
        "A2Z Institute",
    ]
    return subject, "\n".join(lines)


def _send_email(destination, subject, body):
    host = (os.environ.get("A2Z_SMTP_HOST") or "").strip()
    sender = (os.environ.get("A2Z_SMTP_FROM") or "").strip()
    if not host or not sender:
        raise RuntimeError("Email provider is not configured.")
    port = int(os.environ.get("A2Z_SMTP_PORT", "587"))
    username = os.environ.get("A2Z_SMTP_USERNAME") or ""
    password = os.environ.get("A2Z_SMTP_PASSWORD") or ""
    mode = (os.environ.get("A2Z_SMTP_SECURITY") or "starttls").lower()
    message = EmailMessage()
    message["From"] = sender
    message["To"] = destination
    message["Subject"] = subject
    message.set_content(body)
    if mode == "ssl":
        client = smtplib.SMTP_SSL(host, port, timeout=20, context=ssl.create_default_context())
    else:
        client = smtplib.SMTP(host, port, timeout=20)
    with client:
        if mode == "starttls":
            client.starttls(context=ssl.create_default_context())
        if username:
            client.login(username, password)
        client.send_message(message)


def _send_sms(destination, _subject, body):
    webhook = (os.environ.get("A2Z_SMS_WEBHOOK_URL") or "").strip()
    if not webhook:
        raise RuntimeError("SMS provider is not configured.")
    parsed = urlsplit(webhook)
    local_http = parsed.scheme == "http" and parsed.hostname in {"127.0.0.1", "localhost"}
    if parsed.scheme != "https" and not local_http:
        raise RuntimeError("The SMS webhook must use HTTPS.")
    payload = json.dumps({"to": destination, "message": body}).encode("utf-8")
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    token = (os.environ.get("A2Z_SMS_WEBHOOK_TOKEN") or "").strip()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = Request(webhook, data=payload, headers=headers, method="POST")
    with urlopen(request, timeout=20) as response:
        if response.status < 200 or response.status >= 300:
            raise RuntimeError(f"SMS provider returned status {response.status}.")


def _claim_due_job():
    now = datetime.now(IST)
    with get_db() as conn:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            """
            UPDATE notification_queue
            SET status = 'queued', locked_at = NULL,
                last_error = COALESCE(last_error, 'Recovered after worker restart')
            WHERE status = 'processing' AND locked_at < ?
            """,
            ((now - timedelta(minutes=10)).isoformat(),),
        )
        row = conn.execute(
            """
            SELECT nq.id
            FROM notification_queue nq
            WHERE nq.status = 'queued'
              AND COALESCE(nq.next_attempt_at, nq.scheduled_for) <= ?
            ORDER BY COALESCE(nq.next_attempt_at, nq.scheduled_for), nq.id
            LIMIT 1
            """,
            (now.isoformat(),),
        ).fetchone()
        if not row:
            return None
        cursor = conn.execute(
            """
            UPDATE notification_queue
            SET status = 'processing', attempts = attempts + 1, locked_at = ?
            WHERE id = ? AND status = 'queued'
            """,
            (now.isoformat(), row["id"]),
        )
        return row["id"] if cursor.rowcount else None


def _load_job(job_id):
    with get_db() as conn:
        return conn.execute(
            """
            SELECT nq.*, b.student_name, b.target_date, b.start_time, b.end_time,
                   b.validation_status,
                   COALESCE(cp.reminders_enabled, 1) AS reminders_enabled,
                   COALESCE(NULLIF(b.service_name, ''), s.name, m.category)
                       AS service_name,
                   m.machine_code, m.category AS machine_category,
                   i.name AS instructor_name
            FROM notification_queue nq
            JOIN bookings b ON b.id = nq.booking_id
            JOIN machines m ON m.id = b.machine_id
            JOIN instructors i ON i.id = b.instructor_id
            LEFT JOIN services s ON s.id = b.service_id
            LEFT JOIN client_profiles cp ON cp.user_id = b.student_user_id
            WHERE nq.id = ? AND nq.status = 'processing'
            """,
            (job_id,),
        ).fetchone()


def _cancel_job(job_id):
    with get_db() as conn:
        conn.execute(
            """
            UPDATE notification_queue
            SET status = 'cancelled', locked_at = NULL, next_attempt_at = NULL
            WHERE id = ? AND status = 'processing'
            """,
            (job_id,),
        )


def _finish_job(job_id, error=None):
    now = datetime.now(IST)
    with get_db() as conn:
        if error is None:
            conn.execute(
                """
                UPDATE notification_queue
                SET status = 'sent', sent_at = ?, locked_at = NULL,
                    next_attempt_at = NULL, last_error = NULL
                WHERE id = ? AND status = 'processing'
                """,
                (now.isoformat(), job_id),
            )
            return
        row = conn.execute(
            "SELECT attempts FROM notification_queue WHERE id = ?", (job_id,)
        ).fetchone()
        attempts = int(row["attempts"] if row else 5)
        retry_at = now + timedelta(minutes=min(60, 2 ** attempts))
        conn.execute(
            """
            UPDATE notification_queue
            SET status = ?, last_error = ?, locked_at = NULL,
                next_attempt_at = ?
            WHERE id = ? AND status = 'processing'
            """,
            (
                "failed" if attempts >= 5 else "queued",
                str(error)[:500],
                None if attempts >= 5 else retry_at.isoformat(),
                job_id,
            ),
        )


def dispatch_due_notifications(limit=20):
    """Deliver up to ``limit`` due jobs and return summary counts."""
    sent = 0
    failed = 0
    for _ in range(max(1, min(int(limit), 100))):
        job_id = _claim_due_job()
        if job_id is None:
            break
        row = _load_job(job_id)
        if not row:
            _finish_job(job_id, "Notification job could not be loaded.")
            failed += 1
            continue
        if row["event_type"].startswith("reminder_") and (
            not row["reminders_enabled"]
            or row["validation_status"] != "Approved"
        ):
            _cancel_job(job_id)
            continue
        subject, body = _notification_copy(row)
        try:
            if row["channel"] == "email":
                _send_email(row["destination"], subject, body)
            elif row["channel"] == "sms":
                _send_sms(row["destination"], subject, body)
            else:
                raise RuntimeError("Unsupported notification channel.")
            _finish_job(job_id)
            sent += 1
        except Exception as exc:  # Provider failures are retained for review.
            _finish_job(job_id, exc)
            failed += 1
    return {"sent": sent, "failed": failed}


def run_notification_worker(stop_event=None, interval_seconds=30):
    """Run the durable outbox loop until ``stop_event`` is set."""
    stop_event = stop_event or threading.Event()
    while not stop_event.is_set():
        dispatch_due_notifications()
        stop_event.wait(max(10, int(interval_seconds)))
