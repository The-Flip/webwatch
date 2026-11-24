"""Source for the museum's "Plan Your Visit" page, https://www.theflip.museum/visit.

The homepage doesn't publish opening hours; this page does — as visible text, not
JSON-LD. The hours live in a card: an ``<h3>Hours</h3>`` heading followed by rows,
each a container with two ``<span>``s (a day label and a time value), e.g.:

    Monday - Saturday   10a - 8p
    Sunday              11a -6p
    ── Holiday Hours ──
    Thanksgiving        Closed
    Christmas Eve       10a - 3p

So this source reads each weekday's hours from the rows *above* the card's
"Holiday Hours" heading (document order), so a holiday row can never leak into the
weekly hours. Day labels may be ranges ("Monday - Saturday") which expand to each
weekday; non-weekday rows are ignored. The raw time text is left for
``normalize.day_hours`` to parse, so ``"10a - 8p"`` and a facts value of
``"10:00 - 20:00"`` compare equal.

The rows *below* the heading are the holiday hours (undated; judged against the
calendar by ``webwatch.holiday_hours``). Off-season the section is removed, which
reads as "none posted" — but only if no holiday heading or holiday-labelled row
appears anywhere else on the page; otherwise the section moved and the listing is
``missing`` (``STRUCTURE_CHANGED``), never a false "none posted".

There is no ``openingHours`` JSON-LD on the page, so there is no corroboration
source here (and no ``METADATA_DRIFT`` path); the visible card is authoritative. If
the page later adds structured hours, this source can read them as corroboration
without changing the visible-text path.
"""

from __future__ import annotations

from typing import Any

from bs4 import BeautifulSoup, Tag

from webwatch import holidays, normalize
from webwatch.checks.registry import hours_checks
from webwatch.events import extract_events
from webwatch.sources.base import HolidayListing, ListedHours, Observation, Observed, Source

_HEADINGS = ("h1", "h2", "h3", "h4", "h5", "h6")


def _find_hours_card(soup: BeautifulSoup) -> Tag | None:
    """The container around the heading whose text is exactly 'Hours'."""
    for heading in soup.find_all(_HEADINGS):
        if normalize.text(heading.get_text()) == "hours":
            parent = heading.parent
            return parent if isinstance(parent, Tag) else None
    return None


def _is_holiday_heading(element: Tag) -> bool:
    """A "Holiday Hours" heading — not any heading that merely mentions a holiday
    (an events heading like "Holiday Pinball Party" must not split or relocate it)."""
    return element.name in _HEADINGS and "holiday hours" in normalize.text(element.get_text())


def _row_pair(element: Tag) -> tuple[str, str] | None:
    """(label, value) if ``element`` *directly* contains exactly two spans, else None.

    The ``section-divider`` and description elements have none and are skipped (so we
    never crash unpacking).
    """
    spans = element.find_all("span", recursive=False)
    if len(spans) != 2:
        return None
    label = normalize.collapse_whitespace(spans[0].get_text(" ", strip=True))
    value = normalize.collapse_whitespace(spans[1].get_text(" ", strip=True))
    return label, value


def _split_rows(card: Tag) -> tuple[list[tuple[str, str]], list[tuple[str, str]] | None]:
    """The card's (regular rows, holiday rows), split at its "Holiday Hours" heading.

    Rows are read in document order; every row after the first "Holiday Hours"
    heading is a holiday row, so a holiday label can never leak into the weekly
    hours. Holiday rows are ``None`` when the card has no such heading (the section
    is legitimately removed off-season).
    """
    regular: list[tuple[str, str]] = []
    holiday: list[tuple[str, str]] | None = None
    for element in card.find_all(True):
        if holiday is None and _is_holiday_heading(element):
            holiday = []
            continue
        pair = _row_pair(element)
        if pair is not None:
            (regular if holiday is None else holiday).append(pair)
    return regular, holiday


def _holiday_listing(
    soup: BeautifulSoup, card: Tag | None, rows: list[tuple[str, str]] | None
) -> Observed[HolidayListing]:
    """The holiday rows under the card's holiday heading, honestly.

    No card -> ``missing``. No heading in the card -> an empty listing, unless holiday
    content appears elsewhere on the page (the section moved) -> ``missing``. A
    heading with no readable rows under it -> ``missing`` (the row markup changed;
    that is not "none posted"). A blank value -> ``unparseable``, never compared.
    """
    if card is None:
        return Observed.missing("hours card not found")
    if rows is None:
        if _holiday_content_outside(soup, card):
            return Observed.missing("holiday hours appear outside the Hours card")
        return Observed.found(HolidayListing())
    if not rows:
        return Observed.missing("Holiday Hours heading has no readable rows")

    items: list[ListedHours] = []
    unrecognized: list[str] = []
    for label, value in rows:
        holiday = holidays.holiday_for_label(label)
        if holiday is None:
            unrecognized.append(label)
        else:
            hours = Observed.found(value) if value else Observed.unparseable("blank hours")
            items.append(ListedHours(label, hours, holiday=holiday))
    return Observed.found(HolidayListing(tuple(items), tuple(unrecognized)))


def _holiday_content_outside(soup: BeautifulSoup, card: Tag) -> bool:
    """A holiday heading or holiday-labelled row anywhere outside ``card``."""
    inside = {id(element) for element in card.find_all(True)}
    for element in soup.find_all(True):
        if id(element) in inside:
            continue
        if _is_holiday_heading(element):
            return True
        pair = _row_pair(element)
        if pair is not None and holidays.holiday_for_label(pair[0]) is not None:
            return True
    return False


class TheFlipMuseumVisit(Source):
    name = "theflip_museum_visit"
    label = "Visit page"
    url = "https://www.theflip.museum/visit"
    tracks = frozenset(f"hours.{day}" for day in normalize.WEEKDAYS)
    provides_events = True
    provides_holiday_hours = True

    def observe(self, html: str) -> Observation:
        # Start with every weekday missing; overwrite only those the card yields.
        fields: dict[str, Observed[str]] = {
            f"hours.{day}": Observed.missing("hours card or this day not found")
            for day in normalize.WEEKDAYS
        }
        soup = BeautifulSoup(html, "lxml")
        card = _find_hours_card(soup)
        regular, holiday_rows = _split_rows(card) if card is not None else ([], None)
        for label, value in regular:
            for day in normalize.expand_days(label):
                fields[f"hours.{day}"] = Observed.found(value)

        parsed = extract_events(html)
        events: Observed[Any] = (
            Observed.found(parsed)
            if parsed is not None
            else Observed.missing("no upcoming events section found")
        )
        return Observation(
            self.site,
            fields,
            events=events,
            holiday_hours=_holiday_listing(soup, card, holiday_rows),
        )


SOURCE = TheFlipMuseumVisit()


CHECKS = hours_checks()
