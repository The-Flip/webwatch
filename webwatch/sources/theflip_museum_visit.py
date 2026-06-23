"""Source for the museum's "Plan Your Visit" page, https://www.theflip.museum/visit.

The homepage doesn't publish opening hours; this page does — as visible text, not
JSON-LD. The hours live in a card: an ``<h3>Hours</h3>`` heading followed by rows,
each a container with two ``<span>``s (a day label and a time value), e.g.:

    Monday - Saturday   10a - 8p
    Sunday              11a -6p
    Private Tours       By appointment ...

So this source reads each weekday's hours from that card. Day labels may be ranges
("Monday - Saturday") which expand to each weekday; non-weekday rows ("Private
Tours") are ignored. The raw time text is left for ``normalize.day_hours`` to parse,
so ``"10a - 8p"`` and a facts value of ``"10:00 - 20:00"`` compare equal.

There is no ``openingHours`` JSON-LD on the page, so there is no corroboration
source here (and no ``METADATA_DRIFT`` path); the visible card is authoritative. If
the page later adds structured hours, this source can read them as corroboration
without changing the visible-text path.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any

from bs4 import BeautifulSoup, Tag

from webwatch import normalize
from webwatch.checks.registry import Check
from webwatch.events import extract_events
from webwatch.facts import Facts
from webwatch.sources.base import Observation, Observed, Source

_WEEKDAYS = (
    "monday",
    "tuesday",
    "wednesday",
    "thursday",
    "friday",
    "saturday",
    "sunday",
)
_DAY_INDEX = {day: i for i, day in enumerate(_WEEKDAYS)}
# Full names and 3-letter abbreviations both resolve to the canonical weekday.
_DAY_ALIASES = {alias: day for day in _WEEKDAYS for alias in (day, day[:3])}

# Split a day range on a dash (hyphen/en/em) or a space-delimited "to". Built via
# chr() to avoid ambiguous-unicode literals; "to" is space-bounded so it doesn't
# split inside words like "Tours".
_DASHES = re.escape("-" + chr(0x2013) + chr(0x2014))
_DAY_RANGE_SEP = re.compile(rf"\s*[{_DASHES}]\s*|\s+to\s+", re.IGNORECASE)


def expand_days(label: str) -> list[str]:
    """Expand a day label into canonical weekdays.

    ``"Monday - Saturday"`` -> the six days; ``"Sunday"`` -> ``["sunday"]``;
    a wrap-around like ``"Saturday - Tuesday"`` -> sat, sun, mon, tue. Anything not
    recognizable as a day (or range) yields ``[]`` — so an unreadable label degrades
    to a missing day, never a guess.
    """
    parts = [part for part in _DAY_RANGE_SEP.split(label.strip().lower()) if part]
    mapped = [_DAY_ALIASES.get(part) for part in parts]
    if len(mapped) == 1 and mapped[0] is not None:
        return [mapped[0]]
    if len(mapped) == 2 and all(mapped):
        start, end = _DAY_INDEX[mapped[0]], _DAY_INDEX[mapped[1]]  # type: ignore[index]
        if start <= end:
            return list(_WEEKDAYS[start : end + 1])
        return list(_WEEKDAYS[start:]) + list(_WEEKDAYS[: end + 1])
    return []


def _find_hours_card(soup: BeautifulSoup) -> Tag | None:
    """The container around the heading whose text is exactly 'Hours'."""
    for heading in soup.find_all(["h1", "h2", "h3", "h4", "h5", "h6"]):
        if normalize.text(heading.get_text()) == "hours":
            parent = heading.parent
            return parent if isinstance(parent, Tag) else None
    return None


def _row_pairs(card: Tag) -> list[tuple[str, str]]:
    """(day-label, time-value) pairs from the card's rows.

    A row is an element that *directly* contains two spans; the ``section-divider``
    and description elements have none and are skipped (so we never crash unpacking).
    """
    pairs: list[tuple[str, str]] = []
    for element in card.find_all(True):
        spans = element.find_all("span", recursive=False)
        if len(spans) == 2:
            label = normalize.collapse_whitespace(spans[0].get_text(" ", strip=True))
            value = normalize.collapse_whitespace(spans[1].get_text(" ", strip=True))
            pairs.append((label, value))
    return pairs


class TheFlipMuseumVisit(Source):
    name = "theflip_museum_visit"
    url = "https://www.theflip.museum/visit"
    tracks = frozenset(f"hours.{day}" for day in _WEEKDAYS)
    provides_events = True

    def observe(self, html: str) -> Observation:
        # Start with every weekday missing; overwrite only those the card yields.
        fields: dict[str, Observed[str]] = {
            f"hours.{day}": Observed.missing("hours card or this day not found")
            for day in _WEEKDAYS
        }
        card = _find_hours_card(BeautifulSoup(html, "lxml"))
        if card is not None:
            for label, value in _row_pairs(card):
                for day in expand_days(label):
                    fields[f"hours.{day}"] = Observed.found(value)

        parsed = extract_events(html)
        events: Observed[Any] = (
            Observed.found(parsed)
            if parsed is not None
            else Observed.missing("no upcoming events section found")
        )
        return Observation(self.site, fields, events=events)


SOURCE = TheFlipMuseumVisit()


def _hours_getter(day: str) -> Callable[[Facts], Any]:
    """A factory so each check captures its own ``day`` (no late-binding closure trap)."""
    return lambda facts: facts.organization.hours.get(day)


CHECKS = [Check(f"hours.{day}", _hours_getter(day), normalize.day_hours) for day in _WEEKDAYS]
