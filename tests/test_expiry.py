"""Tests for the expired-events check and its year inference."""

from __future__ import annotations

import datetime as dt
from zoneinfo import ZoneInfo

from webwatch.events import Event
from webwatch.expiry import check_expired_events, end_date
from webwatch.result import CheckStatus
from webwatch.sources.base import Observed

TZ = ZoneInfo("America/Chicago")
SITE = "test"


def _now(year: int, month: int, day: int) -> dt.datetime:
    return dt.datetime(year, month, day, 12, 0, tzinfo=TZ)


def _event(month: str = "Jun", day: str = "27", weekday: str = "Saturday", **kw: object) -> Event:
    return Event(title="Saturday Repair Day", month=month, day=day, weekday=weekday, **kw)  # type: ignore[arg-type]


def _events(*events: Event) -> Observed[list[Event]]:
    return Observed.found(list(events))


# --- year inference -----------------------------------------------------------


def test_infers_year_for_upcoming_event() -> None:
    assert end_date(_event(), now=_now(2026, 6, 20)) == dt.date(2026, 6, 27)


def test_infers_nearest_past_year_for_stale_event() -> None:
    # Now is past Jun 27; the weekday pins it to 2026-06-27 (recent past), not next year.
    assert end_date(_event(), now=_now(2026, 7, 1)) == dt.date(2026, 6, 27)


def test_weekday_inconsistent_with_all_years_is_indeterminate() -> None:
    # Jun 27 is never a Monday in 2025-2027, so the year can't be pinned.
    assert end_date(_event(weekday="Monday"), now=_now(2026, 6, 20)) is None


def test_unparseable_month_is_indeterminate() -> None:
    assert end_date(_event(month="Smarch"), now=_now(2026, 6, 20)) is None


def test_no_weekday_falls_back_to_nearest() -> None:
    assert end_date(_event(weekday=""), now=_now(2026, 6, 20)) == dt.date(2026, 6, 27)


# --- the check ----------------------------------------------------------------


def test_event_ending_yesterday_is_mismatch() -> None:
    result = check_expired_events(_events(_event()), now=_now(2026, 6, 28), site=SITE)
    assert result.status is CheckStatus.MISMATCH
    assert "Saturday Repair Day" in result.summary


def test_event_ending_today_is_ok() -> None:
    # The day it ends, before the next midnight -> still valid.
    result = check_expired_events(_events(_event()), now=_now(2026, 6, 27), site=SITE)
    assert result.status is CheckStatus.OK


def test_future_event_is_ok() -> None:
    result = check_expired_events(_events(_event()), now=_now(2026, 6, 20), site=SITE)
    assert result.status is CheckStatus.OK


def test_recurring_stale_event_still_flagged() -> None:
    result = check_expired_events(_events(_event(recurring=True)), now=_now(2026, 6, 28), site=SITE)
    assert result.status is CheckStatus.MISMATCH


def test_indeterminate_date_does_not_false_flag() -> None:
    result = check_expired_events(
        _events(_event(weekday="Monday")), now=_now(2026, 7, 1), site=SITE
    )
    assert result.status is CheckStatus.OK
    assert "indeterminate" in result.observed


def test_unreadable_events_is_structure_changed() -> None:
    result = check_expired_events(Observed.missing("no section"), now=_now(2026, 6, 20), site=SITE)
    assert result.status is CheckStatus.STRUCTURE_CHANGED
