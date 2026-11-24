"""The named holidays webwatch knows, and when they fall.

A small fixed vocabulary rather than a general date grammar: adding a holiday is
one entry here (plus a test of its dates). ``facts.yaml``'s ``holiday_hours`` keys
must come from :data:`NAMES`, so a typo fails loudly at load instead of silently
never being checked. Pure: no clock — callers pass ``today``.
"""

from __future__ import annotations

import calendar
import datetime as dt
import re
from collections.abc import Callable
from dataclasses import dataclass

from webwatch import normalize


def _nth_weekday(year: int, month: int, weekday: int, n: int) -> dt.date:
    """The ``n``-th ``weekday`` (Mon=0) of ``month``, e.g. the 4th Thursday of November."""
    first = dt.date(year, month, 1)
    offset = (weekday - first.weekday()) % 7
    return first + dt.timedelta(days=offset + 7 * (n - 1))


def _fixed(month: int, day: int) -> Callable[[int], dt.date]:
    return lambda year: dt.date(year, month, day)


@dataclass(frozen=True, slots=True)
class Holiday:
    label: str
    date_for: Callable[[int], dt.date]
    #: Visible labels a page may use, compared after :func:`_label_key`.
    aliases: tuple[str, ...]


_HOLIDAYS: dict[str, Holiday] = {
    "thanksgiving": Holiday(
        "Thanksgiving",
        lambda year: _nth_weekday(year, 11, calendar.THURSDAY, 4),
        ("thanksgiving", "thanksgiving day"),
    ),
    "christmas_eve": Holiday("Christmas Eve", _fixed(12, 24), ("christmas eve",)),
    "christmas": Holiday("Christmas Day", _fixed(12, 25), ("christmas", "christmas day")),
    "new_years_eve": Holiday("New Year's Eve", _fixed(12, 31), ("new years eve",)),
    "new_years_day": Holiday("New Year's Day", _fixed(1, 1), ("new years", "new years day")),
}

#: Every holiday name ``facts.yaml`` may use, in calendar order.
NAMES: tuple[str, ...] = tuple(_HOLIDAYS)


def label(name: str) -> str:
    """The human name for reports, e.g. ``"Christmas Eve"``."""
    return _HOLIDAYS[name].label


def date_of(name: str, year: int) -> dt.date:
    """The date of holiday ``name`` in ``year``. Raises ``KeyError`` for an unknown name."""
    return _HOLIDAYS[name].date_for(year)


def next_occurrence(name: str, today: dt.date) -> dt.date:
    """The holiday's date on or after ``today``."""
    this_year = date_of(name, today.year)
    return this_year if this_year >= today else date_of(name, today.year + 1)


def previous_occurrence(name: str, today: dt.date) -> dt.date:
    """The holiday's most recent date strictly before ``today``."""
    this_year = date_of(name, today.year)
    return this_year if this_year < today else date_of(name, today.year - 1)


_CURLY_APOSTROPHE = chr(0x2019)


def _label_key(text: str) -> str:
    """Case/space-insensitive, apostrophe- and trailing-punctuation-free label key."""
    folded = text.replace(_CURLY_APOSTROPHE, "").replace("'", "")
    return normalize.text(re.sub(r"[:.\s]+$", "", folded.strip()))


_BY_ALIAS = {alias: name for name, h in _HOLIDAYS.items() for alias in h.aliases}


def holiday_for_label(text: str) -> str | None:
    """The holiday a visible label names, or ``None`` if it isn't one we know.

    Exact alias match only — "Christmas Week" is not Christmas. An unrecognized
    label is never guessed into a holiday.
    """
    return _BY_ALIAS.get(_label_key(text))
