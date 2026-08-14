"""WSGI entry point for Waitress and managed hosting platforms."""

import os
import threading

from dotenv import load_dotenv


# Load deployment settings before app.py initialises the database and seed data.
load_dotenv()

from app import app  # noqa: E402


if os.environ.get("A2Z_ENABLE_NOTIFICATIONS", "0") == "1":
    from notifications import run_notification_worker  # noqa: E402

    threading.Thread(
        target=run_notification_worker,
        name="a2z-notification-worker",
        daemon=True,
    ).start()


# Some WSGI platforms look for ``application`` instead of ``app``.
application = app


if __name__ == "__main__":
    app.run(
        host=os.environ.get("A2Z_HOST", "127.0.0.1"),
        port=int(os.environ.get("PORT", "5000")),
        debug=os.environ.get("A2Z_DEBUG", "0") == "1",
    )
