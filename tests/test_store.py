"""The store keeps every pull and ingesting the same pull twice adds nothing."""
import os
import re
import sqlite3
import subprocess
import sys
from pathlib import Path

from dawn_patrol import facts, fixtures, store

ROOT = Path(__file__).resolve().parents[1]
LINE = re.compile(r"NEW_ROWS (\d+) TOTAL_ROWS (\d+)\s*")


def run_store(db, folder):
    env = dict(os.environ)
    env.pop("LLM_URL", None)
    result = subprocess.run(
        [sys.executable, "-m", "dawn_patrol.store", "--db", str(db), "--ingest", str(folder)],
        cwd=ROOT, env=env, capture_output=True, text=True, timeout=120)
    return result, LINE.fullmatch(result.stdout)


def independent_total(path):
    con = sqlite3.connect(str(path))
    try:
        tables = [row[0] for row in con.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'")]
        return sum(con.execute('SELECT COUNT(*) FROM "%s"' % name).fetchone()[0] for name in tables)
    finally:
        con.close()


def test_store_is_idempotent(tmp_path):
    fixtures.generate(7, tmp_path / "fx")
    db = tmp_path / "forecast.sqlite"

    first, match = run_store(db, tmp_path / "fx")
    assert first.returncode == 0, first.stderr
    assert match, first.stdout
    new_rows, total_rows = int(match.group(1)), int(match.group(2))
    assert new_rows >= 1
    assert total_rows == independent_total(db)

    second, match = run_store(db, tmp_path / "fx")
    assert second.returncode == 0, second.stderr
    assert match, second.stdout
    assert int(match.group(1)) == 0
    assert int(match.group(2)) == total_rows
    assert independent_total(db) == total_rows


def test_the_series_merges_both_response_kinds(tmp_path):
    fixtures.generate(7, tmp_path / "fx")
    con = store.connect(tmp_path / "series.sqlite")
    store.ingest(con, tmp_path / "fx")
    rows = store.series(con, "Cloud 9")
    assert len(rows) == 24
    assert rows[0]["valid_utc"] == "2026-11-09T00:00"
    for row in rows:
        assert row["wave_height_m"] is not None
        assert row["wind_speed_kmh"] is not None
    con.close()


def test_the_schema_has_every_column_the_facts_cite(tmp_path):
    con = store.connect(tmp_path / "schema.sqlite")
    columns = {row[1] for row in con.execute("PRAGMA table_info(forecast)")}
    con.close()
    sources = list(facts.NUMBER_SOURCES.values()) + list(facts.DIRECTION_SOURCES.values())
    for source in sources:
        table, column = source.split(".")
        assert table == "forecast"
        assert column in columns, source
