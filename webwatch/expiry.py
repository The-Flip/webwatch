"""Flag events that should no longer be displayed.

An event must not appear past midnight of the day it ends. The event cards carry
no year — only a "Jun 27" badge and a weekday — so the end date's year is inferred
from the nearby year whose month/day lands on the stated weekday and is closest to
``now``. A date that can't be pinned confidently is skipped rather than guessed, so
the check never raises a false alarm. See ``docs/plans/expired-events-check.md``.
"""

from __future__ import annotations

import datetime as dt

from webwatch import normalize
from webwatch.events import Event
from webwatch.result import CheckResult
from webwatch.sources.base import Observed

_MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}  # fmt: skip
_WEEKDAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")


def _month_number(text: str) -> int | None:
    return _MONTHS.get(text.strip().lower()[:3])


def end_date(event: Event, *, now: dt.datetime) -> dt.date | None:
    """Infer an event's end date, or ``None`` if it can't be pinned confidently.

    Tries the years around ``now``; when the card shows a weekday, keeps only the
    candidate years whose date falls on that weekday; returns the survivor closest
    to ``now``.
    """
    month = _month_number(event.month)
    if month is None or not event.day.isdigit():
        return None
    day = int(event.day)

    wanted_weekday = normalize.text(event.weekday) if event.weekday else ""
    candidates: list[dt.date] = []
    for year in (now.year - 1, now.year, now.year + 1):
        try:
            candidate = dt.date(year, month, day)
        except ValueError:
            continue  # e.g. Feb 29 in a non-leap year
        if wanted_weekday and _WEEKDAYS[candidate.weekday()] != wanted_weekday:
            continue
        candidates.append(candidate)

    if not candidates:
        return None
    return min(candidates, key=lambda d: abs((d - now.date()).days))


def check_expired_events(
    observed_events: Observed[list[Event]],
    *,
    now: dt.datetime,
    site: str,
    name: str = "expired_events",
) -> CheckResult:
    """OK unless an event whose end date is before today is still listed."""
    if not observed_events.is_found:
        return CheckResult.structure_changed(site, name, detail="could not read the events list")

    events: list[Event] = observed_events.value or []
    today = now.date()
    expired: list[str] = []
    indeterminate: list[str] = []
    for event in events:
        ended = end_date(event, now=now)
        if ended is None:
            indeterminate.append(event.title)
        elif today > ended:
            expired.append(f"{event.title} ({event.month} {event.day})")

    note = f"; {len(indeterminate)} with indeterminate dates" if indeterminate else ""
    if expired:
        listing = ", ".join(expired)
        return CheckResult.mismatch(
            site,
            name,
            expected="no expired events listed",
            observed=listing,
            summary=f"{len(expired)} expired event(s) still shown: {listing}{note}",
        )
    return CheckResult.ok(
        site, name, expected="no expired events", observed=f"{len(events)} event(s){note}"
    )
