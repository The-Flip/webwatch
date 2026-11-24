"""Check that a page's holiday hours are posted in time, correct, and removed afterwards.

Policy (see ``docs/Facts.md``), per holiday in :data:`webwatch.holidays.NAMES`, with
``today`` in the museum's timezone:

- A listed row/entry whose *previous* occurrence is nearer than its next is
  **stale** — the holiday has passed and it's still up -> ``MISMATCH`` ("remove it").
- Otherwise it is **upcoming**, and its hours must match ``facts.yaml``. Posting
  early is fine while the season is open (some configured holiday within
  :data:`SEASON_WITHIN_DAYS`); posted with no holiday that close it is "too early".
- Not listed: ``MISMATCH`` ("not posted") within :data:`REQUIRED_WITHIN_DAYS` of the
  holiday; ``OK`` otherwise.

Honesty: an unreadable listing is never a verdict (its ``Observed`` reason maps to
``STRUCTURE_CHANGED`` / ``PARSE_ERROR``). Rows we can't attribute to a holiday are
reported once, in ``holiday_hours.unrecognized``; they block only a "not posted"
verdict (the row might be that holiday under a new name), so one odd row can't
turn every holiday into an alarm all year. Dated listings (JSON-LD) are attributed
by date — the narrowest entry covering a holiday is the one judged, so a wide
"extended hours" range defers to a specific holiday entry — and an entry is stale
only once its own range has ended. Entries not judged for any configured holiday
are checked only for having expired (``holiday_hours.expired``). Clock-injected,
like ``webwatch.expiry``.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

from webwatch import holidays, normalize
from webwatch.checks.base import check_field, not_found_result
from webwatch.facts import Facts, is_blank
from webwatch.result import CheckResult, CheckStatus
from webwatch.sources.base import HolidayListing, ListedHours, Observed

#: A holiday must be posted at least this many days ahead (inclusive).
REQUIRED_WITHIN_DAYS = 30
#: Early posting is fine while some configured holiday is at most this many days away.
SEASON_WITHIN_DAYS = 60

PREFIX = "holiday_hours."
UNRECOGNIZED = f"{PREFIX}unrecognized"
EXPIRED = f"{PREFIX}expired"
_NOT_CONFIGURED = "no expected holiday hours set"


def check_names(*, dated: bool) -> list[str]:
    """Every result name this check produces for a source (for listings and fan-out)."""
    names = [f"{PREFIX}{name}" for name in holidays.NAMES] + [UNRECOGNIZED]
    return [*names, EXPIRED] if dated else names


@dataclass(frozen=True, slots=True)
class _Attributed:
    item: ListedHours
    #: The item's position in the listing (identifies it for ``expired``).
    index: int
    #: The occurrence this item is about (``None`` for an undated row: judged by nearness).
    occurrence: dt.date | None = None


def check_holiday_hours(
    listing: Observed[HolidayListing],
    facts: Facts,
    *,
    now: dt.datetime,
    site: str,
    dated: bool,
) -> list[CheckResult]:
    """One result per holiday, plus ``unrecognized`` (and ``expired`` if ``dated``)."""
    expected_by_name = facts.organization.holiday_hours
    configured = [n for n in holidays.NAMES if not is_blank(expected_by_name.get(n))]
    if not listing.is_found or listing.value is None:
        return [
            CheckResult.skipped(site, check, summary=_NOT_CONFIGURED)
            if check.removeprefix(PREFIX) in holidays.NAMES
            and check.removeprefix(PREFIX) not in configured
            else not_found_result(site, check, listing)
            for check in check_names(dated=dated)
        ]

    today = now.date()
    value = listing.value
    attributed = _attribute(value.items)
    season_open = any(
        (holidays.next_occurrence(name, today) - today).days <= SEASON_WITHIN_DAYS
        for name in configured
    )
    results = [
        _judge(
            site,
            name,
            expected_by_name.get(name),
            attributed.get(name, []),
            today=today,
            season_open=season_open,
            unrecognized=value.unrecognized,
        )
        for name in holidays.NAMES
    ]
    results.append(_unrecognized(site, value.unrecognized))
    if dated:
        judged = {a.index for name in configured for a in attributed.get(name, [])}
        results.append(_expired(site, value.items, judged, today))
    return results


def _attribute(items: tuple[ListedHours, ...]) -> dict[str, list[_Attributed]]:
    """Group items by holiday: visible ones by label, dated ones by the dates they cover.

    For each holiday date only the *narrowest* covering entries count: a specific
    "Dec 25: closed" overrides a wide "Dec 20-31: extended hours" for Christmas, so
    a correct page never reads as a conflict.
    """
    grouped: dict[str, list[_Attributed]] = {}
    covering: dict[tuple[str, dt.date], list[tuple[dt.timedelta, _Attributed]]] = {}
    for index, item in enumerate(items):
        if item.holiday is not None:
            grouped.setdefault(item.holiday, []).append(_Attributed(item, index))
            continue
        if item.start is None or item.end is None:
            continue
        span = item.end - item.start
        # Spans are bounded by the source (at most a month), so this loop is small.
        for name in holidays.NAMES:
            for year in range(item.start.year, item.end.year + 1):
                occurrence = holidays.date_of(name, year)
                if item.start <= occurrence <= item.end:
                    covering.setdefault((name, occurrence), []).append(
                        (span, _Attributed(item, index, occurrence))
                    )
    for (name, _), candidates in covering.items():
        narrowest = min(span for span, _ in candidates)
        grouped.setdefault(name, []).extend(a for span, a in candidates if span == narrowest)
    return grouped


def _judge(
    site: str,
    name: str,
    expected: object,
    listed: list[_Attributed],
    *,
    today: dt.date,
    season_open: bool,
    unrecognized: tuple[str, ...],
) -> CheckResult:
    check = f"{PREFIX}{name}"
    if is_blank(expected):
        return CheckResult.skipped(site, check, summary=_NOT_CONFIGURED)

    label = holidays.label(name)
    upcoming = holidays.next_occurrence(name, today)
    previous = holidays.previous_occurrence(name, today)
    days_until = (upcoming - today).days
    # A dated entry for a passed holiday whose range is still running (Dec 24-25,
    # read on Dec 25) is current for a later date, not left up for this one.
    listed = [a for a in listed if not _passed_but_in_effect(a, today)]

    stale = [a for a in listed if _is_stale(a, today, previous, upcoming)]
    if stale:
        return CheckResult.mismatch(
            site,
            check,
            expected="not listed",
            observed=", ".join(a.item.hours.value or a.item.label for a in stale),
            summary=f"{label} ({_passed_date(stale[0], previous)}) has passed but is still "
            "listed; remove it",
        )

    if not listed:
        if days_until > REQUIRED_WITHIN_DAYS:
            return CheckResult.ok(
                site,
                check,
                expected=expected,
                observed=None,
                summary=f"not listed yet; next on {upcoming}",
            )
        if unrecognized:
            return CheckResult.structure_changed(
                site,
                check,
                detail=f"unrecognized holiday rows {list(unrecognized)} may be {label}",
                summary=f"can't confirm {label} ({upcoming}) is posted",
            )
        return CheckResult.mismatch(
            site,
            check,
            expected=expected,
            observed="not listed",
            summary=f"{label} ({upcoming}) is in {days_until} days; holiday hours not posted",
        )

    later = [a for a in listed if a.occurrence is not None and a.occurrence > upcoming]
    if later or (days_until > SEASON_WITHIN_DAYS and not season_open):
        return CheckResult.mismatch(
            site,
            check,
            expected="not listed yet",
            observed=", ".join(a.item.hours.value or a.item.label for a in listed),
            summary=f"{label} ({upcoming}) is {days_until} days away; posted too early "
            f"(no holiday within {SEASON_WITHIN_DAYS} days)",
        )

    return _compare(site, check, expected, listed)


def _is_stale(
    attributed: _Attributed, today: dt.date, previous: dt.date, upcoming: dt.date
) -> bool:
    if attributed.occurrence is not None:
        # Dated: stale once the entry's own range has ended.
        return (attributed.item.end or attributed.occurrence) < today
    # Undated: whichever occurrence is nearer is the one the row is about.
    return (today - previous).days < (upcoming - today).days


def _passed_but_in_effect(attributed: _Attributed, today: dt.date) -> bool:
    end = attributed.item.end
    occurrence = attributed.occurrence
    return occurrence is not None and end is not None and occurrence < today <= end


def _passed_date(attributed: _Attributed, previous: dt.date) -> dt.date:
    return attributed.occurrence or previous


def _compare(site: str, check: str, expected: object, listed: list[_Attributed]) -> CheckResult:
    """Every listed item must match — never first-wins. Unreadable beats different."""
    results = [
        check_field(site, check, a.item.hours, expected, normalizer=normalize.day_hours)
        for a in listed
    ]
    for status in (CheckStatus.PARSE_ERROR, CheckStatus.MISMATCH):
        for result in results:
            if result.status is status:
                return result
    return results[0]


def _unrecognized(site: str, unrecognized: tuple[str, ...]) -> CheckResult:
    if unrecognized:
        return CheckResult.structure_changed(
            site,
            UNRECOGNIZED,
            detail=f"unrecognized holiday rows: {list(unrecognized)}",
            summary=f"{len(unrecognized)} holiday row(s) not recognized",
        )
    return CheckResult.ok(site, UNRECOGNIZED, expected="none", observed="none")


def _expired(
    site: str,
    items: tuple[ListedHours, ...],
    judged: set[int],
    today: dt.date,
) -> CheckResult:
    """Dated entries that ended before today and weren't judged for a configured holiday."""
    expired = [
        item.label
        for index, item in enumerate(items)
        if index not in judged and item.end is not None and item.end < today
    ]
    if expired:
        listing = ", ".join(expired)
        return CheckResult.mismatch(
            site,
            EXPIRED,
            expected="no expired special hours",
            observed=listing,
            summary=f"special hours for past date(s) still listed: {listing}",
        )
    return CheckResult.ok(site, EXPIRED, expected="none expired", observed="none expired")
