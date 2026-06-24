"""Tests for the run orchestration over fixture-backed transports (no network)."""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from webwatch.facts import load_facts
from webwatch.result import CheckStatus
from webwatch.run import run_checks

FIXTURES = Path(__file__).parent / "fixtures"
HOME = (FIXTURES / "theflip_museum_2026-06-23.html").read_text(encoding="utf-8")
VISIT = (FIXTURES / "theflip_museum_visit_2026-06-24.html").read_text(encoding="utf-8")
FACTS = load_facts("facts.yaml")


def _router() -> httpx.MockTransport:
    """Serve the right fixture per URL path, so each source sees its own page."""

    def handler(request: httpx.Request) -> httpx.Response:
        html = VISIT if request.url.path.rstrip("/") == "/visit" else HOME
        return httpx.Response(200, html=html)

    return httpx.MockTransport(handler)


def test_all_checks_ok_against_fixtures() -> None:
    from webwatch.result import EXIT_OK, exit_code

    results = run_checks(FACTS, transport=_router())
    # Field checks AND the recurring-event rule all pass against the current page.
    assert all(r.status is CheckStatus.OK for r in results), [
        (r.site, r.name, r.status) for r in results if r.status is not CheckStatus.OK
    ]
    assert {r.site for r in results} == {"theflip_museum", "theflip_museum_visit"}
    assert any(r.name == "weekly-repair-day" for r in results)
    assert exit_code(results) == EXIT_OK


def test_fetch_error_yields_one_fetch_error_per_check(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("webwatch.config.HTTP_MAX_RETRIES", 0)

    def boom(_req: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down")

    results = run_checks(FACTS, transport=httpx.MockTransport(boom))
    assert results
    assert all(r.status is CheckStatus.FETCH_ERROR for r in results)


def test_unknown_site_filter_runs_nothing() -> None:
    results = run_checks(FACTS, site="nonexistent", transport=_router())
    assert results == []


def test_fact_filter_runs_one_check() -> None:
    results = run_checks(FACTS, fact="email", transport=_router())
    assert [(r.site, r.name) for r in results] == [("theflip_museum", "email")]


def test_site_filter_visit_only() -> None:
    results = run_checks(FACTS, site="theflip_museum_visit", transport=_router())
    assert {r.site for r in results} == {"theflip_museum_visit"}
    # 7 hours checks + the recurring-event rule, all OK against the current page.
    assert len(results) == 8
    assert all(r.status is CheckStatus.OK for r in results)


def test_fact_filter_targets_a_rule_by_id() -> None:
    results = run_checks(FACTS, fact="weekly-repair-day", transport=_router())
    assert [(r.site, r.name) for r in results] == [("theflip_museum_visit", "weekly-repair-day")]
    assert results[0].status is CheckStatus.OK
