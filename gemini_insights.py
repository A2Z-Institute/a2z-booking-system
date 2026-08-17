"""Privacy-preserving Gemini analysis for aggregate booking statistics."""

from __future__ import annotations

import json
import os
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen


class GeminiInsightsError(RuntimeError):
    """Raised when Gemini configuration or delivery fails safely."""


def gemini_configured() -> bool:
    return bool((os.environ.get("A2Z_GEMINI_API_KEY") or "").strip())


def _response_schema():
    return {
        "type": "OBJECT",
        "properties": {
            "executive_summary": {"type": "STRING"},
            "recommendations": {
                "type": "ARRAY",
                "items": {
                    "type": "OBJECT",
                    "properties": {
                        "title": {"type": "STRING"},
                        "reason": {"type": "STRING"},
                        "action": {"type": "STRING"},
                        "priority": {
                            "type": "STRING",
                            "enum": ["High", "Medium", "Low"],
                        },
                    },
                    "required": ["title", "reason", "action", "priority"],
                },
            },
            "observations": {
                "type": "ARRAY",
                "items": {"type": "STRING"},
            },
        },
        "required": ["executive_summary", "recommendations", "observations"],
    }


def generate_booking_insights(aggregate_data: dict) -> dict:
    """Send anonymous aggregate counts to Gemini and return validated JSON."""
    api_key = (os.environ.get("A2Z_GEMINI_API_KEY") or "").strip()
    if not api_key:
        raise GeminiInsightsError(
            "Gemini is not configured. Add A2Z_GEMINI_API_KEY in Coolify."
        )
    model = (os.environ.get("A2Z_GEMINI_MODEL") or "gemini-2.5-flash").strip()
    endpoint = (
        "https://generativelanguage.googleapis.com/v1beta/models/"
        f"{quote(model, safe='')}:generateContent"
    )
    prompt = (
        "You are an operations analyst for an Indian heavy-equipment training "
        "institute. Analyse only the anonymous aggregate booking statistics below. "
        "Do not infer identities or invent facts. Identify service demand, timing "
        "patterns, cancellations/no-shows, and practical capacity improvements. "
        "Recommendations must cite a supplied number in the reason and remain "
        "advisory; never recommend automatically changing an appointment.\n\n"
        + json.dumps(aggregate_data, ensure_ascii=False, separators=(",", ":"))
    )
    body = json.dumps(
        {
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {
                "responseMimeType": "application/json",
                "responseSchema": _response_schema(),
            },
        }
    ).encode("utf-8")
    request = Request(
        endpoint,
        data=body,
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
            "x-goog-api-key": api_key,
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
            provider_error = f"Gemini returned HTTP {exc.code}."
        raise GeminiInsightsError(provider_error[:300]) from None
    except (URLError, TimeoutError, OSError):
        raise GeminiInsightsError(
            "Gemini could not be reached. The local statistics remain available."
        ) from None

    try:
        text = payload["candidates"][0]["content"]["parts"][0]["text"]
        result = json.loads(text)
        summary = str(result["executive_summary"]).strip()
        recommendations = result["recommendations"]
        observations = result["observations"]
        if not summary or not isinstance(recommendations, list) or not isinstance(observations, list):
            raise ValueError
        result["recommendations"] = recommendations[:6]
        result["observations"] = [str(item).strip() for item in observations[:6]]
        return result
    except (KeyError, IndexError, TypeError, ValueError, json.JSONDecodeError):
        raise GeminiInsightsError(
            "Gemini returned an incomplete analysis. Please generate it again."
        ) from None
