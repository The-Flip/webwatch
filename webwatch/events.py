"""Extract upcoming events from a page's "Upcoming Events" section.

Events on theflip.museum are not in JSON-LD; they are cards under an "Upcoming
Events" heading, each with a date badge, an ``<h4>`` title, a meta line
(``weekday · time · location``), an optional description, and an optional
"Recurring" tag. This module reads those cards into :class:`Event` objects for the
rules engine (``webwatch.rules``).

``extract_events`` returns ``None`` when the events *section* can't be located
(so the source can report it missing) versus an empty list when the section is
present but lists nothing — keeping the honest found-vs-missing distinction.
"""

from __future__ import annotations

from dataclasses import dataclass

from bs4 import BeautifulSoup, Tag

from webwatch import normalize

# Middot separator in the meta line, via chr() to avoid an ambiguous-unicode lint.
_MIDDOT = chr(0x00B7)


@dataclass(frozen=True, slots=True)
class Event:
    title: str
    weekday: str = ""
    time: str = ""
    recurring: bool = False
    month: str = ""
    day: str = ""
    description: str = ""


def _event_cards(scope: Tag) -> list[Tag]:
    """Event cards within ``scope``: a ``.card`` containing an ``<h4>`` title.

    The ``<h4>`` discriminates event cards from the Hours card (which uses ``<h3>``)
    and other ``.card`` elements on the page.
    """
    return [card for card in scope.select("div.card") if card.find("h4")]


def _find_events_section(soup: BeautifulSoup) -> Tag | None:
    """The nearest ancestor of the 'Upcoming Events' heading that holds event cards."""
    for heading in soup.find_all(["h1", "h2", "h3", "h4"]):
        if normalize.text(heading.get_text()) != "upcoming events":
            continue
        ancestor: Tag | None = heading
        for _ in range(5):
            ancestor = ancestor.parent if ancestor else None
            if ancestor is None:
                break
            if _event_cards(ancestor):
                return ancestor
    return None


def _badge(card: Tag) -> tuple[str, str]:
    """(month, day) from the date badge — the first div with exactly two spans."""
    for div in card.find_all("div"):
        spans = div.find_all("span", recursive=False)
        if len(spans) == 2:
            return spans[0].get_text(strip=True), spans[1].get_text(strip=True)
    return "", ""


def _parse_card(card: Tag) -> Event:
    heading = card.find("h4")
    title = normalize.collapse_whitespace(heading.get_text(" ", strip=True)) if heading else ""

    paragraphs = card.find_all("p")
    meta = (
        normalize.collapse_whitespace(paragraphs[0].get_text(" ", strip=True)) if paragraphs else ""
    )
    description = (
        normalize.collapse_whitespace(paragraphs[1].get_text(" ", strip=True))
        if len(paragraphs) > 1
        else ""
    )

    parts = [part.strip() for part in meta.split(_MIDDOT) if part.strip()]
    weekday = parts[0] if len(parts) >= 1 else ""
    time = parts[1] if len(parts) >= 2 else ""

    recurring = card.find(string=lambda s: s and s.strip().lower() == "recurring") is not None
    month, day = _badge(card)
    return Event(
        title=title,
        weekday=weekday,
        time=time,
        recurring=recurring,
        month=month,
        day=day,
        description=description,
    )


def extract_events(html: str) -> list[Event] | None:
    """All events in the page's Upcoming Events section, or ``None`` if absent."""
    soup = BeautifulSoup(html, "lxml")
    section = _find_events_section(soup)
    if section is None:
        return None
    return [_parse_card(card) for card in _event_cards(section)]
