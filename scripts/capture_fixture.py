#!/usr/bin/env python3
"""Fetch a live web page (or API response) and save it as a test fixture.

Usage:
    uv run python scripts/capture_fixture.py <url> [name]
    uv run python scripts/capture_fixture.py --source <source-name>

Saves to ``tests/fixtures/<name>_<date>.<ext>``. If ``name`` is omitted, it is
derived from the URL's host. ``--source`` fetches exactly as that registered
source does — its own URL and request headers (e.g. an API key from ``.env``) —
and names the fixture after it. The extension is ``.json`` for a JSON response,
``.html`` otherwise. This is a manual, network-using tool — it is never invoked
by the test suite. Re-capturing a fixture after a site changes is how we notice
the change: the affected extractor's tests then show what broke.

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

from webwatch.fetch import FetchError, fetch
from webwatch.run import register_builtins
from webwatch.sources.registry import get_source

FIXTURES_DIR = Path(__file__).parent.parent / "tests" / "fixtures"


def slugify(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__)
        return 2

    headers: dict[str, str] = {}
    if argv[0] == "--source":
        if len(argv) != 2:
            print(__doc__)
            return 2
        register_builtins()
        source = get_source(argv[1])
        if source is None:
            print(f"Unknown source {argv[1]!r}.")
            return 2
        url, name = source.url, source.name
        try:
            headers = source.request_headers()
        except FetchError as err:
            print(f"Cannot fetch {name}: {err}")
            return 1
    else:
        url = argv[0]
        name = argv[1] if len(argv) > 1 else slugify(httpx.URL(url).host)
    today = dt.datetime.now(tz=dt.UTC).date().isoformat()

    result = fetch(url, headers=headers)
    if result.blocked:
        print(f"Refusing to save: page looks blocked ({result.block_reason}).")
        return 1

    content_type = result.headers.get("content-type", "").lower()
    extension = "json" if "json" in content_type else "html"
    FIXTURES_DIR.mkdir(parents=True, exist_ok=True)
    out = FIXTURES_DIR / f"{name}_{today}.{extension}"
    out.write_text(result.text, encoding="utf-8")
    print(f"Saved {len(result.text):,} bytes (HTTP {result.status_code}) to {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
