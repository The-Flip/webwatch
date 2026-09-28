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

from typing import Any

from bs4 import BeautifulSoup, Tag

from webwatch import normalize
from webwatch.checks.registry import hours_checks
from webwatch.events import extract_events
from webwatch.sources.base import Observation, Observed, Source


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
    tracks = frozenset(f"hours.{day}" for day in normalize.WEEKDAYS)
    provides_events = True

    def observe(self, html: str) -> Observation:
        # Start with every weekday missing; overwrite only those the card yields.
        fields: dict[str, Observed[str]] = {
            f"hours.{day}": Observed.missing("hours card or this day not found")
            for day in normalize.WEEKDAYS
        }
        card = _find_hours_card(BeautifulSoup(html, "lxml"))
        if card is not None:
            for label, value in _row_pairs(card):
                for day in normalize.expand_days(label):
                    fields[f"hours.{day}"] = Observed.found(value)

        parsed = extract_events(html)
        events: Observed[Any] = (
            Observed.found(parsed)
            if parsed is not None
            else Observed.missing("no upcoming events section found")
        )
        return Observation(self.site, fields, events=events)


SOURCE = TheFlipMuseumVisit()


CHECKS = hours_checks()
