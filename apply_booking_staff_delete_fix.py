from pathlib import Path
import shutil
import re
import sys

ROOT = Path(__file__).resolve().parent
APP = ROOT / "app.py"

if not APP.exists():
    print("ERROR: Put this script in the root folder of your A2Z booking software, next to app.py.")
    sys.exit(1)

text = APP.read_text(encoding="utf-8")
old = '"can_edit": current_user.role == "admin",'
new = '"can_edit": current_user.role == "admin" or current_user.has_permission("write_access"),'

# Find the appointment calendar-event function/block and change ONLY that block.
positions = [m.start() for m in re.finditer(re.escape(old), text)]
if not positions:
    print("ERROR: The expected calendar can_edit line was not found.")
    print("No files were changed.")
    sys.exit(1)

def block_start(pos):
    # Find the nearest preceding top-level function definition.
    matches = list(re.finditer(r'(?m)^def\s+([A-Za-z0-9_]+)\s*\(', text[:pos]))
    return matches[-1].start() if matches else 0

changed = False
for pos in positions:
    start = block_start(pos)
    next_def = re.search(r'(?m)^def\s+[A-Za-z0-9_]+\s*\(', text[pos + len(old):])
    end = pos + len(old) + (next_def.start() if next_def else 1000000)
    block = text[start:end]

    # Appointment event blocks normally contain booking/client/service fields.
    appointment_markers = (
        '"student_id"',
        '"service_ids"',
        '"client_name"',
        '"booking_id"',
        '"machine_id"',
    )
    if any(marker in block for marker in appointment_markers):
        text = text[:pos] + new + text[pos + len(old):]
        changed = True
        break

if not changed:
    print("ERROR: Found the can_edit line, but could not safely identify the appointment event block.")
    print("No files were changed.")
    sys.exit(1)

backup = APP.with_suffix(".py.booking_staff_delete_backup")
if not backup.exists():
    shutil.copy2(APP, backup)

APP.write_text(text, encoding="utf-8")
print("SUCCESS: Booking staff can now delete/cancel active appointments from the calendar.")
print("Backup created:", backup.name)
print("Admin permanent-delete permissions are unchanged.")
