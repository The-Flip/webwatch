#!/usr/bin/env python3
"""Fetch a live web page and save it as a test fixture.

Usage:
    uv run python scripts/capture_fixture.py <url> [name]

Saves the page to ``tests/fixtures/<name>_<date>.html``. If ``name`` is omitted,
it is derived from the URL's host. This is a manual, network-using tool — it is
never invoked by the test suite. Re-capturing a fixture after a site changes is
how we notice the change: the affected extractor's tests then show what broke.

Fetching goes through ``webwatch.fetch.fetch`` so a captured fixture sees the same
User-Agent, timeout, and redirect behavior as a production run. If the page comes
back blocked (a challenge/empty shell), we refuse to save it as a "golden" fixture.
"""

from __future__ import annotations

import datetime as dt
import re
import sys
from pathlib import Path

import httpx

from webwatch.fetch import fetch

FIXTURES_DIR = Path(__file__).parent.parent / "tests" / "fixtures"


def slugify(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__)
        return 2

    url = argv[0]
    name = argv[1] if len(argv) > 1 else slugify(httpx.URL(url).host)
    today = dt.datetime.now(tz=dt.UTC).date().isoformat()

    result = fetch(url)
    if result.blocked:
        print(f"Refusing to save: page looks blocked ({result.block_reason}).")
        return 1

    FIXTURES_DIR.mkdir(parents=True, exist_ok=True)
    out = FIXTURES_DIR / f"{name}_{today}.html"
    out.write_text(result.text, encoding="utf-8")
    print(f"Saved {len(result.text):,} bytes (HTTP {result.status_code}) to {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
