"""Tests for the Square donation-link source: golden fixture plus the mutation matrix.

The checkout page is a JS shell; its state is the ``window.bootstrap`` JSON. Negative
cases mutate that payload in memory (or serve an in-memory HTTP response for the
404/410/5xx paths) and assert the honest status for each.
"""

from __future__ import annotations

import copy
import dataclasses
import json
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx
import pytest

from webwatch import normalize
from webwatch.facts import Facts, load_facts
from webwatch.fetch import FetchError
from webwatch.result import CheckResult, CheckStatus
from webwatch.sources.base import Observation
from webwatch.sources.square_donation import CHECKS, SOURCE, checkout_ids

FIXTURE = (Path(__file__).parent / "fixtures" / "square_donation_2026-10-15.html").read_text(
    encoding="utf-8"
)
FACTS = load_facts("facts.yaml")
_ASSIGNMENT = re.compile(r"window\.bootstrap\s*=\s*")
# Square's real "no such checkout" page (captured 2026-10-15 for an unknown link id).
SQUARE_NOT_FOUND = (
    "<html><head><title>Something went wrong</title></head><body><h1>Something went wrong</h1>"
    "<p>We couldn't find that page.</p><p>Check your link and try again.</p>"
    "<footer>Secure checkout powered by Square</footer></body></html>"
)


def _split_bootstrap() -> tuple[str, dict[str, Any], str]:
    """The fixture as (text before the payload, payload, text after it)."""
    match = _ASSIGNMENT.search(FIXTURE)
    assert match is not None, "fixture no longer assigns window.bootstrap"
    payload, end = json.JSONDecoder().raw_decode(FIXTURE, match.end())
    return FIXTURE[: match.end()], payload, FIXTURE[end:]


def _with_bootstrap(mutate: Callable[[dict[str, Any]], None]) -> str:
    before, payload, after = _split_bootstrap()
    payload = copy.deepcopy(payload)
    mutate(payload)
    return before + json.dumps(payload) + after


def _link_data(payload: dict[str, Any]) -> dict[str, Any]:
    return payload["checkoutLink"]["checkout_link_data"]


def _check(observation: Observation, facts: Facts = FACTS) -> CheckResult:
    (check,) = CHECKS
    return check.run(observation, facts)


def _status(html: str, facts: Facts = FACTS) -> CheckStatus:
    return _check(SOURCE.observe(html), facts).status


def _fetch_status(status_code: int, body: str = SQUARE_NOT_FOUND) -> CheckStatus:
    transport = httpx.MockTransport(lambda _r: httpx.Response(status_code, html=body))
    return _check(SOURCE.fetch(transport=transport)).status


# --- against the real fixture -------------------------------------------------


def test_link_is_active_against_fixture() -> None:
    assert _status(FIXTURE) is CheckStatus.OK


def test_source_monitors_the_facts_donation_url() -> None:
    """The pinned checkout URL and facts.yaml must name the same link."""
    assert normalize.url(SOURCE.url) == normalize.url(FACTS.organization.donation_url)


def test_checkout_ids_reject_a_short_link() -> None:
    with pytest.raises(ValueError, match="checkout"):
        checkout_ids("https://square.link/u/zHuPuFSr")


# --- the link is not live -> MISMATCH -----------------------------------------


def test_disabled_link_is_mismatch() -> None:
    html = _with_bootstrap(lambda p: _link_data(p).update(enabled=False))
    result = _check(SOURCE.observe(html))
    assert result.status is CheckStatus.MISMATCH
    assert result.observed == "disabled"


def test_deleted_link_is_mismatch() -> None:
    html = _with_bootstrap(lambda p: p["checkoutLink"].update(is_deleted=True))
    assert _status(html) is CheckStatus.MISMATCH


def test_deleted_link_wins_over_a_missing_companion_flag() -> None:
    """A present unhealthy flag is the answer, even if another flag was omitted."""

    def mutate(payload: dict[str, Any]) -> None:
        payload["checkoutLink"]["is_deleted"] = True
        del payload["checkoutLink"]["checkout_link_data"]

    result = _check(SOURCE.observe(_with_bootstrap(mutate)))
    assert result.status is CheckStatus.MISMATCH
    assert result.observed == "deleted"


def test_store_not_accepting_payments_is_mismatch() -> None:
    html = _with_bootstrap(lambda p: p.update(storeIsAcceptingPayments=False))
    assert _status(html) is CheckStatus.MISMATCH


@pytest.mark.parametrize("status_code", [404, 410])
def test_link_not_found_is_mismatch(status_code: int) -> None:
    """Square answers a deleted link with a 404: that's the finding, not a fetch failure."""
    assert _fetch_status(status_code) is CheckStatus.MISMATCH


def test_404_without_squares_not_found_page_is_structure_changed() -> None:
    """A bare 404 (CDN/routing glitch, path change) is not proof the link was deleted."""
    assert _fetch_status(404, "<html><body>404</body></html>") is CheckStatus.STRUCTURE_CHANGED


# --- couldn't read the status -> STRUCTURE_CHANGED / PARSE_ERROR ---------------


@pytest.mark.parametrize(
    "mutate",
    [
        lambda p: p.pop("storeIsAcceptingPayments"),
        lambda p: p["checkoutLink"].pop("is_deleted"),
        lambda p: _link_data(p).pop("enabled"),
        lambda p: p.update(checkoutLink=None),
    ],
    ids=["no-accepting-flag", "no-deleted-flag", "no-enabled-flag", "null-checkout-link"],
)
def test_absent_flag_is_structure_changed_never_ok(mutate: Callable[[dict[str, Any]], Any]) -> None:
    assert _status(_with_bootstrap(mutate)) is CheckStatus.STRUCTURE_CHANGED


def test_non_bool_flag_is_parse_error() -> None:
    html = _with_bootstrap(lambda p: _link_data(p).update(enabled="yes"))
    assert _status(html) is CheckStatus.PARSE_ERROR


def test_missing_bootstrap_is_structure_changed() -> None:
    before, _payload, after = _split_bootstrap()
    assert _status(before.replace("window.bootstrap", "window.other") + "{}" + after) is (
        CheckStatus.STRUCTURE_CHANGED
    )


def test_malformed_bootstrap_is_structure_changed() -> None:
    before, _payload, after = _split_bootstrap()
    assert _status(before + "{not json" + after) is CheckStatus.STRUCTURE_CHANGED


def test_trailing_script_after_bootstrap_is_ignored() -> None:
    before, payload, _after = _split_bootstrap()
    html = before + json.dumps(payload) + "; function f() { return {a: 1}; }</script></html>"
    assert _status(html) is CheckStatus.OK


@pytest.mark.parametrize("key", ["checkoutLinkId", "merchantId"])
def test_page_for_another_checkout_is_structure_changed(key: str) -> None:
    """Identity guard: a different checkout's state is never asserted as ours."""
    html = _with_bootstrap(lambda p: p.update({key: "SOMEONEELSE"}))
    assert _status(html) is CheckStatus.STRUCTURE_CHANGED


# --- fetch paths ---------------------------------------------------------------


def test_golden_page_via_fetch_is_ok() -> None:
    assert _fetch_status(200, FIXTURE) is CheckStatus.OK


def test_challenge_page_is_blocked() -> None:
    assert _fetch_status(200, "<html><title>Just a moment...</title></html>") is (
        CheckStatus.BLOCKED
    )


def test_challenge_served_as_404_is_blocked_not_mismatch() -> None:
    assert _fetch_status(404, "<html><title>Just a moment...</title></html>") is (
        CheckStatus.BLOCKED
    )


def test_server_error_is_still_a_fetch_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("webwatch.config.HTTP_MAX_RETRIES", 0)
    transport = httpx.MockTransport(lambda _r: httpx.Response(500))
    with pytest.raises(FetchError):
        SOURCE.fetch(transport=transport)


# --- skipped --------------------------------------------------------------------


def test_blank_donation_url_fact_is_skipped() -> None:
    facts = dataclasses.replace(
        FACTS, organization=dataclasses.replace(FACTS.organization, donation_url="")
    )
    assert _status(FIXTURE, facts) is CheckStatus.SKIPPED
