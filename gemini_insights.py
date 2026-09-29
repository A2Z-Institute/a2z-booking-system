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


def _gemini_request(prompt: str, response_schema: dict, max_output_tokens: int) -> dict:
    api_key = (os.environ.get("A2Z_GEMINI_API_KEY") or "").strip()
    if not api_key:
        raise GeminiInsightsError(
            "Gemini is not configured. Add A2Z_GEMINI_API_KEY in Coolify."
        )
    model = (os.environ.get("A2Z_GEMINI_MODEL") or "gemini-3.8-flash").strip()
    endpoint = (
        "https://generativelanguage.googleapis.com/v1beta/models/"
        f"{quote(model, safe='')}:generateContent"
    )
    body = json.dumps(
        {
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {
                "responseMimeType": "application/json",
                "responseSchema": response_schema,
                "temperature": 0.2,
                "maxOutputTokens": max_output_tokens,
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
        return json.loads(payload["candidates"][0]["content"]["parts"][0]["text"])
    except (KeyError, IndexError, TypeError, ValueError, json.JSONDecodeError):
        raise GeminiInsightsError("Gemini returned an incomplete response. Try again.") from None


def _anonymous_aggregate_data(aggregate_data: dict) -> dict:
    """Remove staff labels as well as all client data before an external request."""
    safe = json.loads(json.dumps(aggregate_data))
    safe["instructors"] = [
        {"name": f"Instructor {index}", "bookings": item.get("bookings", 0)}
        for index, item in enumerate(safe.get("instructors", []), start=1)
    ]
    return safe


def generate_booking_insights(aggregate_data: dict) -> dict:
    """Send anonymous aggregate counts to Gemini and return validated JSON."""
    aggregate_data = _anonymous_aggregate_data(aggregate_data)
    prompt = (
        "You are an operations analyst for an Indian heavy-equipment training "
        "institute. Analyse only the anonymous aggregate booking statistics below. "
        "Do not infer identities or invent facts. Identify service demand, timing "
        "patterns, cancellations/no-shows, and practical capacity improvements. "
        "Recommendations must cite a supplied number in the reason and remain "
        "advisory; never recommend automatically changing an appointment.\n\n"
        + json.dumps(aggregate_data, ensure_ascii=False, separators=(",", ":"))
    )
    try:
        result = _gemini_request(prompt, _response_schema(), 2048)
        summary = str(result["executive_summary"]).strip()
        recommendations = result["recommendations"]
        observations = result["observations"]
        if not summary or not isinstance(recommendations, list) or not isinstance(observations, list):
            raise ValueError
        validated_recommendations = []
        for item in recommendations[:6]:
            if not isinstance(item, dict):
                raise ValueError
            title = str(item.get("title") or "").strip()
            reason = str(item.get("reason") or "").strip()
            action = str(item.get("action") or "").strip()
            priority = str(item.get("priority") or "").strip()
            if (
                not title
                or not reason
                or not action
                or priority not in {"High", "Medium", "Low"}
            ):
                raise ValueError
            validated_recommendations.append(
                {"title": title, "reason": reason, "action": action, "priority": priority}
            )
        result["recommendations"] = validated_recommendations
        result["observations"] = [
            str(item).strip() for item in observations[:6] if str(item).strip()
        ]
        return result
    except (KeyError, IndexError, TypeError, ValueError, json.JSONDecodeError):
        raise GeminiInsightsError(
            "Gemini returned an incomplete analysis. Please generate it again."
        ) from None
