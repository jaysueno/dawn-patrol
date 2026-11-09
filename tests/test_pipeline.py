"""The whole pipeline, end to end, with no model and no network."""
import os
import subprocess
import sys
from pathlib import Path

from dawn_patrol import fixtures

ROOT = Path(__file__).resolve().parents[1]
SPOTS = ("Cloud 9", "Uluwatu", "Pipeline")


def run_pipeline(fixtures_dir, out_dir):
    env = dict(os.environ)
    env.pop("LLM_URL", None)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return subprocess.run(
        [sys.executable, "-m", "dawn_patrol.run", "--offline", str(fixtures_dir),
         "--out", str(out_dir)],
        cwd=ROOT, env=env, capture_output=True, text=True, timeout=180)


def test_the_offline_pipeline_publishes_an_index_and_one_page_per_spot(tmp_path):
    fixtures.generate(7, tmp_path / "fx")
    result = run_pipeline(tmp_path / "fx", tmp_path / "site")
    assert result.returncode == 0, result.stderr

    site = tmp_path / "site"
    assert (site / "index.html").is_file()
    pages = sorted(path.name for path in site.glob("*.html") if path.name != "index.html")
    assert pages == ["cloud-9.html", "pipeline.html", "uluwatu.html"]

    blob = "\n".join((site / name).read_text(encoding="utf-8") for name in
                     ["index.html"] + pages)
    for spot in SPOTS:
        assert spot in blob


def test_every_page_carries_the_attribution_and_the_viewport_tag(tmp_path):
    fixtures.generate(7, tmp_path / "fx")
    assert run_pipeline(tmp_path / "fx", tmp_path / "site").returncode == 0
    for page in sorted((tmp_path / "site").glob("*.html")):
        text = page.read_text(encoding="utf-8")
        assert "Open-Meteo" in text, page.name
        assert "open-meteo.com" in text, page.name
        assert 'name="viewport"' in text, page.name


def test_the_stylesheet_carries_a_media_rule(tmp_path):
    fixtures.generate(7, tmp_path / "fx")
    assert run_pipeline(tmp_path / "fx", tmp_path / "site").returncode == 0
    css = (tmp_path / "site" / "site.css").read_text(encoding="utf-8")
    assert "@media" in css


def test_the_index_links_every_spot_page(tmp_path):
    fixtures.generate(7, tmp_path / "fx")
    assert run_pipeline(tmp_path / "fx", tmp_path / "site").returncode == 0
    index = (tmp_path / "site" / "index.html").read_text(encoding="utf-8")
    for name in ("cloud-9.html", "uluwatu.html", "pipeline.html"):
        assert 'href="%s"' % name in index


def test_each_spot_page_shows_its_three_line_brief_and_chart(tmp_path):
    fixtures.generate(7, tmp_path / "fx")
    assert run_pipeline(tmp_path / "fx", tmp_path / "site").returncode == 0
    page = (tmp_path / "site" / "cloud-9.html").read_text(encoding="utf-8")
    assert page.count("Swell ") >= 1
    assert "Best window " in page
    assert "<svg" in page
    assert "<polyline" in page


def test_a_second_build_replaces_the_first_and_leaves_no_temporary_folder(tmp_path):
    fixtures.generate(7, tmp_path / "fx")
    site = tmp_path / "site"
    assert run_pipeline(tmp_path / "fx", site).returncode == 0
    (site / "stale.html").write_text("old\n", encoding="utf-8")

    assert run_pipeline(tmp_path / "fx", site).returncode == 0
    assert not (site / "stale.html").exists()
    leftovers = [path.name for path in tmp_path.iterdir()
                 if ".tmp-" in path.name or ".old-" in path.name]
    assert leftovers == []
