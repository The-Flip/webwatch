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
appears outside the card, and no holiday row is left in it without its heading;
otherwise (all or part of) the section moved and the listing is ``missing``
(``STRUCTURE_CHANGED``), never a false "none posted". A holiday row under the
heading whose markup we can't read is kept as unrecognized, not dropped.

There is no ``openingHours`` JSON-LD on the page, so there is no corroboration
source here (and no ``METADATA_DRIFT`` path); the visible card is authoritative. If
the page later adds structured hours, this source can read them as corroboration
without changing the visible-text path.
"""

from __future__ import annotations

from dataclasses import dataclass, field
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


@dataclass(slots=True)
class _CardRows:
    """The Hours card's rows, split at its "Holiday Hours" heading."""

    regular: list[tuple[str, str]] = field(default_factory=list)
    #: ``None`` when the card has no "Holiday Hours" heading.
    holiday: list[tuple[str, str]] | None = None
    #: Holiday labels under the heading that aren't in a readable row.
    unreadable: list[str] = field(default_factory=list)


def _split_rows(card: Tag) -> _CardRows:
    """The card's rows, split at its "Holiday Hours" heading.

    Rows are read in document order; every row after the first "Holiday Hours"
    heading is a holiday row, so a holiday label can never leak into the weekly
    hours. Below the heading, a holiday label that isn't part of a readable row
    (its markup changed) is kept as ``unreadable`` rather than silently dropped.
    """
    rows = _CardRows()
    for element in card.find_all(True):
        if rows.holiday is None and _is_holiday_heading(element):
            rows.holiday = []
            continue
        pair = _row_pair(element)
        if pair is not None:
            (rows.regular if rows.holiday is None else rows.holiday).append(pair)
        elif rows.holiday is not None and _is_loose_holiday_label(element):
            rows.unreadable.append(normalize.collapse_whitespace(element.get_text(" ")))
    return rows


def _is_loose_holiday_label(element: Tag) -> bool:
    """A leaf naming a holiday that isn't the label of a readable two-span row."""
    if element.find(True) is not None:
        return False
    if holidays.holiday_for_label(element.get_text(" ", strip=True)) is None:
        return False
    parent = element.parent
    return not (isinstance(parent, Tag) and _row_pair(parent) is not None)


def _holiday_listing(
    soup: BeautifulSoup, card: Tag | None, rows: _CardRows
) -> Observed[HolidayListing]:
    """The holiday rows under the card's holiday heading, honestly.

    ``missing`` (never a false "none posted") when: there is no card; any holiday
    heading or holiday row appears outside the card (all or part of the section
    moved); holiday rows sit in the card without their heading; or the heading has
    no readable rows under it. No heading and no holiday rows -> an empty listing
    (off-season). A blank value -> ``unparseable``, never compared.
    """
    if card is None:
        return Observed.missing("hours card not found")
    if _holiday_content_outside(soup, card):
        return Observed.missing("holiday hours appear outside the Hours card")
    if rows.holiday is None:
        if any(holidays.holiday_for_label(label) for label, _ in rows.regular):
            return Observed.missing("holiday rows in the Hours card without their heading")
        return Observed.found(HolidayListing())
    if not rows.holiday:
        return Observed.missing("Holiday Hours heading has no readable rows")

    items: list[ListedHours] = []
    unrecognized: list[str] = list(rows.unreadable)
    for label, value in rows.holiday:
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
        rows = _split_rows(card) if card is not None else _CardRows()
        for label, value in rows.regular:
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
            holiday_hours=_holiday_listing(soup, card, rows),
        )


SOURCE = TheFlipMuseumVisit()


CHECKS = hours_checks()
