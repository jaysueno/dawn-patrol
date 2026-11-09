"""The gate accepts an honest draft and refuses every planted mistake."""
import json
import subprocess
import sys
from pathlib import Path

import pytest

from dawn_patrol import facts
from dawn_patrol.gate import direction_key, gate_reason

ROOT = Path(__file__).resolve().parents[1]

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

GOOD = (
    "Swell 1.2 to 1.8 m at 11 seconds from NE.\n"
    "Wind 14 km/h offshore.\n"
    "Best window 06:00 to 08:00.\n"
)


def test_an_honest_draft_is_accepted():
    assert gate_reason(FACTS, GOOD) is None


def test_an_invented_number_is_rejected():
    draft = GOOD.replace("11 seconds", "13 seconds")
    assert gate_reason(FACTS, draft) == "number not in facts: 13 seconds"


def test_a_changed_swell_direction_is_rejected():
    draft = GOOD.replace("from NE", "from SE")
    assert gate_reason(FACTS, draft) == "direction not in facts: se"


def test_a_changed_wind_direction_is_rejected():
    draft = GOOD.replace("km/h offshore", "km/h onshore")
    assert gate_reason(FACTS, draft) == "direction not in facts: onshore"


def test_a_dropped_number_is_rejected():
    draft = GOOD.replace("Wind 14 km/h offshore.", "Wind offshore.")
    assert gate_reason(FACTS, draft) == "missing number: 14 km/h"


def test_a_dropped_direction_word_is_rejected():
    draft = GOOD.replace(" from NE", "")
    assert gate_reason(FACTS, draft) == "missing direction word: ne"


def test_a_clock_time_outside_the_window_is_rejected():
    draft = GOOD.replace("06:00 to 08:00", "07:00 to 09:00")
    assert gate_reason(FACTS, draft) == "clock time not in facts: 07:00"


def test_a_missing_window_is_rejected():
    draft = GOOD.replace("Best window 06:00 to 08:00.\n", "")
    assert gate_reason(FACTS, draft) == "missing clock time: 06:00"


def test_a_unit_letter_is_not_read_as_a_compass_point():
    draft = GOOD.replace("11 seconds", "11s").replace("14 km/h", "14km/h")
    assert gate_reason(FACTS, draft) is None


def test_a_number_in_prose_is_rejected():
    draft = GOOD.replace("Best window", "Best 2 hour window")
    assert gate_reason(FACTS, draft) == "number has no unit: 2"


def test_a_lowercase_direction_word_is_accepted():
    assert gate_reason(FACTS, GOOD.lower().replace("swell", "Swell")) is None


def test_a_negative_wave_height_is_rejected():
    draft = GOOD.replace("Swell 1.2", "Swell -1.2")
    assert gate_reason(FACTS, draft) == "number not in facts: -1.2 m"


def test_a_unicode_minus_is_rejected():
    draft = GOOD.replace("Swell 1.2", "Swell −1.2")
    assert gate_reason(FACTS, draft) == "number not in facts: -1.2 m"


def test_a_negative_wind_speed_is_rejected():
    draft = GOOD.replace("Wind 14", "Wind -14")
    assert gate_reason(FACTS, draft) == "number not in facts: -14 km/h"


def test_a_hyphen_between_words_is_not_a_sign():
    local = dict(FACTS, wind_direction="cross-shore")
    draft = GOOD.replace("offshore", "cross-shore")
    assert gate_reason(local, draft) is None


def test_a_number_in_the_wrong_unit_is_rejected():
    draft = GOOD.replace("at 11 seconds", "at 14 seconds")
    assert gate_reason(FACTS, draft) == "number not in facts: 14 seconds"


def test_a_percentage_is_rejected():
    draft = GOOD.replace("Wind 14 km/h offshore.", "Wind 14 km/h offshore, 40% chance of rain.")
    assert gate_reason(FACTS, draft) == "number in a unit the facts do not use: 40%"


def test_a_full_compass_name_counts_as_the_fact_direction():
    assert gate_reason(FACTS, GOOD.replace("from NE", "from northeast")) is None


def test_a_hyphenated_compass_name_counts_as_the_fact_direction():
    assert gate_reason(FACTS, GOOD.replace("from NE", "from north-east")) is None


def test_a_second_direction_word_is_rejected():
    draft = GOOD.replace("from NE", "from NE with a southwest cross-swell")
    assert gate_reason(FACTS, draft) == "direction not in facts: southwest"


def test_the_spot_name_is_not_read_as_a_number():
    local = dict(FACTS, spot="Cloud 9")
    draft = GOOD.replace("Swell", "Cloud 9: Swell")
    assert gate_reason(local, draft) is None


def test_the_spot_name_is_removed_in_any_case():
    local = dict(FACTS, spot="Pipeline")
    draft = GOOD.replace("Swell", "pipeline swell")
    assert gate_reason(local, draft) is None


PIPELINE_FACTS = {
    "spot": "Pipeline",
    "wave_height_min_m": 1.13,
    "wave_height_max_m": 2.03,
    "period_s": 11.4,
    "swell_direction": "NW",
    "wind_speed_kmh": 15.3,
    "wind_direction": "onshore",
    "best_window_start": "15:00",
    "best_window_end": "17:00",
}

PIPELINE_DRAFT = (
    "Pipeline's holding up with NW swell and 15.3 km/h onshore wind.\n"
    "Sets are rolling 1.13 m to 2.03 m with 11.4 seconds period.\n"
    "Best window is 15:00 to 17:00.\n"
)


def test_an_apostrophe_s_is_not_a_direction_word():
    assert gate_reason(PIPELINE_FACTS, PIPELINE_DRAFT) is None


def test_a_standalone_south_is_still_a_direction_word():
    draft = PIPELINE_DRAFT.replace("NW swell", "NW swell and south")
    assert gate_reason(PIPELINE_FACTS, draft) == "direction not in facts: south"


def test_a_standalone_s_is_still_a_direction_word():
    draft = PIPELINE_DRAFT.replace("15.3 km/h", "15.3 km/h S")
    assert gate_reason(PIPELINE_FACTS, draft) == "direction not in facts: s"


@pytest.mark.parametrize("name,key", [
    ("north", "n"), ("north-northeast", "nne"), ("northeast", "ne"), ("north-east", "ne"),
    ("east-northeast", "ene"), ("east", "e"), ("east-southeast", "ese"), ("southeast", "se"),
    ("south-east", "se"), ("south-southeast", "sse"), ("south", "s"), ("south-southwest", "ssw"),
    ("southwest", "sw"), ("south-west", "sw"), ("west-southwest", "wsw"), ("west", "w"),
    ("west-northwest", "wnw"), ("northwest", "nw"), ("north-west", "nw"),
    ("north-northwest", "nnw"), ("offshore", "offshore"), ("onshore", "onshore"),
    ("cross-shore", "cross-shore"), ("side-shore", "side-shore"),
])
def test_direction_names_map_to_their_key(name, key):
    assert direction_key(name) == key


@pytest.mark.parametrize("point", facts.COMPASS)
def test_every_compass_point_is_a_valid_direction_word(point):
    local = dict(FACTS, swell_direction=point)
    draft = GOOD.replace("from NE", "from %s" % point)
    assert gate_reason(local, draft) is None


@pytest.mark.parametrize("point", [word for word in facts.COMPASS if word != "NE"])
def test_a_neighbouring_compass_point_is_rejected(point):
    draft = GOOD.replace("from NE", "from %s" % point)
    assert gate_reason(FACTS, draft) is not None


# The grader's twelve adversarial drafts, with the verdict the round 2 rules give them.
ADVERSARIAL = [
    ("period written as a word",
     "Swell 1.2 to 1.8 m at eleven seconds from NE.\nWind 14 km/h offshore.\n"
     "Best window 06:00 to 08:00.\n", "REJECT"),
    ("trailing zero on a height",
     "Swell 1.20 to 1.8 m at 11 seconds from NE.\nWind 14 km/h offshore.\n"
     "Best window 06:00 to 08:00.\n", "ACCEPT"),
    ("rounded heights",
     "Swell 1 to 2 m at 11 seconds from NE.\nWind 14 km/h offshore.\n"
     "Best window 06:00 to 08:00.\n", "REJECT"),
    ("heights with feet added",
     "Swell 1.2 to 1.8 m (4 to 6 ft) at 11 seconds from NE.\nWind 14 km/h offshore.\n"
     "Best window 06:00 to 08:00.\n", "REJECT"),
    ("window in am/pm",
     "Swell 1.2 to 1.8 m at 11 seconds from NE.\nWind 14 km/h offshore.\n"
     "Best window 6 am to 08:00.\n", "REJECT"),
    ("an extra harmless number",
     "Swell 1.2 to 1.8 m at 11 seconds from NE.\nWind 14 km/h offshore, 3 lines.\n"
     "Best window 06:00 to 08:00.\n", "REJECT"),
    ("direction written in full",
     "Swell 1.2 to 1.8 m at 11 seconds from northeast.\nWind 14 km/h offshore.\n"
     "Best window 06:00 to 08:00.\n", "ACCEPT"),
    ("a second direction word",
     "Swell 1.2 to 1.8 m at 11 seconds from NE with a southwest cross-swell.\n"
     "Wind 14 km/h offshore.\nBest window 06:00 to 08:00.\n", "REJECT"),
    ("a negative height",
     "Swell -1.2 to 1.8 m at 11 seconds from NE.\nWind 14 km/h offshore.\n"
     "Best window 06:00 to 08:00.\n", "REJECT"),
    ("a percentage",
     "Swell 1.2 to 1.8 m at 11 seconds from NE.\n"
     "Wind 14 km/h offshore, 40% chance of rain.\nBest window 06:00 to 08:00.\n", "REJECT"),
    ("the break's name glued to a digit",
     "Swell 1.2 to 1.8 m at 11 seconds from NE at Cloud9.\nWind 14 km/h offshore.\n"
     "Best window 06:00 to 08:00.\n", "ACCEPT"),
    ("an empty draft", "", "REJECT"),
]


@pytest.mark.parametrize("name,draft,verdict", ADVERSARIAL)
def test_the_graders_adversarial_drafts(name, draft, verdict):
    reason = gate_reason(FACTS, draft)
    if verdict == "ACCEPT":
        assert reason is None, name
    else:
        assert reason is not None, name
        assert reason.strip(), name


def test_the_command_line_prints_one_line_and_sets_the_exit_code(tmp_path):
    facts_file = tmp_path / "facts.json"
    facts_file.write_text(json.dumps(FACTS), encoding="utf-8")
    good = tmp_path / "good.txt"
    good.write_text(GOOD, encoding="utf-8")
    bad = tmp_path / "bad.txt"
    bad.write_text(GOOD.replace("11 seconds", "13 seconds"), encoding="utf-8")

    accepted = subprocess.run(
        [sys.executable, "-m", "dawn_patrol.gate", "--facts", str(facts_file), "--draft", str(good)],
        cwd=ROOT, capture_output=True, text=True, timeout=60)
    assert accepted.returncode == 0
    assert accepted.stdout == "ACCEPT\n"

    rejected = subprocess.run(
        [sys.executable, "-m", "dawn_patrol.gate", "--facts", str(facts_file), "--draft", str(bad)],
        cwd=ROOT, capture_output=True, text=True, timeout=60)
    assert rejected.returncode == 1
    lines = rejected.stdout.splitlines()
    assert len(lines) == 1
    assert lines[0].startswith("REJECT ")
