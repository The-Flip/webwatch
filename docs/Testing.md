# Testing

Tests use [`pytest`](https://docs.pytest.org/). Run the fast suite with `make test`.

## Golden rule: don't fetch live websites by default

The default suite must be hermetic — no network. Mock HTTP at the transport boundary so tests are fast, deterministic, and safe. Pages under test are served from committed HTML fixtures.

```python
import httpx

def test_serves_fixture(serve_html):
    transport = serve_html("<html>...</html>")
    client = httpx.Client(transport=transport)
    assert client.get("https://example.test/").status_code == 200
```

The `conftest.py` helpers — `load_fixture(name)`, `serve_html(html)`, and `make_transport(handler)` — cover the common cases. Mock at the transport, not by patching `httpx` internals.

## Fixtures: one golden snapshot per source

- Commit **one** real HTML snapshot per source under `tests/fixtures/` (dated, e.g. `theflip_museum_2026-06-23.html`). This is the page as it actually looked.
- Refresh it with `scripts/capture_fixture.py` (manual, network-using; never run in `make test`). Re-capturing after a site change is how we _notice_ the change — the extractor tests then show what broke.
- **Do not commit separate "broken" fixtures.** Derive negative cases by mutating the golden HTML in-memory. This avoids fixture bloat and dual-maintenance.

## Prove every status by mutation

For each source/check, prove the full taxonomy from the one golden fixture:

```python
from bs4 import BeautifulSoup

def test_missing_hours_block_is_structure_changed():
    soup = BeautifulSoup(load_fixture("theflip_museum_2026-06-23.html"), "lxml")
    soup.select_one("[data-hours]").decompose()      # remove the region
    result = check_hours(serve(str(soup)))
    assert result.status is CheckStatus.STRUCTURE_CHANGED   # NOT a MISMATCH
```

Cover, per check:

- unchanged fixture → `OK`
- region removed → `STRUCTURE_CHANGED`
- value corrupted/unparseable → `PARSE_ERROR`
- value changed to a different valid value → `MISMATCH`
- body swapped for a challenge/empty-shell page → `BLOCKED`
- stale JSON-LD disagreeing with visible text → `MISMATCH` against the visible value

This is the heart of the suite: it pins down that a broken page is reported as broken, not as a false alarm.

## Time-dependent rules

Dynamic rules (recurring events) depend on "now". Pin the clock with `freezegun` (or pass a fixed `now`) relative to the fixture's capture date, so passing real time never breaks tests.

## Test organization

- Tests live in `tests/` and mirror the package: `webwatch/result.py` → `tests/test_result.py`; `webwatch/sources/theflip_museum.py` → `tests/test_theflip_museum.py`.
- Name tests descriptively (`test_missing_hours_block_is_structure_changed`) and give non-obvious ones a one-line docstring.
- Put shared fixtures/helpers in `tests/conftest.py`.
- Generate any secrets dynamically (`secrets.token_hex(16)`).

## Integration tests (live web)

Tests that genuinely need a live site must be marked:

```python
import pytest

@pytest.mark.integration
def test_theflip_museum_is_reachable():
    ...
```

- `make test` runs `pytest -m "not integration"` and **excludes** these.
- `make test-all` runs everything and requires network access.
- Keep integration tests read-only and minimal — prefer the hermetic fixture suite for behavior.

## TDD

- Fixing a bug: write a failing test that reproduces it first, then fix the code.
- New behavior: include tests; consider writing them first.
