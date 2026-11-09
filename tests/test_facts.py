"""Facts come only from stored rows, and every number is tied to a named column."""
import random

import pytest

from dawn_patrol import facts
from dawn_patrol.brief import template_brief
from dawn_patrol.gate import gate_reason

SPOT = {"name": "Test Point", "best_wind_direction": "SW"}


def make_rows(count=24, height=1.5, period=10.0, swell_from=45,
              wind=10.0, wind_from=225):
    return [
        {
            "valid_utc": "2026-11-09T%02d:00" % hour,
            "wave_height_m": height,
            "wave_period_s": period,
            "wave_direction_deg": swell_from,
            "wind_speed_kmh": wind,
            "wind_direction_deg": wind_from,
        }
        for hour in range(count)
    ]


def test_every_fact_has_a_named_source_column():
    covered = set(facts.NUMBER_SOURCES) | set(facts.DIRECTION_SOURCES)
    assert covered == set(facts.FACT_KEYS) - {"spot"}
    for key in facts.NUMBER_SOURCES:
        assert facts.NUMBER_SOURCES[key].startswith("forecast.")
    for key in facts.DIRECTION_SOURCES:
        assert facts.DIRECTION_SOURCES[key].startswith("forecast.")


def test_the_facts_have_exactly_the_frozen_keys():
    row = facts.facts_for(SPOT, make_rows())
    assert tuple(row) == facts.FACT_KEYS


def test_the_facts_change_when_a_stored_value_changes():
    calm = facts.facts_for(SPOT, make_rows(wind=5.0, height=1.0))
    windy = facts.facts_for(SPOT, make_rows(wind=40.0, height=3.0))
    assert calm["wind_speed_kmh"] == 5.0
    assert windy["wind_speed_kmh"] == 40.0
    assert calm["wave_height_max_m"] == 1.0
    assert windy["wave_height_max_m"] == 3.0
    assert calm["period_s"] == 10.0


def test_compass_words_round_trip():
    for index, point in enumerate(facts.COMPASS):
        assert facts.compass_word(index * 22.5) == point


@pytest.mark.parametrize("gap,word", [
    (0.0, "offshore"),
    (45.0, "offshore"),
    (46.0, "cross-shore"),
    (90.0, "cross-shore"),
    (134.0, "cross-shore"),
    (135.0, "onshore"),
    (180.0, "onshore"),
])
def test_the_wind_word_is_measured_from_the_offshore_direction(gap, word):
    # SW is 225 degrees; a wind from 225 + gap degrees.
    assert facts.wind_word((225.0 + gap) % 360.0, "SW") == word


def test_the_best_window_picks_the_calm_hours():
    rows = make_rows(wind=40.0)
    for index in (6, 7):
        rows[index]["wind_speed_kmh"] = 3.0
        rows[index]["wave_height_m"] = 1.5
    assert facts.best_window(rows, "SW") == ("06:00", "08:00")


def test_the_best_window_runs_past_midnight():
    rows = make_rows()
    rows[23]["valid_utc"] = "2026-11-09T23:00"
    start, end = facts.best_window(rows[22:], "SW")
    assert (start, end) == ("22:00", "00:00")


def test_too_few_rows_is_an_error():
    with pytest.raises(ValueError):
        facts.facts_for(SPOT, make_rows(count=1))


def test_the_template_brief_always_passes_the_gate():
    rng = random.Random(3)
    for _ in range(60):
        rows = [
            {
                "valid_utc": "2026-11-09T%02d:00" % hour,
                "wave_height_m": round(rng.uniform(0.3, 3.5), 2),
                "wave_period_s": round(rng.uniform(5.0, 18.0), 1),
                "wave_direction_deg": rng.randrange(0, 360),
                "wind_speed_kmh": round(rng.uniform(0.0, 45.0), 1),
                "wind_direction_deg": rng.randrange(0, 360),
            }
            for hour in range(24)
        ]
        spot = {"name": "Random Point", "best_wind_direction": rng.choice(facts.COMPASS)}
        row = facts.facts_for(spot, rows)
        assert gate_reason(row, template_brief(row)) is None, row
