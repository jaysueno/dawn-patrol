"""Keep every pull in SQLite, and make ingesting the same pull twice a no-op.

Two tables:

    pulls     one row per ingest, keyed by the sha256 of the response bytes
    forecast  one row per spot, per response kind, per forecast hour

The pull is keyed by a hash of the bytes, not by a wall clock. That is what makes the store
idempotent: the same recorded responses produce the same hash, so the second ingest inserts
nothing and the row count does not move.

    python3 -m dawn_patrol.store --db data/forecast.sqlite --ingest fixtures/

prints exactly one line: NEW_ROWS <n> TOTAL_ROWS <m>, where n is the number of rows this run
inserted and m is the row count across every user table in the file after the run.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
import sys
from pathlib import Path

from dawn_patrol.facts import load_spots

FILENAME_RE = re.compile(r"^(marine|forecast)-(.+)\.json$")

SCHEMA = """
CREATE TABLE IF NOT EXISTS pulls (
    seq INTEGER PRIMARY KEY,
    sha256 TEXT NOT NULL UNIQUE,
    first_valid_utc TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS forecast (
    pull_sha256 TEXT NOT NULL,
    spot TEXT NOT NULL,
    kind TEXT NOT NULL,
    valid_utc TEXT NOT NULL,
    wave_height_m REAL,
    wave_period_s REAL,
    wave_direction_deg INTEGER,
    wind_speed_kmh REAL,
    wind_direction_deg INTEGER,
    PRIMARY KEY (pull_sha256, spot, kind, valid_utc)
);
"""


def connect(db_path):
    """Open (or create) the database and make sure the two tables exist."""
    path = Path(db_path)
    if path.parent and str(path.parent) not in ("", "."):
        path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(path))
    con.executescript(SCHEMA)
    con.commit()
    return con


def user_tables(con):
    return [row[0] for row in con.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]


def total_rows(con):
    """Rows across every user table, the number the store reports as TOTAL_ROWS."""
    total = 0
    for name in user_tables(con):
        total += con.execute('SELECT COUNT(*) FROM "%s"' % name.replace('"', '""')).fetchone()[0]
    return total


def _read_payloads(fixtures_dir):
    files = sorted(Path(fixtures_dir).glob("*.json"))
    if not files:
        raise ValueError("no JSON files in %s" % fixtures_dir)
    payloads = []
    for path in files:
        match = FILENAME_RE.match(path.name)
        if not match:
            raise ValueError("fixture file name is not marine-<slug>.json or forecast-<slug>.json: %s"
                             % path.name)
        payloads.append((match.group(1), match.group(2), path.name, path.read_bytes()))
    return payloads


def ingest(con, fixtures_dir):
    """Ingest one folder of recorded responses. Returns the number of rows inserted."""
    payloads = _read_payloads(fixtures_dir)
    by_slug = {spot["slug"]: spot for spot in load_spots()}
    digest = hashlib.sha256()
    decoded = []
    first_valid = None
    for kind, slug, name, raw in payloads:
        if slug not in by_slug:
            raise ValueError("fixture for unknown spot slug: %s" % slug)
        digest.update(name.encode("utf-8"))
        digest.update(b"\0")
        digest.update(raw)
        body = json.loads(raw)
        hourly = body["hourly"]
        times = hourly["time"]
        if first_valid is None or times[0] < first_valid:
            first_valid = times[0]
        decoded.append((kind, by_slug[slug]["name"], hourly))

    sha = digest.hexdigest()
    cursor = con.cursor()
    cursor.execute("INSERT OR IGNORE INTO pulls (sha256, first_valid_utc) VALUES (?, ?)",
                   (sha, first_valid))
    inserted = cursor.rowcount

    for kind, spot, hourly in decoded:
        times = hourly["time"]
        for index, valid in enumerate(times):
            if kind == "marine":
                row = (sha, spot, kind, valid,
                       hourly["wave_height"][index], hourly["wave_period"][index],
                       hourly["wave_direction"][index], None, None)
            else:
                row = (sha, spot, kind, valid,
                       None, None, None,
                       hourly["wind_speed_10m"][index], hourly["wind_direction_10m"][index])
            cursor.execute(
                "INSERT OR IGNORE INTO forecast"
                " (pull_sha256, spot, kind, valid_utc, wave_height_m, wave_period_s,"
                "  wave_direction_deg, wind_speed_kmh, wind_direction_deg)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", row)
            inserted += cursor.rowcount

    con.commit()
    return inserted


def latest_pull(con):
    row = con.execute("SELECT sha256 FROM pulls ORDER BY seq DESC LIMIT 1").fetchone()
    return row[0] if row else None


def series(con, spot_name, pull=None):
    """Merged hourly rows for one spot, marine and wind side by side, oldest first."""
    sha = pull or latest_pull(con)
    if sha is None:
        return []
    rows = con.execute(
        "SELECT m.valid_utc, m.wave_height_m, m.wave_period_s, m.wave_direction_deg,"
        "       f.wind_speed_kmh, f.wind_direction_deg"
        " FROM forecast m"
        " LEFT JOIN forecast f"
        "   ON f.pull_sha256 = m.pull_sha256 AND f.spot = m.spot"
        "  AND f.valid_utc = m.valid_utc AND f.kind = 'forecast'"
        " WHERE m.kind = 'marine' AND m.spot = ? AND m.pull_sha256 = ?"
        " ORDER BY m.valid_utc", (spot_name, sha)).fetchall()
    return [
        {
            "valid_utc": row[0],
            "wave_height_m": row[1],
            "wave_period_s": row[2],
            "wave_direction_deg": row[3],
            "wind_speed_kmh": row[4],
            "wind_direction_deg": row[5],
        }
        for row in rows
    ]


def main(argv=None):
    parser = argparse.ArgumentParser(description="Store recorded Open-Meteo responses in SQLite.")
    parser.add_argument("--db", default="data/forecast.sqlite", help="path to the SQLite file")
    parser.add_argument("--ingest", required=True, metavar="DIR", help="folder of recorded responses")
    args = parser.parse_args(argv)

    try:
        con = connect(args.db)
    except (OSError, sqlite3.Error) as error:
        print("cannot open the database: %s" % error, file=sys.stderr)
        return 1
    try:
        inserted = ingest(con, args.ingest)
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as error:
        print("cannot ingest %s: %s" % (args.ingest, error), file=sys.stderr)
        return 1
    print("NEW_ROWS %d TOTAL_ROWS %d" % (inserted, total_rows(con)))
    con.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
