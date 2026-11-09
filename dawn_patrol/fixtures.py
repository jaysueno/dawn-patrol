"""Recorded Open-Meteo responses, generated from a fixed seed.

The real pipeline calls two public endpoints, the marine API and the forecast API, and keeps
the JSON they return. The tests never call either one. This module writes a stand-in that has
the same shape: the same top-level keys, the same hourly_units, the same hourly arrays, one
value per hour for 24 hours. The values are synthetic and a fixed seed makes them
byte-identical on every run.

    python3 -m dawn_patrol.fixtures --seed 7 --out fixtures/

Files are named marine-<slug>.json and forecast-<slug>.json, one pair per spot in spots.toml.
"""
from __future__ import annotations

import argparse
import json
import math
import random
from pathlib import Path

from dawn_patrol.facts import compass_degrees, load_spots

HOURS = 24
DAY = "2026-11-09"

# Per-spot shape of the synthetic day, in spots.toml order. The wind offset is the gap in
# degrees between the break's offshore direction and the day's mean wind, so the three spots
# show one offshore day, one cross-shore day and one onshore day.
WIND_OFFSETS = (0.0, 90.0, 180.0)


def _times():
    return ["%sT%02d:00" % (DAY, hour) for hour in range(HOURS)]


def _wave_series(rng, base, amplitude, jitter):
    values = []
    for hour in range(HOURS):
        value = base + amplitude * math.sin(2.0 * math.pi * hour / HOURS) + rng.uniform(-jitter, jitter)
        values.append(round(min(4.5, max(0.2, value)), 2))
    return values


def _period_series(rng, base):
    values = []
    for hour in range(HOURS):
        value = base + 1.6 * math.sin(2.0 * math.pi * (hour + 3) / HOURS) + rng.uniform(-0.6, 0.6)
        values.append(round(min(20.0, max(4.0, value)), 1))
    return values


def _wind_series(rng, base):
    values = []
    for hour in range(HOURS):
        value = base + 5.0 * math.sin(2.0 * math.pi * (hour + 2) / HOURS) + rng.uniform(-2.0, 2.0)
        values.append(round(min(60.0, max(0.0, value)), 1))
    return values


def _direction_series(rng, base, spread):
    values = []
    for hour in range(HOURS):
        value = base + spread * math.sin(2.0 * math.pi * (hour + 1) / HOURS) + rng.uniform(-6.0, 6.0)
        values.append(int(round(value)) % 360)
    return values


def marine_payload(spot, seed, index):
    """One marine response for a spot, shaped like the real endpoint's reply."""
    rng = random.Random("marine:%s:%s" % (seed, spot["slug"]))
    wave_base = 1.10 + 0.25 * index
    swell_from = compass_degrees(spot["best_swell_direction"])
    return {
        "latitude": spot["latitude"],
        "longitude": spot["longitude"],
        "generationtime_ms": round(rng.uniform(0.08, 0.9), 3),
        "utc_offset_seconds": spot["utc_offset_seconds"],
        "timezone": spot["timezone"],
        "timezone_abbreviation": "GMT%+d" % (spot["utc_offset_seconds"] // 3600),
        "elevation": 0.0,
        "hourly_units": {
            "time": "iso8601",
            "wave_height": "m",
            "wave_period": "s",
            "wave_direction": "°",
        },
        "hourly": {
            "time": _times(),
            "wave_height": _wave_series(rng, wave_base, 0.35, 0.18),
            "wave_period": _period_series(rng, 9.0 + 1.2 * index),
            "wave_direction": _direction_series(rng, swell_from, 30.0),
        },
    }


def forecast_payload(spot, seed, index):
    """One weather response for a spot, shaped like the real endpoint's reply."""
    rng = random.Random("forecast:%s:%s" % (seed, spot["slug"]))
    wind_from = compass_degrees(spot["best_wind_direction"]) + WIND_OFFSETS[index % len(WIND_OFFSETS)]
    return {
        "latitude": spot["latitude"],
        "longitude": spot["longitude"],
        "generationtime_ms": round(rng.uniform(0.08, 0.9), 3),
        "utc_offset_seconds": spot["utc_offset_seconds"],
        "timezone": spot["timezone"],
        "timezone_abbreviation": "GMT%+d" % (spot["utc_offset_seconds"] // 3600),
        "elevation": 10.0,
        "hourly_units": {
            "time": "iso8601",
            "wind_speed_10m": "km/h",
            "wind_direction_10m": "°",
        },
        "hourly": {
            "time": _times(),
            "wind_speed_10m": _wind_series(rng, 9.0 + 3.0 * index),
            "wind_direction_10m": _direction_series(rng, wind_from, 20.0),
        },
    }


def generate(seed, out_dir):
    """Write one marine and one forecast file per spot. Returns the paths written."""
    target = Path(out_dir)
    target.mkdir(parents=True, exist_ok=True)
    written = []
    for index, spot in enumerate(load_spots()):
        for kind, payload in (("marine", marine_payload(spot, seed, index)),
                              ("forecast", forecast_payload(spot, seed, index))):
            path = target / ("%s-%s.json" % (kind, spot["slug"]))
            path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            written.append(path)
    return written


def main(argv=None):
    parser = argparse.ArgumentParser(description="Write recorded Open-Meteo responses at a fixed seed.")
    parser.add_argument("--seed", type=int, default=7, help="generator seed (default 7)")
    parser.add_argument("--out", required=True, help="directory to write the fixtures into")
    args = parser.parse_args(argv)

    paths = generate(args.seed, args.out)
    print("wrote %d fixture file(s) at seed %d to %s" % (len(paths), args.seed, args.out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
