"""The recorded responses: fixed seed, fixed bytes, and the same shape as the real API."""
import json
import os
import subprocess
import sys
from pathlib import Path

from dawn_patrol import facts, fixtures

ROOT = Path(__file__).resolve().parents[1]

MARINE_KEYS = {"latitude", "longitude", "generationtime_ms", "utc_offset_seconds", "timezone",
               "timezone_abbreviation", "elevation", "hourly_units", "hourly"}


def names(directory):
    return sorted(path.name for path in Path(directory).iterdir())


def test_two_runs_at_seed_seven_are_byte_identical(tmp_path):
    first, second = tmp_path / "first", tmp_path / "second"
    fixtures.generate(7, first)
    fixtures.generate(7, second)

    assert names(first) == names(second)
    assert len(names(first)) == 2 * len(facts.load_spots())
    for name in names(first):
        assert (first / name).read_bytes() == (second / name).read_bytes(), name


def test_a_different_seed_changes_the_values(tmp_path):
    fixtures.generate(7, tmp_path / "seven")
    fixtures.generate(8, tmp_path / "eight")
    first = json.loads((tmp_path / "seven" / "marine-cloud-9.json").read_text())
    second = json.loads((tmp_path / "eight" / "marine-cloud-9.json").read_text())
    assert first["hourly"]["wave_height"] != second["hourly"]["wave_height"]


def test_fixture_shape_matches_the_live_endpoints(tmp_path):
    fixtures.generate(7, tmp_path)
    marine = json.loads((tmp_path / "marine-cloud-9.json").read_text())
    weather = json.loads((tmp_path / "forecast-cloud-9.json").read_text())

    assert set(marine) == MARINE_KEYS
    assert set(weather) == MARINE_KEYS
    assert set(marine["hourly"]) == {"time", "wave_height", "wave_period", "wave_direction"}
    assert set(weather["hourly"]) == {"time", "wind_speed_10m", "wind_direction_10m"}
    assert marine["hourly_units"]["wave_height"] == "m"
    assert marine["hourly_units"]["wave_period"] == "s"
    assert weather["hourly_units"]["wind_speed_10m"] == "km/h"
    assert len(marine["hourly"]["time"]) == 24
    assert len(weather["hourly"]["wind_speed_10m"]) == 24
    assert marine["hourly"]["time"][0] == "2026-11-09T00:00"
    assert all(0 <= value < 360 for value in marine["hourly"]["wave_direction"])
    assert all(0 <= value < 360 for value in weather["hourly"]["wind_direction_10m"])


def test_the_command_line_writes_the_same_files(tmp_path):
    first, second = tmp_path / "cli", tmp_path / "api"
    env = dict(os.environ)
    env.pop("LLM_URL", None)
    result = subprocess.run(
        [sys.executable, "-m", "dawn_patrol.fixtures", "--seed", "7", "--out", str(first)],
        cwd=ROOT, env=env, capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stderr

    fixtures.generate(7, second)
    assert names(first) == names(second)
    for name in names(first):
        assert (first / name).read_bytes() == (second / name).read_bytes(), name
