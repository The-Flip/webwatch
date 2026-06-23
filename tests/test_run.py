"""Tests for the run orchestration over a fixture-backed transport (no network)."""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from webwatch.facts import load_facts
from webwatch.result import CheckStatus
from webwatch.run import run_checks

FIXTURE = Path(__file__).parent / "fixtures" / "theflip_museum_2026-06-23.html"
FACTS = load_facts("facts.yaml")


def _serve(html: str) -> httpx.MockTransport:
    return httpx.MockTransport(lambda _req: httpx.Response(200, html=html))


def test_run_all_ok_against_fixture() -> None:
    results = run_checks(FACTS, transport=_serve(FIXTURE.read_text(encoding="utf-8")))
    assert results
    assert all(r.status is CheckStatus.OK for r in results)


def test_fetch_error_yields_one_fetch_error_per_check(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("webwatch.config.HTTP_MAX_RETRIES", 0)

    def boom(_req: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down")

    results = run_checks(FACTS, transport=httpx.MockTransport(boom))
    assert results
    assert all(r.status is CheckStatus.FETCH_ERROR for r in results)


def test_unknown_site_filter_runs_nothing() -> None:
    results = run_checks(FACTS, site="nonexistent", transport=_serve("<html></html>"))
    assert results == []


def test_fact_filter_runs_one_check() -> None:
    results = run_checks(FACTS, fact="email", transport=_serve(FIXTURE.read_text(encoding="utf-8")))
    assert [r.name for r in results] == ["email"]
