"""The brief falls back to the template whenever the model is missing, down or wrong."""
import json

from dawn_patrol.brief import choose_brief, template_brief
from dawn_patrol.gate import gate_reason

FACTS = {
    "spot": "Fixture Point",
    "wave_height_min_m": 1.2,
    "wave_height_max_m": 1.8,
    "period_s": 11,
    "swell_direction": "NE",
    "wind_speed_kmh": 14,
    "wind_direction": "offshore",
    "best_window_start": "06:00",
    "best_window_end": "08:00",
}

GOOD_DRAFT = (
    "Swell 1.2 to 1.8 m at 11 seconds from NE.\n"
    "Wind 14 km/h offshore.\n"
    "Best window 06:00 to 08:00."
)


def make_transport(text):
    calls = {}

    def transport(url, payload, timeout):
        calls["url"] = url
        calls["payload"] = payload
        body = {"choices": [{"message": {"content": text}}]}
        return json.dumps(body).encode("utf-8")

    return transport, calls


def test_without_a_model_the_template_is_used():
    text, source = choose_brief(FACTS)
    assert source == "template"
    assert text == template_brief(FACTS)
    assert gate_reason(FACTS, text) is None


def test_a_model_draft_that_passes_the_gate_is_used():
    transport, calls = make_transport(GOOD_DRAFT)
    text, source = choose_brief(FACTS, "http://localhost:11434/v1", transport=transport)
    assert source == "model"
    assert text.strip() == GOOD_DRAFT
    assert calls["url"] == "http://localhost:11434/v1/chat/completions"


def test_the_model_only_receives_the_facts():
    transport, calls = make_transport(GOOD_DRAFT)
    choose_brief(FACTS, "http://localhost:11434/v1", transport=transport)
    messages = calls["payload"]["messages"]
    assert messages[0]["role"] == "system"
    assert messages[1]["role"] == "user"
    assert json.loads(messages[1]["content"]) == FACTS


def test_a_model_draft_with_an_invented_number_falls_back():
    bad = GOOD_DRAFT.replace("11 seconds", "13 seconds")
    transport, _calls = make_transport(bad)
    text, source = choose_brief(FACTS, "http://localhost:11434/v1", transport=transport)
    assert source == "template"
    assert text == template_brief(FACTS)


def test_a_model_that_is_down_falls_back():
    def down(_url, _payload, _timeout):
        raise OSError("connection refused")

    text, source = choose_brief(FACTS, "http://localhost:11434/v1", transport=down)
    assert source == "template"
    assert text == template_brief(FACTS)
