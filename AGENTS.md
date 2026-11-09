# AGENTS.md

Instructions for an AI agent working in this repo.

## Install

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
```

Python 3.11 or newer. The pipeline uses only the standard library. `requirements.txt` holds the
test dependency (`pytest`) and nothing else.

## Run

```bash
python3 -m dawn_patrol.fixtures --seed 7 --out fixtures/    # recorded API responses, no network
python3 -m dawn_patrol.run --offline fixtures/ --out site/  # the whole pipeline, no network
python3 -m dawn_patrol.run --fetch --out site/              # the real Open-Meteo pull
python3 -m dawn_patrol.store --db data/forecast.sqlite --ingest fixtures/
python3 -m dawn_patrol.gate --facts facts.json --draft draft.txt
python3 docs/img/make.py                                    # rebuild the README picture
```

Three settings, all read from the environment: `LLM_URL` (unset means the fixed template),
`LLM_MODEL` (optional, defaults to `local-model`) and `LLM_TIMEOUT` (optional request timeout in
seconds, defaults to 60). A brief written by a model still goes through the gate, and a rejected
draft falls back to the template.

## Test

```bash
.venv/bin/python -m pytest -q
```

CI runs the same `pytest` on Python 3.11 and 3.12 (`.github/workflows/ci.yml`). Every test is
offline. Tests that need model output pass a fake transport function into `brief.choose_brief`;
nothing opens a socket.

## Where you may edit

- `dawn_patrol/`: the pipeline. A new behavior needs a new assertion in `tests/`.
- `tests/`: the test suite.
- `spots.toml`: the break list. Adding a spot is one `[[spots]]` block.
- `docs/img/make.py`: the picture is built from the repo, so a number in it is a number you can
  check. Rebuild it after changing the spot list or the hours per pull.
- `README.md` and `AGENTS.md`: plain technical prose.

## Where you may not edit

- The opening story under the README title. It is the owner's words.
- `LICENSE`.

## Never

- Never let a number reach a page or a brief unless it came from a stored row. The gate is the
  floor, not the whole rule.
- Never weaken the gate to make a draft pass. If a model cannot write an honest brief, the
  template is the answer.
- Never call the network in a test, and never give a test a live fixture. `dawn_patrol.fixtures`
  is the only source of API data in the test suite.
- Never put an API key, a token, an address or a personal name in the repo, a test or a doc.
  Write `localhost`.
- Never commit `.venv/`, `site/`, `data/` or `*.sqlite`. They are in `.gitignore`.
- Never use em dashes in prose.

## Before each commit

Run an identity and secret scan over the tree and the history, then run `pytest`.
