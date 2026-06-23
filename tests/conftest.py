"""Shared test fixtures and helpers.

All HTTP is mocked at the transport boundary (``httpx.MockTransport``) so the
suite is hermetic — no network. Pages under test are served from committed HTML
fixtures in ``tests/fixtures/``; negative cases are produced by mutating that
golden HTML in-memory rather than committing separate broken copies. See
``docs/Testing.md``.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import httpx
import pytest

FIXTURES_DIR = Path(__file__).parent / "fixtures"

Handler = Callable[[httpx.Request], httpx.Response]


def load_fixture(name: str) -> str:
    """Return the text of a committed fixture under ``tests/fixtures/``."""
    return (FIXTURES_DIR / name).read_text(encoding="utf-8")


@pytest.fixture
def fixtures_dir() -> Path:
    return FIXTURES_DIR


@pytest.fixture
def make_transport() -> Callable[[Handler], httpx.MockTransport]:
    """Return a factory that builds an ``httpx.MockTransport`` from a handler."""

    def _make(handler: Handler) -> httpx.MockTransport:
        return httpx.MockTransport(handler)

    return _make


@pytest.fixture
def serve_html() -> Callable[[str], httpx.MockTransport]:
    """Return a factory: given an HTML string, build a transport that serves it 200."""

    def _make(html: str, *, status_code: int = 200) -> httpx.MockTransport:
        def handler(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(status_code, html=html)

        return httpx.MockTransport(handler)

    return _make
