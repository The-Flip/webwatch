#!/usr/bin/env python3
"""Fetch a live web page and save it as a test fixture.

Usage:
    uv run python scripts/capture_fixture.py <url> [name]

Saves the page to ``tests/fixtures/<name>_<date>.html``. If ``name`` is omitted,
it is derived from the URL's host. This is a manual, network-using tool — it is
never invoked by the test suite. Re-capturing a fixture after a site changes is
how we notice the change: the affected extractor's tests then show what broke.

Phase A note: this uses ``httpx`` directly. Once ``webwatch/fetch.py`` exists it
should fetch through that boundary so capture and production share one path.
"""

from __future__ import annotations

import datetime as dt
import re
import sys
from pathlib import Path

import httpx

FIXTURES_DIR = Path(__file__).parent.parent / "tests" / "fixtures"
USER_AGENT = "webwatch/0.1 (+https://www.theflip.museum/; capturing a monitoring fixture)"


def slugify(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__)
        return 2

    url = argv[0]
    name = argv[1] if len(argv) > 1 else slugify(httpx.URL(url).host)
    today = dt.datetime.now(tz=dt.UTC).date().isoformat()

    response = httpx.get(url, headers={"User-Agent": USER_AGENT}, follow_redirects=True, timeout=30)
    response.raise_for_status()

    FIXTURES_DIR.mkdir(parents=True, exist_ok=True)
    out = FIXTURES_DIR / f"{name}_{today}.html"
    out.write_text(response.text, encoding="utf-8")
    print(f"Saved {len(response.text):,} bytes to {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
