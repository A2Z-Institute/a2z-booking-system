"""Read candidate rows from the text-based SRTO DL test register PDF."""

from __future__ import annotations

import io
import re
from datetime import datetime
from pathlib import Path

import pdfplumber


class DrivingTestPdfError(ValueError):
    """Raised when an uploaded PDF is not a supported candidate register."""


def _iso_date(value: str, label: str) -> str:
    try:
        return datetime.strptime(value.strip(), "%d/%m/%Y").date().isoformat()
    except (TypeError, ValueError):
        raise DrivingTestPdfError(f"The PDF contains an invalid {label}: {value!r}.") from None


def _clean_classes(value: str) -> str:
    parts = [
        part.strip().upper()
        for part in re.split(r"[,\n]+", str(value or ""))
        if part.strip()
    ]
    return ", ".join(dict.fromkeys(parts))


def parse_driving_test_pdf(content: bytes, filename: str) -> dict:
    """Return the SRTO header and candidate rows from a PDF byte string."""
    if Path(filename or "").suffix.lower() != ".pdf":
        raise DrivingTestPdfError("Upload a PDF test form.")
    if not content:
        raise DrivingTestPdfError("The uploaded PDF is empty.")

    try:
        pdf = pdfplumber.open(io.BytesIO(content))
    except Exception as exc:
        raise DrivingTestPdfError("The uploaded file could not be opened as a PDF.") from exc

    rows = []
    header_text = ""
    try:
        for page_number, page in enumerate(pdf.pages, 1):
            page_text = page.extract_text() or ""
            if page_number == 1:
                header_text = page_text
            for table in page.extract_tables() or []:
                for cells in table:
                    if len(cells) < 7:
                        continue
                    serial_text = str(cells[0] or "").strip()
                    if not serial_text.isdigit():
                        continue
                    application_lines = [
                        line.strip() for line in str(cells[1] or "").splitlines() if line.strip()
                    ]
                    applicant_lines = [
                        line.strip() for line in str(cells[2] or "").splitlines() if line.strip()
                    ]
                    if len(application_lines) < 2 or len(applicant_lines) < 2:
                        raise DrivingTestPdfError(
                            f"Candidate row {serial_text} is incomplete on page {page_number}."
                        )
                    application_number = re.sub(r"\D", "", application_lines[0])
                    appointment_match = next(
                        (
                            line
                            for line in application_lines[1:]
                            if re.fullmatch(r"\d{1,2}/\d{1,2}/\d{4}", line)
                        ),
                        None,
                    )
                    phone = re.sub(r"\D", "", applicant_lines[-1])
                    name = " ".join(applicant_lines[:-1]).strip()
                    if not application_number or not appointment_match or len(phone) < 8 or not name:
                        raise DrivingTestPdfError(
                            f"Candidate row {serial_text} could not be read safely on page {page_number}."
                        )
                    classes = _clean_classes(cells[3])
                    if not classes:
                        raise DrivingTestPdfError(
                            f"Candidate row {serial_text} has no licence class."
                        )
                    result = "Pending"
                    for column, status in ((4, "Passed"), (5, "Failed"), (6, "Absent")):
                        if str(cells[column] or "").strip():
                            result = status
                            break
                    rows.append(
                        {
                            "serial_number": int(serial_text),
                            "application_number": application_number,
                            "appointment_date": _iso_date(appointment_match, "appointment date"),
                            "candidate_name": " ".join(name.split()),
                            "phone": phone,
                            "course_name": classes,
                            "result_status": result,
                            "source_page": page_number,
                        }
                    )
    finally:
        pdf.close()

    test_date_match = re.search(
        r"(?:DL\s+Test\s+on|Test\s+on)\s*(\d{2}/\d{2}/\d{4})",
        header_text,
        re.IGNORECASE,
    )
    if not test_date_match:
        raise DrivingTestPdfError("The DL test date was not found in the PDF heading.")
    location_match = re.search(r"^\s*(SRTO[^\n]+)", header_text, re.IGNORECASE | re.MULTILINE)
    if not rows:
        raise DrivingTestPdfError(
            "No candidate table was found. Upload the original text-based SRTO PDF, not a photo."
        )
    serials = [item["serial_number"] for item in rows]
    if len(serials) != len(set(serials)):
        raise DrivingTestPdfError("The PDF contains duplicate candidate serial numbers.")
    rows.sort(key=lambda item: item["serial_number"])
    return {
        "test_date": _iso_date(test_date_match.group(1), "test date"),
        "test_location": " ".join((location_match.group(1) if location_match else "SRTO").split()),
        "rows": rows,
    }
