"""Turn stored forecast rows into the facts a brief may state.

Every value here is computed from rows in the SQLite file. There is no model call, no
network call and no clock in this module, so the same rows always give the same facts.

The fact keys are frozen, because the gate reads them by name:

    spot, wave_height_min_m, wave_height_max_m, period_s, swell_direction,
    wind_speed_kmh, wind_direction, best_window_start, best_window_end
"""
from __future__ import annotations

import math
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SPOTS_FILE = ROOT / "spots.toml"

# The 16 compass points, clockwise from north, and the four words the gate accepts for a
# wind that is not given as a compass point.
COMPASS = (
    "N", "NNE", "NE", "ENE",
    "E", "ESE", "SE", "SSE",
    "S", "SSW", "SW", "WSW",
    "W", "WNW", "NW", "NNW",
)
SHORE_WORDS = ("offshore", "onshore", "cross-shore", "side-shore")
DIRECTION_WORDS = tuple(word.lower() for word in COMPASS) + SHORE_WORDS

FACT_KEYS = (
    "spot",
    "wave_height_min_m",
    "wave_height_max_m",
    "period_s",
    "swell_direction",
    "wind_speed_kmh",
    "wind_direction",
    "best_window_start",
    "best_window_end",
)

# Every number a brief may say, and the stored column it comes from. tests/test_facts.py
# reads this map and asserts that each column exists in the schema, so a renamed column
# breaks a test instead of silently changing a published number.
NUMBER_SOURCES = {
    "wave_height_min_m": "forecast.wave_height_m",
    "wave_height_max_m": "forecast.wave_height_m",
    "period_s": "forecast.wave_period_s",
    "wind_speed_kmh": "forecast.wind_speed_kmh",
    "best_window_start": "forecast.valid_utc",
    "best_window_end": "forecast.valid_utc",
}

# The two direction words in a brief, and the stored column each is computed from.
DIRECTION_SOURCES = {
    "swell_direction": "forecast.wave_direction_deg",
    "wind_direction": "forecast.wind_direction_deg",
}


def load_spots(path=None):
    """Read spots.toml and return the list of spot dicts, in file order."""
    source = Path(path) if path else SPOTS_FILE
    with open(source, "rb") as handle:
        data = tomllib.load(handle)
    spots = data.get("spots", [])
    if not spots:
        raise ValueError("spots.toml lists no spots")
    return spots


def spot_by_slug(slug, path=None):
    for spot in load_spots(path):
        if spot["slug"] == slug:
            return spot
    raise KeyError("no spot with slug %r in spots.toml" % slug)


def compass_word(degrees):
    """The nearest of the 16 compass points to an angle in degrees clockwise from north."""
    return COMPASS[int((float(degrees) % 360.0) / 22.5 + 0.5) % 16]


def compass_degrees(word):
    """The centre of a compass point, in degrees. Raises KeyError for anything else."""
    return COMPASS.index(str(word).upper()) * 22.5


def circular_mean(degrees):
    """The mean direction of a list of angles, in degrees clockwise from north."""
    values = [float(value) for value in degrees if value is not None]
    if not values:
        raise ValueError("no directions to average")
    east = sum(math.cos(math.radians(value)) for value in values)
    north = sum(math.sin(math.radians(value)) for value in values)
    return math.degrees(math.atan2(north, east)) % 360.0


def angular_gap(a, b):
    """The smaller angle between two bearings, 0 to 180 degrees."""
    return abs((float(a) - float(b) + 180.0) % 360.0 - 180.0)


def wind_word(wind_from_degrees, best_wind_direction):
    """Name the wind relative to the break.

    Open-Meteo reports the direction the wind comes FROM. spots.toml records the direction
    that blows offshore at each break, so a wind within 45 degrees of it is offshore, a wind
    within 45 degrees of the opposite direction is onshore, and the rest is cross-shore.
    """
    best = compass_degrees(best_wind_direction)
    gap = angular_gap(wind_from_degrees, best)
    if gap <= 45.0:
        return "offshore"
    if gap >= 135.0:
        return "onshore"
    return "cross-shore"


def _clock(value):
    """Normalise one ISO local time, "YYYY-MM-DDTHH:MM", to "HH:MM"."""
    text = str(value)
    if "T" in text:
        text = text.split("T", 1)[1]
    hour, _, minute = text.partition(":")
    return "%02d:%s" % (int(hour), minute[:2])


def _plus_one_hour(stamp):
    """Add one hour to an ISO local time, keeping the "YYYY-MM-DDTHH:MM" shape."""
    date, _, clock = str(stamp).partition("T")
    hour, _, minute = clock.partition(":")
    hour = (int(hour) + 1) % 24
    if hour == 0:
        from datetime import date as _date, timedelta

        day = _date.fromisoformat(date) + timedelta(days=1)
        date = day.isoformat()
    return "%sT%02d:%s" % (date, hour, minute[:2])


def best_window(hours, best_wind_direction):
    """Pick the best two-hour window in the series and return ("HH:MM", "HH:MM").

    The score for the two hours starting at index i is the sum of three parts:

        wind      = 60 - mean wind speed in km/h          (calm scores higher)
        direction = 20 when the mean wind over the window is offshore, else 0
        swell     = 12 - 8 * abs(mean wave height - 1.5)  (a head-high wave is the target)

    The highest score wins. A tie goes to the earlier window. The window is the pair of
    hourly readings at i and i+1, reported as the start at i and the end one hour after i+1,
    so the two readings at 06:00 and 07:00 read "06:00 to 08:00". Fewer than two hours is
    an error: with nothing to compare there is no window to call best.
    """
    usable = [row for row in hours if row.get("wave_height_m") is not None
              and row.get("wind_speed_kmh") is not None and row.get("wind_direction_deg") is not None]
    if len(usable) < 2:
        raise ValueError("need at least two hourly rows to pick a window")

    best_index, best_score = 0, None
    for index in range(len(usable) - 1):
        pair = usable[index:index + 2]
        wind = sum(float(row["wind_speed_kmh"]) for row in pair) / 2.0
        swell = sum(float(row["wave_height_m"]) for row in pair) / 2.0
        wind_from = circular_mean([row["wind_direction_deg"] for row in pair])
        word = wind_word(wind_from, best_wind_direction)
        direction = 20.0 if word == "offshore" else 0.0
        score = (60.0 - wind) + direction + (12.0 - 8.0 * abs(swell - 1.5))
        if best_score is None or score > best_score:
            best_index, best_score = index, score

    start = usable[best_index]["valid_utc"]
    end = _plus_one_hour(usable[best_index + 1]["valid_utc"])
    return _clock(start), _clock(end)


def facts_for(spot, hours):
    """Build the frozen facts dict for one spot from its merged hourly rows.

    `hours` is a list of dicts with valid_utc, wave_height_m, wave_period_s,
    wave_direction_deg, wind_speed_kmh and wind_direction_deg. Rows missing any value are
    skipped. Raises ValueError when there is not enough data to state a fact.
    """
    complete = [row for row in hours
                if all(row.get(key) is not None for key in
                       ("valid_utc", "wave_height_m", "wave_period_s", "wave_direction_deg",
                        "wind_speed_kmh", "wind_direction_deg"))]
    if len(complete) < 2:
        raise ValueError("not enough hourly rows for %s" % spot["name"])

    heights = [float(row["wave_height_m"]) for row in complete]
    periods = [float(row["wave_period_s"]) for row in complete]
    winds = [float(row["wind_speed_kmh"]) for row in complete]
    start, end = best_window(complete, spot["best_wind_direction"])

    return {
        "spot": spot["name"],
        "wave_height_min_m": round(min(heights), 2),
        "wave_height_max_m": round(max(heights), 2),
        "period_s": round(sum(periods) / len(periods), 1),
        "swell_direction": compass_word(circular_mean([row["wave_direction_deg"] for row in complete])),
        "wind_speed_kmh": round(sum(winds) / len(winds), 1),
        "wind_direction": wind_word(circular_mean([row["wind_direction_deg"] for row in complete]),
                                    spot["best_wind_direction"]),
        "best_window_start": start,
        "best_window_end": end,
    }


def fmt_number(value):
    """Format a fact value for a brief: 11.0 reads "11", 1.2 reads "1.2", 1.04 reads "1.04"."""
    number = float(value)
    if number.is_integer():
        return str(int(number))
    return ("%.2f" % number).rstrip("0").rstrip(".")
