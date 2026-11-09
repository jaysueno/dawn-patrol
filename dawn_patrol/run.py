"""Run the pipeline: fetch (or read fixtures), store, compute facts, write the brief, build.

    python3 -m dawn_patrol.run --offline fixtures/ --out site/   # no network, no model
    python3 -m dawn_patrol.run --fetch --out site/               # the real Open-Meteo pull

LLM_URL is read from the environment. Unset means the fixed template. Set means an
OpenAI-compatible endpoint; its draft still has to pass the gate. LLM_MODEL names the model
at that endpoint and defaults to local-model.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import urllib.parse
import urllib.request
from pathlib import Path

from dawn_patrol import brief, facts, site, store

MARINE_URL = "https://marine-api.open-meteo.com/v1/marine"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"

MARINE_HOURLY = "wave_height,wave_period,wave_direction"
FORECAST_HOURLY = "wind_speed_10m,wind_direction_10m"


def get_json(url, params, timeout=30):
    """One read-only GET against a public Open-Meteo endpoint."""
    full = url + "?" + urllib.parse.urlencode(params)
    with urllib.request.urlopen(full, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def fetch_into(directory):
    """Pull both endpoints for every spot and write responses like the fixtures writer does."""
    target = Path(directory)
    target.mkdir(parents=True, exist_ok=True)
    for spot in facts.load_spots():
        common = {
            "latitude": spot["latitude"],
            "longitude": spot["longitude"],
            "timezone": spot["timezone"],
            "forecast_days": 1,
        }
        marine = get_json(MARINE_URL, dict(common, hourly=MARINE_HOURLY))
        weather = get_json(FORECAST_URL, dict(common, hourly=FORECAST_HOURLY,
                                              wind_speed_unit="kmh"))
        for kind, payload in (("marine", marine), ("forecast", weather)):
            path = target / ("%s-%s.json" % (kind, spot["slug"]))
            path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return target


def bundles_from_db(con, llm_url=None, model="local-model"):
    """Facts and briefs for every spot, computed only from rows already in the database."""
    bundles = []
    for spot in facts.load_spots():
        hours = store.series(con, spot["name"])
        row = facts.facts_for(spot, hours)
        text, source = brief.choose_brief(row, llm_url, model=model)
        bundles.append({"spot": spot, "facts": row, "brief": text,
                        "source": source, "hours": hours})
    return bundles


def main(argv=None):
    parser = argparse.ArgumentParser(description="Fetch, store, and publish the dawn-patrol site.")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--offline", metavar="DIR", help="read recorded responses from this folder")
    source.add_argument("--fetch", action="store_true", help="pull the two Open-Meteo endpoints")
    parser.add_argument("--out", required=True, metavar="DIR", help="folder to publish the site to")
    parser.add_argument("--db", default="data/forecast.sqlite", help="SQLite file for the --fetch run")
    args = parser.parse_args(argv)

    llm_url = os.environ.get("LLM_URL") or None
    model = os.environ.get("LLM_MODEL") or "local-model"

    try:
        if args.offline:
            with tempfile.TemporaryDirectory(prefix="dawn-patrol-") as work:
                con = store.connect(Path(work) / "forecast.sqlite")
                try:
                    store.ingest(con, args.offline)
                    bundles = bundles_from_db(con, llm_url, model)
                    rows = store.total_rows(con)
                finally:
                    con.close()
        else:
            with tempfile.TemporaryDirectory(prefix="dawn-patrol-pull-") as work:
                fetch_into(work)
                con = store.connect(args.db)
                try:
                    store.ingest(con, work)
                    bundles = bundles_from_db(con, llm_url, model)
                    rows = store.total_rows(con)
                finally:
                    con.close()
        site.build(bundles, args.out)
    except (OSError, ValueError, KeyError) as error:
        print("dawn-patrol: %s" % error, file=sys.stderr)
        return 1

    print("dawn-patrol: %d spot(s), %d stored row(s), site in %s" % (len(bundles), rows, args.out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
