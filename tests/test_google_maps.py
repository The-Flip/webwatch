"""Tests for the Google Maps (Places API) source: golden response plus mutations.

Every negative case mutates the parsed golden response in memory. No test touches
the network or needs a real key; keys are generated per test.
"""

from __future__ import annotations

import copy
import dataclasses
import json
import secrets
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx
import pytest

from webwatch.facts import load_facts
from webwatch.result import CheckStatus
from webwatch.run import run_checks
from webwatch.sources.google_maps import CHECKS, SOURCE

GOLDEN: dict[str, Any] = json.loads(
    (Path(__file__).parent / "fixtures" / "google_maps_2026-09-28.json").read_text(encoding="utf-8")
)
FACTS = load_facts("facts.yaml")


def _statuses(place: dict[str, Any]) -> dict[str, CheckStatus]:
    observation = SOURCE.observe(json.dumps(place))
    return {check.field: check.run(observation, FACTS).status for check in CHECKS}


def _mutated(mutate: Callable[[dict[str, Any]], None]) -> dict[str, Any]:
    place = copy.deepcopy(GOLDEN)
    mutate(place)
    return place


def _periods(place: dict[str, Any]) -> list[dict[str, Any]]:
    periods: list[dict[str, Any]] = place["regularOpeningHours"]["periods"]
    return periods


def _period_for(place: dict[str, Any], day: int) -> dict[str, Any]:
    (period,) = [p for p in _periods(place) if p["open"]["day"] == day]
    return period


@pytest.fixture
def api_key(monkeypatch: pytest.MonkeyPatch) -> str:
    key = secrets.token_hex(16)
    monkeypatch.setattr("webwatch.config.GOOGLE_PLACES_API_KEY", key)
    return key


# --- golden ------------------------------------------------------------------------


def test_golden_all_ok() -> None:
    statuses = _statuses(GOLDEN)
    assert set(statuses.values()) == {CheckStatus.OK}, statuses


def test_google_long_name_is_accepted_via_listing_names() -> None:
    assert GOLDEN["displayName"]["text"] in FACTS.organization.listing_names
    without_alias = dataclasses.replace(
        FACTS, organization=dataclasses.replace(FACTS.organization, listing_names=())
    )
    observation = SOURCE.observe(json.dumps(GOLDEN))
    name_check = next(c for c in CHECKS if c.field == "name")
    assert name_check.run(observation, FACTS).status is CheckStatus.OK
    assert name_check.run(observation, without_alias).status is CheckStatus.MISMATCH


def test_google_day_zero_is_sunday() -> None:
    observation = SOURCE.observe(json.dumps(GOLDEN))
    assert observation.get("hours.sunday").value == "11:00 - 18:00"
    assert observation.get("hours.monday").value == "10:00 - 20:00"


def test_proto3_omitted_zero_fields_default_to_zero() -> None:
    def omit_zeros(place: dict[str, Any]) -> None:
        sunday = _period_for(place, 0)
        sunday["open"] = {"hour": 11}  # day 0 and minute 0 omitted, as proto3 JSON does
        sunday["close"] = {"hour": 18}

    assert _statuses(_mutated(omit_zeros))["hours.sunday"] is CheckStatus.OK


# --- hours -------------------------------------------------------------------------


def test_changed_hours_are_mismatch() -> None:
    def shorten_monday(place: dict[str, Any]) -> None:
        _period_for(place, 1)["close"]["hour"] = 17

    statuses = _statuses(_mutated(shorten_monday))
    assert statuses["hours.monday"] is CheckStatus.MISMATCH
    assert statuses["hours.tuesday"] is CheckStatus.OK


def test_day_without_a_period_is_closed_mismatch() -> None:
    def drop_monday(place: dict[str, Any]) -> None:
        place["regularOpeningHours"]["periods"] = [
            p for p in _periods(place) if p["open"]["day"] != 1
        ]

    observation = SOURCE.observe(json.dumps(_mutated(drop_monday)))
    assert observation.get("hours.monday").value == "closed"
    assert _statuses(_mutated(drop_monday))["hours.monday"] is CheckStatus.MISMATCH


def test_overnight_close_is_read_and_mismatches() -> None:
    def late_friday(place: dict[str, Any]) -> None:
        _period_for(place, 5)["close"] = {"day": 6, "hour": 2, "minute": 0}

    observation = SOURCE.observe(json.dumps(_mutated(late_friday)))
    assert observation.get("hours.friday").value == "10:00 - 02:00"
    assert _statuses(_mutated(late_friday))["hours.friday"] is CheckStatus.MISMATCH


def test_always_open_is_a_full_day_every_day_not_closed() -> None:
    def always_open(place: dict[str, Any]) -> None:
        place["regularOpeningHours"]["periods"] = [{"open": {"day": 0, "hour": 0, "minute": 0}}]

    place = _mutated(always_open)
    observation = SOURCE.observe(json.dumps(place))
    assert {observation.get(f"hours.{d}").value for d in ("monday", "sunday")} == {"00:00 - 00:00"}
    statuses = _statuses(place)
    assert all(statuses[f"hours.{d}"] is CheckStatus.MISMATCH for d in ("monday", "sunday"))


def test_period_spanning_days_makes_all_hours_parse_error() -> None:
    def long_period(place: dict[str, Any]) -> None:
        _period_for(place, 1)["close"]["day"] = 3

    statuses = _statuses(_mutated(long_period))
    assert {statuses[f"hours.{d}"] for d in ("monday", "sunday")} == {CheckStatus.PARSE_ERROR}


@pytest.mark.parametrize(
    "bad_point",
    [
        {"day": 1, "hour": 25, "minute": 0},  # hour out of range
        {"day": 1, "hour": 10, "minute": 99},  # minute out of range
        {"day": 1, "hour": True, "minute": 0},  # bool is an int subclass in Python
    ],
)
def test_invalid_point_makes_all_hours_parse_error(bad_point: dict[str, Any]) -> None:
    def corrupt(place: dict[str, Any]) -> None:
        _period_for(place, 1)["close"] = bad_point

    statuses = _statuses(_mutated(corrupt))
    assert {statuses[f"hours.{d}"] for d in ("monday", "sunday")} == {CheckStatus.PARSE_ERROR}


def test_missing_opening_hours_is_structure_changed() -> None:
    statuses = _statuses(_mutated(lambda p: p.pop("regularOpeningHours")))
    assert statuses["hours.monday"] is CheckStatus.STRUCTURE_CHANGED
    assert statuses["phone"] is CheckStatus.OK


# --- phone / website / name / status -----------------------------------------------


def test_changed_phone_is_mismatch() -> None:
    place = _mutated(lambda p: p.update(nationalPhoneNumber="(312) 555-0100"))
    assert _statuses(place)["phone"] is CheckStatus.MISMATCH


def test_omitted_phone_is_structure_changed() -> None:
    assert _statuses(_mutated(lambda p: p.pop("nationalPhoneNumber")))["phone"] is (
        CheckStatus.STRUCTURE_CHANGED
    )


def test_changed_website_is_mismatch() -> None:
    place = _mutated(lambda p: p.update(websiteUri="https://example.com/"))
    assert _statuses(place)["url"] is CheckStatus.MISMATCH


def test_omitted_website_is_structure_changed() -> None:
    statuses = _statuses(_mutated(lambda p: p.pop("websiteUri")))
    assert statuses["url"] is CheckStatus.STRUCTURE_CHANGED


def test_permanently_closed_is_mismatch() -> None:
    place = _mutated(lambda p: p.update(businessStatus="CLOSED_PERMANENTLY"))
    assert _statuses(place)["business_status"] is CheckStatus.MISMATCH


def test_changed_name_is_mismatch() -> None:
    place = _mutated(lambda p: p.update(displayName={"text": "Flip Side"}))
    assert _statuses(place)["name"] is CheckStatus.MISMATCH


# --- identity / malformed ----------------------------------------------------------


def test_response_for_another_place_is_structure_changed_everywhere() -> None:
    place = _mutated(lambda p: p.update(id="ChIJsomeoneElse"))
    assert set(_statuses(place).values()) == {CheckStatus.STRUCTURE_CHANGED}


def test_non_json_response_is_parse_error_everywhere() -> None:
    observation = SOURCE.observe("<html>Not JSON</html>")
    statuses = {check.field: check.run(observation, FACTS).status for check in CHECKS}
    assert set(statuses.values()) == {CheckStatus.PARSE_ERROR}


# --- fetch boundary: the key -------------------------------------------------------


def _json_transport(
    body: dict[str, Any], status_code: int = 200, seen: list[httpx.Request] | None = None
) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(request)
        return httpx.Response(status_code, json=body)

    return httpx.MockTransport(handler)


def test_key_and_field_mask_are_sent_as_headers_not_in_url(api_key: str) -> None:
    seen: list[httpx.Request] = []
    SOURCE.fetch(transport=_json_transport(GOLDEN, seen=seen))
    (request,) = seen
    assert request.headers["X-Goog-Api-Key"] == api_key
    assert "regularOpeningHours" in request.headers["X-Goog-FieldMask"]
    assert api_key not in str(request.url)


def test_unset_key_is_fetch_error_without_any_request(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("webwatch.config.GOOGLE_PLACES_API_KEY", "")

    def must_not_be_called(_request: httpx.Request) -> httpx.Response:
        raise AssertionError("no request may be made without a key")

    results = run_checks(
        FACTS, site="google_maps", transport=httpx.MockTransport(must_not_be_called)
    )
    assert results
    assert {r.status for r in results} == {CheckStatus.FETCH_ERROR}
    assert "WEBWATCH_GOOGLE_PLACES_API_KEY" in (results[0].detail or "")


def test_rejected_key_is_fetch_error_with_reason_but_no_key(
    api_key: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("webwatch.config.HTTP_MAX_RETRIES", 0)
    error = {"error": {"code": 403, "message": "API key not valid.", "status": "PERMISSION_DENIED"}}
    results = run_checks(FACTS, site="google_maps", transport=_json_transport(error, 403))
    assert {r.status for r in results} == {CheckStatus.FETCH_ERROR}
    detail = results[0].detail or ""
    assert "PERMISSION_DENIED" in detail
    assert all(api_key not in (r.detail or "") + r.summary for r in results)


def test_closure_is_reported_even_when_the_name_also_changed(api_key: str) -> None:
    def renamed_and_closed(place: dict[str, Any]) -> None:
        place["displayName"] = {"text": "Flip Side"}
        place["businessStatus"] = "CLOSED_PERMANENTLY"

    body = _mutated(renamed_and_closed)
    by_name = {
        r.name: r.status
        for r in run_checks(FACTS, site="google_maps", transport=_json_transport(body))
    }
    assert by_name["name"] is CheckStatus.MISMATCH
    assert by_name["business_status"] is CheckStatus.MISMATCH  # never hidden by the gate
    assert by_name["hours.monday"] is CheckStatus.STRUCTURE_CHANGED  # gated on name
