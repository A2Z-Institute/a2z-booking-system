"""Privacy-preserving OpenAI chatbot for anonymous booking statistics."""

from __future__ import annotations

import json
import os
import re
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class OpenAIBookingChatError(RuntimeError):
    """Raised when the booking chatbot cannot answer safely."""


def openai_chat_configured() -> bool:
    return bool((os.environ.get("A2Z_OPENAI_API_KEY") or "").strip())


def _anonymous_statistics(aggregate_data: dict) -> dict:
    safe = json.loads(json.dumps(aggregate_data))
    safe["instructors"] = [
        {"name": f"Instructor {index}", "bookings": item.get("bookings", 0)}
        for index, item in enumerate(safe.get("instructors", []), start=1)
    ]
    return safe


def _output_text(payload: dict) -> str:
    texts = []
    for item in payload.get("output", []):
        if not isinstance(item, dict) or item.get("type") != "message":
            continue
        for content in item.get("content", []):
            if isinstance(content, dict) and content.get("type") == "output_text":
                texts.append(str(content.get("text") or ""))
    return "\n".join(texts).strip()


def generate_openai_booking_chat(aggregate_data: dict, question: str, history: list) -> str:
    question = " ".join(str(question or "").split())
    if not question or len(question) > 500:
        raise OpenAIBookingChatError("Enter a question of 500 characters or fewer.")
    compact_digits = re.sub(r"[\s()+-]", "", question)
    if re.search(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", question) or re.search(
        r"(?<!\d)\d{8,}(?!\d)", compact_digits
    ):
        raise OpenAIBookingChatError(
            "Do not include phone numbers, email addresses, or admission numbers."
        )
    api_key = (os.environ.get("A2Z_OPENAI_API_KEY") or "").strip()
    if not api_key:
        raise OpenAIBookingChatError(
            "OpenAI is not configured. Add A2Z_OPENAI_API_KEY in Coolify."
        )
    safe_history = []
    for item in (history or [])[-6:]:
        if not isinstance(item, dict) or item.get("role") not in {"user", "assistant"}:
            continue
        content = " ".join(str(item.get("content") or "").split())[:800]
        history_digits = re.sub(r"[\s()+-]", "", content)
        contains_identifier = re.search(
            r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", content
        ) or re.search(r"(?<!\d)\d{8,}(?!\d)", history_digits)
        if content and not contains_identifier:
            safe_history.append({"role": item["role"], "content": content})
    model = (os.environ.get("A2Z_OPENAI_MODEL") or "gpt-5.4-mini").strip()
    prompt = (
        "Anonymous booking statistics:\n"
        + json.dumps(_anonymous_statistics(aggregate_data), ensure_ascii=False, separators=(",", ":"))
        + "\n\nRecent browser-session conversation:\n"
        + json.dumps(safe_history, ensure_ascii=False, separators=(",", ":"))
        + "\n\nManagement question:\n"
        + question
    )
    body = json.dumps(
        {
            "model": model,
            "instructions": (
                "You are the read-only A2Z Booking Insights assistant. Answer only "
                "from the supplied anonymous statistics. Be concise and cite relevant "
                "numbers. If the statistics cannot answer, say so. Never request, infer, "
                "or reveal personal data, and never claim to change a booking."
            ),
            "input": prompt,
            "max_output_tokens": 900,
        }
    ).encode("utf-8")
    request = Request(
        "https://api.openai.com/v1/responses",
        data=body,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=35) as response:
            payload = json.load(response)
    except HTTPError as exc:
        try:
            provider_error = json.loads(exc.read().decode("utf-8"))["error"]["message"]
        except Exception:
            provider_error = f"OpenAI returned HTTP {exc.code}."
        raise OpenAIBookingChatError(provider_error[:300]) from None
    except (URLError, TimeoutError, OSError):
        raise OpenAIBookingChatError(
            "OpenAI could not be reached. Please try again shortly."
        ) from None
    answer = _output_text(payload)
    if not answer:
        raise OpenAIBookingChatError("OpenAI returned an empty answer. Try again.")
    return answer[:4000]
