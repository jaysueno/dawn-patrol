"""The number gate: the one rule that keeps a brief honest.

A draft is accepted only when every number in it carries the unit of the fact it states, and
every direction word maps to one of the facts' two direction words. The facts come from stored
rows, so an accepted brief cannot state a number or a direction the database does not hold.

Rules, applied in this order:

1. The spot name is removed first, so "Cloud 9" is a name and never a number.
2. Every clock time in the draft (HH:MM) must equal one of the two window strings, and both
   window strings must appear.
3. A number is read with its sign and its unit. A minus sign (ASCII "-" or U+2212) directly in
   front of a digit is part of that number, so "-1.2 m" is a negative height and is rejected.
   A hyphen with a space after it, or between two numbers, is a range separator, not a sign.
4. A number counts as a fact only when it carries that fact's unit: heights in m, metres or
   meters; the period in s, sec, secs, second or seconds; wind in km/h or kph. In a range like
   "1.2 to 1.8 m" the unit after the second number applies to both. A number with any other
   unit, or with none, is rejected. Comparison is by value, so 1.20 equals 1.2.
5. Every direction word in the draft must map to one of the facts' two direction words, and
   both of those words must appear. A direction word is one of the 16 compass points, written
   as an abbreviation (NE), a full name (northeast) or a hyphenated name (north-east), or one
   of offshore, onshore, cross-shore, side-shore. A letter run glued to the end of a number is
   a unit, not a direction word, so "11s" is eleven seconds and not a south wind. An "s" right
   after an apostrophe closes a possessive or a contraction, so "Pipeline's" and "it's" carry
   no direction word either.

The command line prints exactly "ACCEPT" and exits 0, or exactly one line "REJECT <reason>"
and exits 1. Nothing else goes to stdout.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from decimal import Decimal, InvalidOperation

from dawn_patrol.facts import COMPASS, SHORE_WORDS

TIME_RE = re.compile(r"(?<!\d)(\d{1,2}):(\d{2})(?!\d)")
# A number not glued to a preceding word character or dot. The sign must sit directly in front
# of the first digit, so "1.2 - 1.8" is a range and "-1.8" is a negative number.
NUMBER_RE = re.compile(r"(?<![\w.])(?P<sign>[-−])?(?P<num>\d+(?:\.\d+)?)(?![\d.])")
UNIT_RE = re.compile(
    r"\s*(?:(?P<wind>km/h|kph)\b"
    r"|(?P<percent>%)"
    r"|(?P<metre>metres|meters|metre|meter|m)\b"
    r"|(?P<second>seconds|second|secs|sec|s)\b)", re.I)
BETWEEN_RE = re.compile(r"\s*(?:to|[-–])\s*", re.I)
WORD_RE = re.compile(r"[A-Za-z]+(?:-[A-Za-z]+)*")

NUMBER_KEYS = ("wave_height_min_m", "wave_height_max_m", "period_s", "wind_speed_kmh")
DIRECTION_KEYS = ("swell_direction", "wind_direction")
WINDOW_KEYS = ("best_window_start", "best_window_end")

UNIT_FOR_KEY = {
    "wave_height_min_m": "m",
    "wave_height_max_m": "m",
    "period_s": "s",
    "wind_speed_kmh": "kmh",
}
UNIT_LABEL = {"m": "m", "s": "seconds", "kmh": "km/h", "percent": "%"}

_COMPASS_SPELLINGS = {
    "N": ("north",),
    "NNE": ("north-northeast",),
    "NE": ("northeast", "north-east"),
    "ENE": ("east-northeast",),
    "E": ("east",),
    "ESE": ("east-southeast",),
    "SE": ("southeast", "south-east"),
    "SSE": ("south-southeast",),
    "S": ("south",),
    "SSW": ("south-southwest",),
    "SW": ("southwest", "south-west"),
    "WSW": ("west-southwest",),
    "W": ("west",),
    "WNW": ("west-northwest",),
    "NW": ("northwest", "north-west"),
    "NNW": ("north-northwest",),
}

DIRECTION_NAMES = {}
for _abbreviation in COMPASS:
    DIRECTION_NAMES[_abbreviation.lower()] = _abbreviation.lower()
    for _name in _COMPASS_SPELLINGS[_abbreviation]:
        DIRECTION_NAMES[_name] = _abbreviation.lower()
for _word in SHORE_WORDS:
    DIRECTION_NAMES[_word] = _word


def direction_key(word):
    """The canonical form of a direction word, or None when the word is not a direction."""
    return DIRECTION_NAMES.get(str(word).strip().lower())


def _decimal(value, key):
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise ValueError("fact %s is not a number" % key)


def _clock(value):
    text = str(value).strip()
    hour, _, minute = text.partition(":")
    if not minute or not hour.isdigit() or not minute.isdigit():
        raise ValueError("window %r is not HH:MM" % text)
    return "%02d:%s" % (int(hour), minute[:2])


def _words(text):
    """Every word in the draft, except a unit letter and an apostrophe-s.

    A letter run glued to the end of a number is a unit ("11s" is eleven seconds). An "s"
    right after an apostrophe closes a possessive or a contraction ("Pipeline's", "it's") and
    is never a direction word.
    """
    words = []
    for match in WORD_RE.finditer(text):
        start = match.start()
        if start > 0 and (text[start - 1].isdigit() or text[start - 1] == "."):
            continue
        if start > 0 and text[start - 1] in "'’" and match.group(0).lower() == "s":
            continue
        words.append(match.group(0))
    return words


def _unit_at(text, position):
    """The unit that follows a number, and where it ends. None when there is no known unit."""
    match = UNIT_RE.match(text, position)
    if not match:
        return None, position
    if match.group("wind"):
        return "kmh", match.end()
    if match.group("percent"):
        return "percent", match.end()
    if match.group("metre"):
        return "m", match.end()
    return "s", match.end()


def _said(occurrence):
    """How to quote a number back in a reason."""
    unit = occurrence["unit"]
    if unit == "percent":
        return occurrence["raw"] + "%"
    return ("%s %s" % (occurrence["raw"], UNIT_LABEL.get(unit, ""))).strip()


def _occurrences(text):
    """Every number in the text, with its sign and its unit, in reading order."""
    found = []
    for match in NUMBER_RE.finditer(text):
        sign = match.group("sign")
        literal = (sign.replace("−", "-") if sign else "") + match.group("num")
        unit, unit_end = _unit_at(text, match.end())
        found.append({
            "value": Decimal(literal),
            "raw": literal,
            "unit": unit,
            "start": match.start(),
            "end": match.end(),
            "unit_end": unit_end,
        })
    # A range hands the unit after its second number to the first number.
    for index, occurrence in enumerate(found):
        if occurrence["unit"] is not None or index + 1 >= len(found):
            continue
        following = found[index + 1]
        if following["unit"] is None:
            continue
        if BETWEEN_RE.fullmatch(text[occurrence["end"]:following["start"]]):
            occurrence["unit"] = following["unit"]
    return found


def gate_reason(facts, draft):
    """Return None when the draft may ship, or a short reason when it may not."""
    if not isinstance(facts, dict):
        return "facts are not a JSON object"
    text = "" if draft is None else str(draft)

    for key in NUMBER_KEYS + WINDOW_KEYS + DIRECTION_KEYS:
        if key not in facts:
            return "facts are missing %s" % key

    numbers = {key: _decimal(facts[key], key) for key in NUMBER_KEYS}
    windows = {key: _clock(facts[key]) for key in WINDOW_KEYS}
    swell = direction_key(facts["swell_direction"])
    wind = direction_key(facts["wind_direction"])
    if swell is None or wind is None:
        return "bad facts: unknown direction word"
    allowed = {swell, wind}

    # 1. The spot name is a name, not a number.
    spot = str(facts.get("spot") or "").strip()
    if spot:
        text = re.sub(re.escape(spot), " ", text, flags=re.I)

    # 2. Clock times.
    found_times = []
    for hour, minute in TIME_RE.findall(text):
        stamp = "%02d:%s" % (int(hour), minute)
        if stamp not in windows.values():
            return "clock time not in facts: %s" % stamp
        found_times.append(stamp)
    for stamp in windows.values():
        if stamp not in found_times:
            return "missing clock time: %s" % stamp
    rest = TIME_RE.sub(" ", text)

    # 3 and 4. Numbers, their signs and their units.
    found = _occurrences(rest)
    for occurrence in found:
        if occurrence["unit"] is None:
            return "number has no unit: %s" % occurrence["raw"]
        keys = [key for key in NUMBER_KEYS if UNIT_FOR_KEY[key] == occurrence["unit"]]
        if not keys:
            return "number in a unit the facts do not use: %s" % _said(occurrence)
        if occurrence["value"] not in {numbers[key] for key in keys}:
            return "number not in facts: %s" % _said(occurrence)
    for key in NUMBER_KEYS:
        unit = UNIT_FOR_KEY[key]
        if numbers[key] not in [item["value"] for item in found if item["unit"] == unit]:
            return "missing number: %s %s" % (facts[key], UNIT_LABEL[unit])

    # 5. Direction words.
    found_keys = []
    for word in _words(rest):
        key = direction_key(word)
        if key is None:
            continue
        if key not in allowed:
            return "direction not in facts: %s" % word.lower()
        found_keys.append(key)
    for key in sorted(allowed):
        if key not in found_keys:
            return "missing direction word: %s" % key

    return None


def main(argv=None):
    parser = argparse.ArgumentParser(description="Check a brief against the facts it may state.")
    parser.add_argument("--facts", required=True, help="path to the facts JSON file")
    parser.add_argument("--draft", required=True, help="path to the draft text file")
    args = parser.parse_args(argv)

    try:
        with open(args.facts, encoding="utf-8") as handle:
            facts = json.load(handle)
        with open(args.draft, encoding="utf-8") as handle:
            draft = handle.read()
    except OSError as error:
        print("REJECT cannot read input: %s" % error.strerror)
        return 1

    try:
        reason = gate_reason(facts, draft)
    except ValueError as error:
        reason = "bad facts: %s" % error
    if reason:
        print("REJECT %s" % reason)
        return 1
    print("ACCEPT")
    return 0


if __name__ == "__main__":
    sys.exit(main())
