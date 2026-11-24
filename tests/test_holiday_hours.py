"""Tests for the holiday-hours check: posted in time, correct, and removed afterwards.

Policy (``docs/Facts.md``): a holiday must be posted within 30 days of it; earlier
posting is fine while the season is open (some configured holiday within 60 days);
a row still up after its holiday is stale. The clock is always pinned. Real-page
cases come from the 2026-11-24 fixtures; the rest mutate them or build a listing.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import replace
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from bs4 import BeautifulSoup

from webwatch.facts import Facts, Organization, load_facts
from webwatch.holiday_hours import check_holiday_hours, check_names
from webwatch.result import CheckResult, CheckStatus
from webwatch.sources.base import HolidayListing, ListedHours, Observed
from webwatch.sources.theflip_museum import SOURCE as HOME
from webwatch.sources.theflip_museum_visit import SOURCE as VISIT

FIXTURES = Path(__file__).parent / "fixtures"
VISIT_HTML = (FIXTURES / "theflip_museum_visit_2026-11-24.html").read_text(encoding="utf-8")
HOME_HTML = (FIXTURES / "theflip_museum_2026-11-24.html").read_text(encoding="utf-8")
FACTS = load_facts("facts.yaml")
TZ = ZoneInfo("America/Chicago")
SITE = "test"


def _now(year: int, month: int, day: int) -> dt.datetime:
    return dt.datetime(year, month, day, 7, 0, tzinfo=TZ)


def _by_name(results: list[CheckResult]) -> dict[str, CheckResult]:
    return {r.name.removeprefix("holiday_hours."): r for r in results}


def _run(
    listing: Observed[HolidayListing] | HolidayListing,
    now: dt.datetime,
    *,
    dated: bool = False,
    facts: Facts = FACTS,
) -> dict[str, CheckResult]:
    observed = listing if isinstance(listing, Observed) else Observed.found(listing)
    return _by_name(check_holiday_hours(observed, facts, now=now, site=SITE, dated=dated))


def _visible(*rows: tuple[str, str], unrecognized: tuple[str, ...] = ()) -> HolidayListing:
    return HolidayListing(
        tuple(ListedHours(h, Observed.found(v), holiday=h) for h, v in rows), unrecognized
    )


def _dated(*entries: tuple[str, str]) -> HolidayListing:
    return HolidayListing(
        tuple(
            ListedHours(
                d, Observed.found(v), start=dt.date.fromisoformat(d), end=dt.date.fromisoformat(d)
            )
            for d, v in entries
        )
    )


def _visit(html: str, now: dt.datetime) -> dict[str, CheckResult]:
    return _run(VISIT.observe(html).holiday_hours, now)


def _home(now: dt.datetime) -> dict[str, CheckResult]:
    return _run(HOME.observe(HOME_HTML).holiday_hours, now, dated=True)


def _without_row(html: str, label: str) -> str:
    """The /visit fixture with one holiday row removed (fresh parse)."""
    soup = BeautifulSoup(html, "lxml")
    for span in soup.find_all("span"):
        if span.get_text(strip=True) == label:
            span.parent.decompose()
    return str(soup)


def _statuses(results: dict[str, CheckResult]) -> dict[str, CheckStatus]:
    return {name: r.status for name, r in results.items()}


# --- the real pages today -----------------------------------------------------------

TODAY = _now(2026, 11, 24)


def test_visit_page_all_ok_today() -> None:
    assert set(_statuses(_visit(VISIT_HTML, TODAY)).values()) == {CheckStatus.OK}


def test_homepage_all_ok_today() -> None:
    results = _home(TODAY)
    assert set(_statuses(results).values()) == {CheckStatus.OK}
    assert "expired" in results


def test_check_names_cover_every_holiday() -> None:
    assert check_names(dated=False) == [
        "holiday_hours.thanksgiving",
        "holiday_hours.christmas_eve",
        "holiday_hours.christmas",
        "holiday_hours.new_years_eve",
        "holiday_hours.new_years_day",
        "holiday_hours.unrecognized",
    ]
    assert check_names(dated=True)[-1] == "holiday_hours.expired"


# --- left up after the holiday -------------------------------------------------------


def test_row_left_up_after_the_holiday_is_mismatch() -> None:
    result = _visit(VISIT_HTML, _now(2026, 11, 27))["thanksgiving"]
    assert result.status is CheckStatus.MISMATCH
    assert "2026-11-26" in result.summary and "remove" in result.summary


def test_row_removed_after_the_holiday_is_ok() -> None:
    html = _without_row(VISIT_HTML, "Thanksgiving")
    assert _visit(html, _now(2026, 11, 27))["thanksgiving"].status is CheckStatus.OK


def test_dated_entry_left_up_after_the_holiday_is_mismatch() -> None:
    result = _home(_now(2026, 11, 27))["thanksgiving"]
    assert result.status is CheckStatus.MISMATCH
    assert "2026-11-26" in result.summary


def test_whole_block_left_up_in_january() -> None:
    statuses = _statuses(_visit(VISIT_HTML, _now(2027, 1, 2)))
    assert {statuses[h] for h in ("thanksgiving", "christmas", "new_years_day")} == {
        CheckStatus.MISMATCH
    }


def test_on_the_holiday_itself_the_row_is_current() -> None:
    assert _visit(VISIT_HTML, _now(2026, 11, 26))["thanksgiving"].status is CheckStatus.OK
    assert _visit(VISIT_HTML, _now(2026, 12, 31))["new_years_eve"].status is CheckStatus.OK


# --- posted in time -----------------------------------------------------------------


def test_not_posted_within_30_days_is_mismatch() -> None:
    html = _without_row(VISIT_HTML, "Christmas Eve")
    result = _visit(html, _now(2026, 12, 1))["christmas_eve"]
    assert result.status is CheckStatus.MISMATCH
    assert "not posted" in result.summary and "2026-12-24" in result.summary


@pytest.mark.parametrize(("day", "status"), [(24, CheckStatus.MISMATCH), (23, CheckStatus.OK)])
def test_30_day_boundary(day: int, status: CheckStatus) -> None:
    # Christmas Eve 2026-12-24: 30 days out on Nov 24 (required), 31 on Nov 23.
    listing = _visible(("christmas", "closed"))  # season open, Christmas Eve absent
    assert _run(listing, _now(2026, 11, day))["christmas_eve"].status is status


def test_not_posted_more_than_30_days_ahead_is_ok() -> None:
    assert _run(HolidayListing(), _now(2026, 10, 20))["thanksgiving"].status is CheckStatus.OK


# --- posted early: season-aware -------------------------------------------------------


def test_whole_block_posted_with_thanksgiving_due_is_ok() -> None:
    # Oct 27: Thanksgiving 30 days out; New Year's Day 66 days out but the season is open.
    statuses = _statuses(_visit(VISIT_HTML, _now(2026, 10, 27)))
    assert set(statuses.values()) == {CheckStatus.OK}, statuses


def test_posted_with_no_holiday_within_60_days_is_too_early() -> None:
    result = _visit(VISIT_HTML, _now(2026, 9, 1))["thanksgiving"]
    assert result.status is CheckStatus.MISMATCH
    assert "too early" in result.summary


@pytest.mark.parametrize(("day", "status"), [(27, CheckStatus.OK), (26, CheckStatus.MISMATCH)])
def test_60_day_season_boundary(day: int, status: CheckStatus) -> None:
    # Thanksgiving 2026-11-26 is 60 days out on Sep 27 (season open), 61 on Sep 26.
    listing = _visible(("thanksgiving", "closed"))
    assert _run(listing, _now(2026, 9, day))["thanksgiving"].status is status


# --- hours themselves --------------------------------------------------------------------


def test_wrong_hours_are_mismatch() -> None:
    listing = _visible(("christmas_eve", "10a - 4p"))
    assert _run(listing, TODAY)["christmas_eve"].status is CheckStatus.MISMATCH


def test_open_when_it_should_be_closed_is_mismatch() -> None:
    listing = _visible(("thanksgiving", "10a - 8p"))
    assert _run(listing, TODAY)["thanksgiving"].status is CheckStatus.MISMATCH


def test_unparseable_hours_are_parse_error() -> None:
    listing = _visible(("christmas_eve", "ten-ish"))
    assert _run(listing, TODAY)["christmas_eve"].status is CheckStatus.PARSE_ERROR


def test_conflicting_duplicate_rows_are_mismatch_not_first_wins() -> None:
    listing = _visible(("thanksgiving", "closed"), ("thanksgiving", "10a - 3p"))
    assert _run(listing, TODAY)["thanksgiving"].status is CheckStatus.MISMATCH


def test_dated_entry_with_unreadable_times_is_parse_error() -> None:
    item = ListedHours(
        "2026-12-24",
        Observed.unparseable("no opens"),
        start=dt.date(2026, 12, 24),
        end=dt.date(2026, 12, 24),
    )
    results = _run(HolidayListing((item,)), TODAY, dated=True)
    assert results["christmas_eve"].status is CheckStatus.PARSE_ERROR


def test_dated_range_is_attributed_to_every_holiday_it_covers() -> None:
    item = ListedHours(
        "range", Observed.found("closed"), start=dt.date(2026, 12, 24), end=dt.date(2026, 12, 25)
    )
    results = _run(HolidayListing((item,)), TODAY, dated=True)
    assert results["christmas"].status is CheckStatus.OK
    assert results["christmas_eve"].status is CheckStatus.MISMATCH  # expected 10-15


# --- honesty -------------------------------------------------------------------------------


def test_unreadable_listing_is_never_a_verdict() -> None:
    results = _run(Observed.missing("hours card not found"), TODAY)
    assert {r.status for r in results.values()} == {CheckStatus.STRUCTURE_CHANGED}


def test_unrecognized_row_blocks_only_a_not_posted_verdict() -> None:
    listing = _visible(("thanksgiving", "closed"), unrecognized=("Xmas Eve",))
    results = _run(listing, TODAY)
    # Christmas Eve is due and absent -- but "Xmas Eve" might be it: can't say "not posted".
    assert results["christmas_eve"].status is CheckStatus.STRUCTURE_CHANGED
    assert results["thanksgiving"].status is CheckStatus.OK
    assert results["unrecognized"].status is CheckStatus.STRUCTURE_CHANGED
    assert "Xmas Eve" in results["unrecognized"].detail


def test_unrecognized_row_off_season_does_not_block_every_holiday() -> None:
    listing = _visible(unrecognized=("Inventory Day",))
    results = _run(listing, _now(2026, 6, 1))
    assert {results[h].status for h in ("thanksgiving", "christmas")} == {CheckStatus.OK}
    assert results["unrecognized"].status is CheckStatus.STRUCTURE_CHANGED


def test_unconfigured_holiday_is_skipped() -> None:
    hours = {k: v for k, v in FACTS.organization.holiday_hours.items() if k != "christmas"}
    facts = replace(FACTS, organization=replace(FACTS.organization, holiday_hours=hours))
    assert _run(HolidayListing(), TODAY, facts=facts)["christmas"].status is CheckStatus.SKIPPED


def test_blank_expected_is_skipped() -> None:
    facts = Facts(organization=Organization(holiday_hours={"thanksgiving": ""}))
    assert (
        _run(_visible(("thanksgiving", "x")), TODAY, facts=facts)["thanksgiving"].status
        is CheckStatus.SKIPPED
    )


# --- dated: non-holiday entries -------------------------------------------------------------


def test_expired_non_holiday_entry_is_flagged() -> None:
    listing = _dated(("2026-11-01", "closed"))
    result = _run(listing, TODAY, dated=True)["expired"]
    assert result.status is CheckStatus.MISMATCH
    assert "2026-11-01" in result.summary


def test_future_non_holiday_entry_is_ignored() -> None:
    # e.g. a one-off closure: not ours to judge, and it never blocks a verdict.
    results = _run(_dated(("2026-12-05", "closed")), TODAY, dated=True)
    assert results["expired"].status is CheckStatus.OK
    assert results["unrecognized"].status is CheckStatus.OK


def _range(start: str, end: str, hours: str) -> ListedHours:
    return ListedHours(
        f"{start}..{end}",
        Observed.found(hours),
        start=dt.date.fromisoformat(start),
        end=dt.date.fromisoformat(end),
    )


def test_wide_range_defers_to_a_narrower_entry_for_the_holiday() -> None:
    # "Dec 20-31 extended hours" plus specific holiday entries: judge the specific ones.
    listing = HolidayListing(
        (
            _range("2026-12-20", "2026-12-31", "10:00 - 22:00"),
            *_dated(
                ("2026-12-24", "10:00 - 15:00"),
                ("2026-12-25", "closed"),
                ("2026-12-31", "10:00 - 15:00"),
            ).items,
        )
    )
    statuses = _statuses(_run(listing, TODAY, dated=True))
    assert {statuses[h] for h in ("christmas_eve", "christmas", "new_years_eve")} == {
        CheckStatus.OK
    }


def test_range_still_in_effect_is_not_stale_for_its_earlier_holiday() -> None:
    # A Dec 24-25 entry read on Dec 25 is still current: Christmas Eve is not "left up".
    listing = HolidayListing((_range("2026-12-24", "2026-12-25", "closed"),))
    results = _run(listing, _now(2026, 12, 25), dated=True)
    assert results["christmas_eve"].status is CheckStatus.OK
    assert results["christmas"].status is CheckStatus.OK


def test_stale_entry_for_an_unconfigured_holiday_is_still_expired() -> None:
    hours = {k: v for k, v in FACTS.organization.holiday_hours.items() if k != "thanksgiving"}
    facts = replace(FACTS, organization=replace(FACTS.organization, holiday_hours=hours))
    results = _run(_dated(("2026-11-26", "closed")), _now(2026, 11, 27), dated=True, facts=facts)
    assert results["thanksgiving"].status is CheckStatus.SKIPPED
    assert results["expired"].status is CheckStatus.MISMATCH
