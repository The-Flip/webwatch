"""Tests for the Apple Maps source: golden fixture plus the mutation matrix.

Every negative case mutates the committed fixture in memory (visible markup or the
embedded ``shell-props`` payload) and asserts the honest status for it.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx

from webwatch.facts import load_facts
from webwatch.result import CheckStatus
from webwatch.sources.apple_maps import CHECKS, SOURCE

FIXTURE = (Path(__file__).parent / "fixtures" / "apple_maps_2026-09-26.html").read_text(
    encoding="utf-8"
)
FACTS = load_facts("facts.yaml")
PLACE_ID = "I807CC9ABBE1179A2"
# Apple separates ranges with an en dash; built via chr() to avoid ambiguous-unicode literals.
EN = chr(0x2013)

# The visible Mon-Sat row, as it appears in the fixture.
MON_SAT_ROW = re.compile(
    r'<div class="sc-hours-row" role="text" aria-label="Monday to Saturday[^"]*">.*?'
    r"</div></div></div>",
    re.DOTALL,
)
_SHELL_PROPS = re.compile(
    r'(<script id="shell-props" type="application/json">)(.*?)(</script>)', re.DOTALL
)


def _statuses(html: str) -> dict[str, CheckStatus]:
    observation = SOURCE.observe(html)
    return {check.field: check.run(observation, FACTS).status for check in CHECKS}


def _row(label: str, hours_html: str) -> str:
    return (
        f'<div class="sc-hours-row" role="text"><div class="sc-day-range sc-hours-day">{label}</div>'
        f'<div class="sc-hours-range">{hours_html}</div></div>'
    )


def _time(open_: str, close: str) -> str:
    return f'<div class="sc-time-range"><span>{open_}</span> {EN} <span>{close}</span></div>'


def _replace_mon_sat(new_rows: str) -> str:
    html, count = MON_SAT_ROW.subn(new_rows, FIXTURE)
    assert count == 1, "fixture no longer has the Mon-Sat row this test mutates"
    return html


def _mutate_payload(mutate: Callable[[dict[str, Any]], None]) -> str:
    match = _SHELL_PROPS.search(FIXTURE)
    assert match is not None
    payload = json.loads(match.group(2))
    mutate(payload)
    return FIXTURE[: match.start(2)] + json.dumps(payload) + FIXTURE[match.end(2) :]


def _business_hours(payload: dict[str, Any]) -> dict[str, Any]:
    (place,) = payload["initialState"]["placeCache"].values()
    (component,) = [c for c in place["component"] if c["type"] == "COMPONENT_TYPE_BUSINESS_HOURS"]
    hours: dict[str, Any] = component["value"][0]["businessHours"]
    return hours


# --- golden ------------------------------------------------------------------------


def test_golden_fixture_all_ok() -> None:
    statuses = _statuses(FIXTURE)
    assert set(statuses.values()) == {CheckStatus.OK}, statuses


def test_golden_reads_the_full_week_not_todays_summary() -> None:
    observation = SOURCE.observe(FIXTURE)
    assert observation.get("hours.sunday").value == f"11:00 AM {EN} 6:00 PM"
    assert observation.get("hours.monday").value == f"10:00 AM {EN} 8:00 PM"


# --- hours -------------------------------------------------------------------------


def test_changed_hours_are_mismatch() -> None:
    html = _replace_mon_sat(_row(f"Mon {EN} Sat", _time("12:00 PM", "5:00 PM")))
    statuses = _statuses(html)
    assert statuses["hours.monday"] is CheckStatus.MISMATCH
    assert statuses["hours.sunday"] is CheckStatus.OK


def test_closed_row_when_facts_expect_open_is_mismatch() -> None:
    rows = _row("Monday", "Closed") + _row(f"Tue {EN} Sat", _time("10:00 AM", "8:00 PM"))
    statuses = _statuses(_replace_mon_sat(rows))
    assert statuses["hours.monday"] is CheckStatus.MISMATCH
    assert statuses["hours.tuesday"] is CheckStatus.OK


def test_wraparound_day_range_is_read() -> None:
    # Apple groups across the week boundary (e.g. Saturday through Monday).
    rows = _row(f"Sat {EN} Mon", _time("10:00 AM", "8:00 PM")) + _row(
        f"Tue {EN} Fri", _time("10:00 AM", "8:00 PM")
    )
    observation = SOURCE.observe(_replace_mon_sat(rows))
    assert observation.get("hours.monday").value == f"10:00 AM {EN} 8:00 PM"
    assert observation.get("hours.saturday").is_found


def test_unparseable_hours_are_parse_error() -> None:
    html = _replace_mon_sat(_row(f"Mon {EN} Sat", "ten-ish"))
    assert _statuses(html)["hours.monday"] is CheckStatus.PARSE_ERROR


def test_dropped_day_row_is_structure_changed() -> None:
    html = _replace_mon_sat(_row(f"Tue {EN} Sat", _time("10:00 AM", "8:00 PM")))
    statuses = _statuses(html)
    assert statuses["hours.monday"] is CheckStatus.STRUCTURE_CHANGED
    assert statuses["hours.tuesday"] is CheckStatus.OK


def test_missing_hours_block_is_structure_changed() -> None:
    html = FIXTURE.replace("sc-hours-row", "sc-renamed-row")
    statuses = _statuses(html)
    assert all(
        statuses[f"hours.{day}"] is CheckStatus.STRUCTURE_CHANGED for day in ("monday", "sunday")
    )
    assert statuses["phone"] is CheckStatus.OK


def test_stale_payload_hours_are_metadata_drift() -> None:
    def shift_sunday(payload: dict[str, Any]) -> None:
        for entry in _business_hours(payload)["weeklyHours"]:
            if entry["day"] == ["SUNDAY"]:
                entry["timeRange"] = [{"from": 12 * 3600, "to": 17 * 3600}]

    assert _statuses(_mutate_payload(shift_sunday))["hours.sunday"] is CheckStatus.METADATA_DRIFT


def test_payload_omitting_a_day_means_closed() -> None:
    def drop_sunday(payload: dict[str, Any]) -> None:
        hours = _business_hours(payload)
        hours["weeklyHours"] = [e for e in hours["weeklyHours"] if e["day"] != ["SUNDAY"]]

    observation = SOURCE.observe(_mutate_payload(drop_sunday))
    assert observation.structured["hours.sunday"] == "closed"


def test_malformed_payload_hours_give_no_corroboration_not_a_crash() -> None:
    def break_hours(payload: dict[str, Any]) -> None:
        _business_hours(payload)["weeklyHours"] = [{"day": ["SUNDAY"], "timeRange": [{}]}]

    html = _mutate_payload(break_hours)
    assert "hours.sunday" not in SOURCE.observe(html).structured
    assert _statuses(html)["hours.sunday"] is CheckStatus.OK


def test_empty_payload_hours_are_no_data_not_closed_all_week() -> None:
    def empty_hours(payload: dict[str, Any]) -> None:
        _business_hours(payload)["weeklyHours"] = []

    html = _mutate_payload(empty_hours)
    assert "hours.monday" not in SOURCE.observe(html).structured
    assert _statuses(html)["hours.monday"] is CheckStatus.OK


def test_non_regular_hours_type_is_structure_changed() -> None:
    def holiday(payload: dict[str, Any]) -> None:
        _business_hours(payload)["hoursType"] = "SPECIAL"

    statuses = _statuses(_mutate_payload(holiday))
    assert statuses["hours.monday"] is CheckStatus.STRUCTURE_CHANGED
    assert statuses["phone"] is CheckStatus.OK


# --- phone / website / name --------------------------------------------------------


def test_changed_phone_is_mismatch() -> None:
    html = FIXTURE.replace(">+1 (312) 999-0153</bdo>", ">+1 (312) 555-0100</bdo>")
    assert _statuses(html)["phone"] is CheckStatus.MISMATCH


def test_missing_phone_cell_is_structure_changed() -> None:
    html = FIXTURE.replace("sc-phone-number", "sc-renamed")
    assert _statuses(html)["phone"] is CheckStatus.STRUCTURE_CHANGED


def test_tracking_parameters_on_website_are_not_a_mismatch() -> None:
    html = FIXTURE.replace(
        'href="https://www.theflip.museum/"', 'href="https://www.theflip.museum/?utm_source=apple"'
    )
    assert _statuses(html)["url"] is CheckStatus.OK


def test_changed_website_is_mismatch() -> None:
    html = FIXTURE.replace('href="https://www.theflip.museum/"', 'href="https://example.com/"')
    assert _statuses(html)["url"] is CheckStatus.MISMATCH


def test_changed_name_is_mismatch() -> None:
    html = FIXTURE.replace(
        'with-business-assets" dir="auto">The Flip<', 'with-business-assets" dir="auto">Flip Side<'
    )
    assert _statuses(html)["name"] is CheckStatus.MISMATCH


# --- identity ----------------------------------------------------------------------


def test_page_for_another_place_id_is_structure_changed_everywhere() -> None:
    html = FIXTURE.replace(PLACE_ID, "I0000000000000001")
    assert set(_statuses(html).values()) == {CheckStatus.STRUCTURE_CHANGED}


def test_page_without_any_place_id_is_structure_changed_everywhere() -> None:
    html = FIXTURE.replace(PLACE_ID, "")
    assert set(_statuses(html).values()) == {CheckStatus.STRUCTURE_CHANGED}


# --- fetch boundary ----------------------------------------------------------------


def test_challenge_page_is_blocked(serve_html: Callable[[str], httpx.MockTransport]) -> None:
    challenge = "<html><title>Just a moment...</title></html>"
    observation = SOURCE.fetch(transport=serve_html(challenge))
    statuses = {check.field: check.run(observation, FACTS).status for check in CHECKS}
    assert set(statuses.values()) == {CheckStatus.BLOCKED}
