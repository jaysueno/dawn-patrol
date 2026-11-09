"""Write the three-line brief.

Two paths, one output. With LLM_URL unset the brief is a fixed template built from the facts,
and the template is written so the gate always accepts it. With LLM_URL set to an
OpenAI-compatible endpoint, the model is sent the facts JSON and returns three lines; those
lines go through the same gate, and a reject falls back to the template. A model that is down,
slow, or wrong never breaks the pipeline and never gets a number past the gate.

The model is never sent anything except the facts dict. There is no database handle, no page
text and no spot history in the request.
"""
from __future__ import annotations

import json
import os
import urllib.request

from dawn_patrol.facts import fmt_number
from dawn_patrol.gate import gate_reason

SYSTEM = "You write a three-line morning surf brief for one break, in the plain voice of a local surfer talking to a friend. You are given a JSON object of facts. Use every number in it, each with its unit exactly as follows: wave heights in m, the period in seconds, the wind in km/h, times as HH:MM. Use no other number of any kind, not even a count or an ordinal. Name the swell direction only with the compass abbreviation given, and the wind only with the word given (offshore, onshore or cross-shore). Do not mention any other direction. Three lines, no title, nothing else."

DEFAULT_TIMEOUT = 60.0


def timeout_seconds(value=None):
    """The request timeout in seconds: the argument, then LLM_TIMEOUT, then 60."""
    if value is not None:
        return float(value)
    raw = os.environ.get("LLM_TIMEOUT", "").strip()
    if not raw:
        return DEFAULT_TIMEOUT
    try:
        seconds = float(raw)
    except ValueError:
        return DEFAULT_TIMEOUT
    return seconds if seconds > 0 else DEFAULT_TIMEOUT


def template_brief(facts):
    """The fixed three-line brief. Every value is a fact, so the gate accepts it by construction."""
    return (
        "Swell %s to %s m at %s seconds from %s.\n"
        "Wind %s km/h %s.\n"
        "Best window %s to %s.\n"
    ) % (
        fmt_number(facts["wave_height_min_m"]),
        fmt_number(facts["wave_height_max_m"]),
        fmt_number(facts["period_s"]),
        facts["swell_direction"],
        fmt_number(facts["wind_speed_kmh"]),
        facts["wind_direction"],
        facts["best_window_start"],
        facts["best_window_end"],
    )


def _http_post(url, payload, timeout):
    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url, data=body, headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read()


def model_draft(facts, llm_url, model="local-model", transport=None, timeout=None):
    """Ask an OpenAI-compatible endpoint for three lines. Raises on any transport problem."""
    payload = {
        "model": model,
        "temperature": 0.7,
        "messages": [
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": json.dumps(facts, sort_keys=True)},
        ],
    }
    post = transport or _http_post
    raw = post(llm_url.rstrip("/") + "/chat/completions", payload, timeout_seconds(timeout))
    body = json.loads(raw.decode("utf-8") if isinstance(raw, bytes) else raw)
    text = body["choices"][0]["message"]["content"]
    lines = [line.strip() for line in str(text).splitlines() if line.strip()]
    if not lines:
        raise ValueError("the model returned an empty answer")
    return "\n".join(lines[:3]) + "\n"


def choose_brief(facts, llm_url=None, model="local-model", transport=None, timeout=None):
    """Return (brief text, source) where source is "model" or "template"."""
    if llm_url:
        try:
            draft = model_draft(facts, llm_url, model=model, transport=transport, timeout=timeout)
            if gate_reason(facts, draft) is None:
                return draft, "model"
        except (OSError, ValueError, KeyError, TypeError, IndexError):
            pass
    return template_brief(facts), "template"
