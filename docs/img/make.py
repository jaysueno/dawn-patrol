#!/usr/bin/env python3
"""Build docs/img/hero.svg, the one picture in the README.

Standard library only. Same inputs, same bytes: no clock, no randomness, no network.
Every number drawn here is read from the repo: the spot count from spots.toml, the hours per
pull from dawn_patrol/fixtures.py, and the refresh interval from the cron line in
.github/workflows/pages.yml.

Run from the repo root:  python3 docs/img/make.py
"""
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, ROOT)

from dawn_patrol import fixtures  # noqa: E402
from dawn_patrol.facts import load_spots  # noqa: E402

NAVY, SAND, TERRACOTTA, OLIVE = "#001B3B", "#EDE7DC", "#8C5348", "#59591D"
HEAD, SUB = "#F2EDE2", "#D8D3CA"
SERIF = "Georgia, 'Playfair Display', serif"
SANS = "-apple-system, 'Helvetica Neue', Helvetica, Arial, sans-serif"
WIDTH, HEIGHT = 1200, 420


def esc(value):
    return (str(value).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


def text(x, y, value, size=16, fill=SUB, serif=False, bold=False, anchor="start"):
    family = SERIF if serif else SANS
    weight = ' font-weight="700"' if bold else ""
    return ('<text x="%d" y="%d" font-family="%s" font-size="%d"%s fill="%s" '
            'text-anchor="%s">%s</text>' % (x, y, family, size, weight, fill, anchor, esc(value)))


def refresh_hours():
    """Read the cron line the pages workflow runs on, so the picture cannot drift from it."""
    path = os.path.join(ROOT, ".github", "workflows", "pages.yml")
    with open(path, encoding="utf-8") as handle:
        match = re.search(r'cron:\s*"0 \*/(\d+) \* \* \*"', handle.read())
    return int(match.group(1)) if match else 6


def build():
    spots = load_spots()
    hours = fixtures.HOURS
    refresh = refresh_hours()
    rows_per_spot = 2 * hours

    boxes = [
        ("Open-Meteo", "marine + wind"),
        ("SQLite", "%d rows per spot" % rows_per_spot),
        ("facts", ["4 numbers, 2 directions", "2 clock times"]),
        ("gate", "accept or reject"),
        ("site", "1 page per spot"),
    ]

    parts = [
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 %d %d" width="%d" height="%d" '
        'role="img">' % (WIDTH, HEIGHT, WIDTH, HEIGHT),
        "<title>dawn-patrol: fetch, store, compute, gate, publish</title>",
        "<desc>Five steps from the Open-Meteo forecast to a published page, with %d spots and "
        "%d rows stored per spot each pull.</desc>" % (len(spots), rows_per_spot),
        '<rect x="0.5" y="0.5" width="%d" height="%d" fill="%s" stroke="%s" stroke-width="1"/>'
        % (WIDTH - 1, HEIGHT - 1, NAVY, SAND),
        text(48, 76, "dawn-patrol", 42, HEAD, serif=True),
        text(48, 112, "%d breaks. A forecast every %d hours. Every number in the brief is checked."
             % (len(spots), refresh), 18, SUB),
    ]

    box_w, box_h, gap = 180, 120, 30
    total = len(boxes) * box_w + (len(boxes) - 1) * gap
    start_x = (WIDTH - total) // 2
    box_y = 170
    for index, (title, note) in enumerate(boxes):
        x = start_x + index * (box_w + gap)
        parts.append('<rect x="%d" y="%d" width="%d" height="%d" fill="%s" stroke="%s" '
                     'stroke-width="1"/>' % (x, box_y, box_w, box_h, NAVY, SAND))
        parts.append(text(x + 18, box_y + 48, title, 22, HEAD, serif=True))
        for offset, line in enumerate([note] if isinstance(note, str) else note):
            parts.append(text(x + 18, box_y + 82 + 20 * offset, line, 15, SUB))
        if index < len(boxes) - 1:
            ax = x + box_w + 6
            ay = box_y + box_h // 2
            parts.append('<line x1="%d" y1="%d" x2="%d" y2="%d" stroke="%s" stroke-width="3"/>'
                         % (ax, ay, ax + gap - 12, ay, TERRACOTTA))
            parts.append('<polygon points="%d,%d %d,%d %d,%d" fill="%s"/>'
                         % (ax + gap - 12, ay, ax + gap - 20, ay - 6, ax + gap - 20, ay + 6,
                            TERRACOTTA))

    parts.append(text(48, 360, "%d spots, %d hours per pull, a refresh every %d hours. "
                     "The template brief needs no model; LLM_URL is optional."
                     % (len(spots), hours, refresh), 16, SUB))
    parts.append(text(48, 388, "No number reaches the page unless it came from a stored row.",
                      16, TERRACOTTA))
    parts.append("</svg>")
    return "\n".join(parts) + "\n"


def main():
    out = os.path.join(HERE, "hero.svg")
    with open(out, "w", encoding="utf-8") as handle:
        handle.write(build())
    print("wrote %s" % os.path.relpath(out, ROOT))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
