"""Render the static site: an index page, one page per spot, one stylesheet.

Plain HTML and one inline SVG chart per spot. No framework, no script, no image request. The
pages are written into a temporary folder next to the output and then swapped into place, so
a reader never sees a half-built site and a failed build leaves the last good one alone.

Every page carries the Open-Meteo attribution and a link to open-meteo.com.
"""
from __future__ import annotations

import html
import math
import os
import shutil
import time
from pathlib import Path

from dawn_patrol.facts import fmt_number

ATTRIBUTION = ('Weather data by <a href="https://open-meteo.com/">Open-Meteo.com</a>, '
               'CC BY 4.0. Marine forecast and 10 m wind, refreshed every six hours.')

SANS = "-apple-system, 'Helvetica Neue', Helvetica, Arial, sans-serif"


def esc(value):
    return html.escape(str(value), quote=True)


def _page(title, body):
    return (
        "<!doctype html>\n"
        '<html lang="en">\n'
        "<head>\n"
        '<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        "<title>%s</title>\n"
        '<link rel="stylesheet" href="site.css">\n'
        "</head>\n"
        "<body>\n"
        "%s\n"
        '<footer class="wrap foot">\n'
        "<p>%s</p>\n"
        "<p>The breaks are public surf spots. Nothing here is advice; check the water yourself.</p>\n"
        "</footer>\n"
        "</body>\n"
        "</html>\n"
    ) % (esc(title), body, ATTRIBUTION)


def chart(hours, facts):
    """One inline SVG line chart of wave height over the stored hours."""
    usable = [row for row in hours if row.get("wave_height_m") is not None]
    if len(usable) < 2:
        return '<p class="source">No stored swell hours to chart.</p>'
    width, height = 480, 260
    left, right, top, bottom = 52, 14, 20, 40
    plot_w, plot_h = width - left - right, height - top - bottom
    heights = [float(row["wave_height_m"]) for row in usable]
    ymax = max(2, math.ceil(max(heights) + 0.3))
    step = plot_w / (len(usable) - 1) if len(usable) > 1 else plot_w

    def x(index):
        return left + index * step

    def y(value):
        return top + (1.0 - float(value) / ymax) * plot_h

    parts = [
        '<svg viewBox="0 0 %d %d" role="img" xmlns="http://www.w3.org/2000/svg">' % (width, height),
        "<title>Wave height for %s over the stored hours</title>" % esc(facts["spot"]),
        "<desc>Wave height runs from %s to %s metres. The shaded band is the best window, "
        "%s to %s.</desc>" % (fmt_number(facts["wave_height_min_m"]),
                              fmt_number(facts["wave_height_max_m"]),
                              facts["best_window_start"], facts["best_window_end"]),
    ]

    # Grid and y labels.
    for value in range(0, ymax + 1):
        gy = y(value)
        parts.append('<line x1="%d" y1="%.1f" x2="%d" y2="%.1f" stroke="#D8D3CA" '
                     'stroke-opacity="0.22" stroke-width="1"/>' % (left, gy, left + plot_w, gy))
        parts.append('<text x="%d" y="%.1f" text-anchor="end" font-family="%s" font-size="16" '
                     'fill="#D8D3CA">%d</text>' % (left - 10, gy + 6, SANS, value))
    parts.append('<text x="%d" y="%d" text-anchor="end" font-family="%s" font-size="16" '
                 'fill="#D8D3CA">metres</text>' % (left + plot_w, top - 6, SANS))

    # The best window, two hours wide.
    starts = [index for index, row in enumerate(usable)
              if row["valid_utc"][11:16] == facts["best_window_start"]]
    if starts:
        band_x = x(starts[0])
        parts.append('<rect x="%.1f" y="%d" width="%.1f" height="%d" fill="#59591D" '
                     'fill-opacity="0.38"/>' % (band_x, top, step * 2, plot_h))
        parts.append('<text x="%.1f" y="%d" text-anchor="middle" font-family="%s" font-size="15" '
                     'fill="#F2EDE2">best window</text>'
                     % (band_x + step, top + 20, SANS))

    # X labels every six hours.
    for index in (0, 6, 12, 18, len(usable) - 1):
        if index >= len(usable):
            continue
        anchor = "start" if index == 0 else ("end" if index == len(usable) - 1 else "middle")
        parts.append('<text x="%.1f" y="%d" text-anchor="%s" font-family="%s" font-size="16" '
                     'fill="#D8D3CA">%s</text>'
                     % (x(index), height - 14, anchor, SANS, usable[index]["valid_utc"][11:16]))

    # The line.
    points = " ".join("%.1f,%.1f" % (x(index), y(value)) for index, value in enumerate(heights))
    parts.append('<polyline points="%s" fill="none" stroke="#8C5348" stroke-width="3" '
                 'stroke-linejoin="round" stroke-linecap="round"/>' % points)
    parts.append("</svg>")
    return "".join(parts)


def _brief_block(text):
    lines = [line for line in text.strip().splitlines() if line.strip()]
    return "<br>".join(esc(line) for line in lines)


def index_page(bundles):
    cards = []
    for bundle in bundles:
        spot, facts = bundle["spot"], bundle["facts"]
        cards.append(
            '<a class="card" href="%s.html">\n'
            "<h2>%s</h2>\n"
            '<p class="where">%s</p>\n'
            '<p class="brief">%s</p>\n'
            '<p class="more">Open the forecast</p>\n'
            "</a>" % (esc(spot["slug"]), esc(spot["name"]), esc(spot.get("place", "")),
                      _brief_block(bundle["brief"])))
    body = (
        '<header class="masthead">\n<div class="wrap">\n'
        '<p class="kicker">dawn patrol</p>\n'
        "<h1>Three breaks, one honest brief</h1>\n"
        '<p class="lede">Every six hours the pipeline pulls the marine and wind forecast, stores '
        "it in SQLite, and publishes one page per break. Every number on the page comes from a "
        "stored row, and the gate refuses a brief that says anything else.</p>\n"
        "</div>\n</header>\n"
        '<main class="wrap">\n<div class="cards">\n%s\n</div>\n</main>' % "\n".join(cards))
    return _page("dawn-patrol: three breaks, one honest brief", body)


def spot_page(bundle):
    spot, facts, hours = bundle["spot"], bundle["facts"], bundle["hours"]
    source = ("The local model wrote these three lines. The gate passed them, so every number "
              "came from the stored row." if bundle.get("source") == "model"
              else "The fixed template wrote these three lines, straight from the stored row.")
    stats = (
        ("Swell low", "%s m" % fmt_number(facts["wave_height_min_m"])),
        ("Swell high", "%s m" % fmt_number(facts["wave_height_max_m"])),
        ("Period", "%s s" % fmt_number(facts["period_s"])),
        ("Swell from", esc(facts["swell_direction"])),
        ("Wind", "%s km/h" % fmt_number(facts["wind_speed_kmh"])),
        ("Wind state", esc(facts["wind_direction"])),
    )
    stat_html = "\n".join('<div class="stat"><dt>%s</dt><dd>%s</dd></div>' % pair for pair in stats)
    body = (
        '<header class="masthead">\n<div class="wrap">\n'
        '<p class="kicker"><a href="index.html">dawn patrol</a></p>\n'
        "<h1>%s</h1>\n"
        '<p class="where">%s. Latitude %s, longitude %s. Best swell %s, best wind %s.</p>\n'
        "</div>\n</header>\n"
        '<main class="wrap">\n'
        '<section class="panel">\n<h2>The brief</h2>\n'
        '<p class="brief big">%s</p>\n<p class="source">%s</p>\n</section>\n'
        '<section class="panel">\n<h2>Swell, next 24 hours</h2>\n'
        '<figure>%s</figure>\n</section>\n'
        '<section class="panel">\n<h2>The numbers</h2>\n'
        '<div class="stats">%s</div>\n'
        '<p class="source">Window %s to %s, the best two hours by the score in '
        "dawn_patrol/facts.py.</p>\n</section>\n"
        "</main>"
    ) % (esc(spot["name"]), esc(spot.get("place", "")), fmt_number(spot["latitude"]),
         fmt_number(spot["longitude"]), esc(spot["best_swell_direction"]),
         esc(spot["best_wind_direction"]), _brief_block(bundle["brief"]), esc(source),
         chart(hours, facts), stat_html,
         esc(facts["best_window_start"]), esc(facts["best_window_end"]))
    return _page("%s: dawn-patrol" % spot["name"], body)


def stylesheet():
    return """/* dawn-patrol. Four colors from the brand palette and nothing else. */
:root {
  --navy: #001B3B;
  --sand: #EDE7DC;
  --terracotta: #8C5348;
  --olive: #59591D;
  --ink: #F2EDE2;
  --dim: #D8D3CA;
}
* { box-sizing: border-box; }
body {
  margin: 0;
  background: var(--sand);
  color: var(--navy);
  font-family: -apple-system, 'Helvetica Neue', Helvetica, Arial, sans-serif;
  line-height: 1.5;
}
.wrap { max-width: 1080px; margin: 0 auto; padding: 26px 28px; }
.masthead { background: var(--navy); color: var(--ink); border-bottom: 1px solid var(--sand); }
.masthead h1 {
  font-family: Georgia, 'Playfair Display', serif;
  font-weight: 400;
  font-size: 44px;
  margin: 8px 0 10px;
}
.kicker {
  margin: 0;
  font-size: 12px;
  letter-spacing: 0.14em;
  text-transform: uppercase;
  color: var(--dim);
}
.kicker a { color: var(--dim); text-decoration: none; }
.lede { margin: 0; max-width: 700px; color: var(--dim); }
.where { margin: 0 0 14px; font-size: 13px; color: var(--dim); }
.cards { display: grid; grid-template-columns: repeat(3, 1fr); gap: 20px; padding: 28px 0; }
.card {
  display: block;
  padding: 22px;
  background: var(--navy);
  color: var(--ink);
  border: 1px solid var(--sand);
  text-decoration: none;
  min-height: 72px;
}
.card h2 {
  margin: 0 0 2px;
  font-family: Georgia, 'Playfair Display', serif;
  font-weight: 400;
  font-size: 26px;
}
.card .brief { margin: 0; font-size: 15px; color: var(--ink); }
.card .more { margin: 16px 0 0; font-size: 14px; color: var(--sand); text-decoration: underline; }
.panel {
  margin: 0 0 20px;
  padding: 22px;
  background: var(--navy);
  color: var(--ink);
  border: 1px solid var(--sand);
}
.panel h2 {
  margin: 0 0 14px;
  font-family: Georgia, 'Playfair Display', serif;
  font-weight: 400;
  font-size: 22px;
}
.brief { margin: 0; }
.brief.big { font-size: 19px; line-height: 1.6; }
.source { margin: 14px 0 0; font-size: 13px; color: var(--dim); }
figure { margin: 0; }
svg { display: block; width: 100%; max-width: 720px; height: auto; margin: 0 auto; }
.stats { display: grid; grid-template-columns: repeat(3, 1fr); gap: 16px; }
.stat dt {
  margin: 0;
  font-size: 12px;
  letter-spacing: 0.1em;
  text-transform: uppercase;
  color: var(--dim);
}
.stat dd { margin: 2px 0 0; font-size: 28px; font-weight: 600; }
.foot {
  background: var(--navy);
  color: var(--dim);
  border-top: 1px solid var(--sand);
  font-size: 13px;
}
.foot a { color: var(--sand); }
.foot p { margin: 4px 0; }
@media (max-width: 700px) {
  .wrap { padding: 18px 16px; }
  .masthead h1 { font-size: 30px; }
  .cards { grid-template-columns: 1fr; gap: 14px; padding: 18px 0; }
  .card { padding: 18px; }
  .panel { padding: 16px; }
  .brief.big { font-size: 16px; }
  .stats { grid-template-columns: repeat(2, 1fr); }
  .stat dd { font-size: 22px; }
}
"""


def _swap(tmp, out, stamp):
    old = None
    if out.exists() or out.is_symlink():
        old = out.parent / ("%s.old-%s" % (out.name, stamp))
        os.replace(str(out), str(old))
    try:
        os.replace(str(tmp), str(out))
    except OSError:
        if old is not None:
            os.replace(str(old), str(out))
        raise
    if old is not None:
        if old.is_dir():
            shutil.rmtree(str(old), ignore_errors=True)
        else:
            old.unlink()


def build(bundles, out_dir):
    """Write the whole site, then swap it into place. Returns the folder it published."""
    out = Path(out_dir)
    out.parent.mkdir(parents=True, exist_ok=True)
    stamp = "%d-%d" % (os.getpid(), time.time_ns())
    tmp = out.parent / ("%s.tmp-%s" % (out.name, stamp))
    tmp.mkdir()
    try:
        (tmp / "site.css").write_text(stylesheet(), encoding="utf-8")
        (tmp / "index.html").write_text(index_page(bundles), encoding="utf-8")
        for bundle in bundles:
            name = "%s.html" % bundle["spot"]["slug"]
            (tmp / name).write_text(spot_page(bundle), encoding="utf-8")
        _swap(tmp, out, stamp)
    except BaseException:
        shutil.rmtree(str(tmp), ignore_errors=True)
        raise
    return out
