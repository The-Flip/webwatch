"""Tests for the run orchestration over fixture-backed transports (no network)."""

from __future__ import annotations

import datetime as dt
import secrets
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx
import pytest

from webwatch.facts import load_facts
from webwatch.result import CheckStatus
from webwatch.run import run_checks

FIXTURES = Path(__file__).parent / "fixtures"
HOME = (FIXTURES / "theflip_museum_2026-06-24.html").read_text(encoding="utf-8")
VISIT = (FIXTURES / "theflip_museum_visit_2026-06-24.html").read_text(encoding="utf-8")
APPLE_MAPS = (FIXTURES / "apple_maps_2026-09-26.html").read_text(encoding="utf-8")
GOOGLE_MAPS = (FIXTURES / "google_maps_2026-09-28.json").read_text(encoding="utf-8")
FACTS = load_facts("facts.yaml")
# Pinned to the fixtures' capture date so the expired-events check is deterministic
# (the listed events — Jun 27, Jul 4, Jul 11 — are all upcoming as of this date).
NOW = dt.datetime(2026, 6, 24, 12, 0, tzinfo=ZoneInfo("America/Chicago"))


def _router(*, apple_maps: str = APPLE_MAPS) -> httpx.MockTransport:
    """Serve the right fixture per host and path, so each source sees its own page."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "places.googleapis.com":
            return httpx.Response(
                200, text=GOOGLE_MAPS, headers={"content-type": "application/json"}
            )
        if request.url.host == "maps.apple.com":
            html = apple_maps
        elif request.url.path.rstrip("/") == "/visit":
            html = VISIT
        else:
            html = HOME
        return httpx.Response(200, html=html)

    return httpx.MockTransport(handler)


@pytest.fixture(autouse=True)
def _google_places_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("webwatch.config.GOOGLE_PLACES_API_KEY", secrets.token_hex(16))


def test_all_checks_ok_against_fixtures() -> None:
    from webwatch.result import EXIT_OK, exit_code

    results = run_checks(FACTS, transport=_router(), now=NOW)
    # Field checks, the recurring-event rule, AND the expired-events check all pass.
    assert all(r.status is CheckStatus.OK for r in results), [
        (r.site, r.name, r.status) for r in results if r.status is not CheckStatus.OK
    ]
    assert {r.site for r in results} == {
        "theflip_museum",
        "theflip_museum_visit",
        "apple_maps",
        "google_maps",
    }
    assert any(r.name == "weekly-repair-day" for r in results)
    assert any(r.name == "expired_events" for r in results)
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
    results = run_checks(FACTS, site="theflip_museum_visit", transport=_router(), now=NOW)
    assert {r.site for r in results} == {"theflip_museum_visit"}
    # 7 hours checks + the recurring-event rule + the expired-events check, all OK.
    assert len(results) == 9
    assert all(r.status is CheckStatus.OK for r in results)


def test_fact_filter_targets_a_rule_by_id() -> None:
    results = run_checks(FACTS, fact="weekly-repair-day", transport=_router(), now=NOW)
    # The rule runs on every events-providing source (both pages list the repair day).
    assert {(r.site, r.name) for r in results} == {
        ("theflip_museum", "weekly-repair-day"),
        ("theflip_museum_visit", "weekly-repair-day"),
    }
    assert all(r.status is CheckStatus.OK for r in results)


def test_fact_filter_targets_expired_events() -> None:
    results = run_checks(FACTS, fact="expired_events", transport=_router(), now=NOW)
    assert {r.site for r in results} == {"theflip_museum", "theflip_museum_visit"}
    assert all(r.name == "expired_events" and r.status is CheckStatus.OK for r in results)


def test_one_crashing_check_does_not_kill_the_run(monkeypatch: pytest.MonkeyPatch) -> None:
    """An unexpected crash in one check becomes STRUCTURE_CHANGED; the rest still run."""
    import webwatch.run as run_module

    def boom(*_a: object, **_k: object) -> object:
        raise AttributeError("the page changed drastically")

    monkeypatch.setattr(run_module, "check_expired_events", boom)
    results = run_checks(FACTS, transport=_router(), now=NOW)

    expired = [r for r in results if r.name == "expired_events"]
    assert expired and all(r.status is CheckStatus.STRUCTURE_CHANGED for r in expired)
    # Other checks still ran (the crash didn't abort the whole run).
    assert any(r.name == "email" and r.status is CheckStatus.OK for r in results)


# --- check prerequisites (Check.requires) -----------------------------------------


def _other_business() -> str:
    """The Apple Maps page, but for a business with a different name and hours."""
    html = APPLE_MAPS.replace(">The Flip</h1>", ">Flip Side</h1>")
    return html.replace("<span>10:00</span>", "<span>9:00</span>")


def test_failed_identity_gates_dependent_checks() -> None:
    results = run_checks(FACTS, site="apple_maps", transport=_router(apple_maps=_other_business()))
    by_name = {r.name: r for r in results}
    assert by_name["name"].status is CheckStatus.MISMATCH
    # Hours differ too, but must not be asserted against another business's page.
    assert by_name["hours.monday"].status is CheckStatus.STRUCTURE_CHANGED
    assert "prerequisite" in (by_name["hours.monday"].detail or "")
    assert not any(r.status is CheckStatus.MISMATCH for r in results if r.name != "name")


def test_prerequisite_is_evaluated_even_when_filtered_out() -> None:
    results = run_checks(
        FACTS,
        site="apple_maps",
        fact="hours.monday",
        transport=_router(apple_maps=_other_business()),
    )
    assert [(r.name, r.status) for r in results] == [
        ("hours.monday", CheckStatus.STRUCTURE_CHANGED)
    ]


def test_passing_prerequisite_lets_dependent_checks_run() -> None:
    results = run_checks(FACTS, site="apple_maps", fact="hours.monday", transport=_router())
    assert [(r.name, r.status) for r in results] == [("hours.monday", CheckStatus.OK)]
