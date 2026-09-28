"""Source for The Flip's Apple Maps place page.

Apple Maps place pages (``maps.apple.com/place?place-id=…``) are server-rendered:
the visible "Details" section carries cells titled by a heading — **Hours**,
**Website**, **Phone**, **Address** — and the business name is the card's ``h1``.
Those visible values are authoritative.

The page also embeds Apple's own place payload as JSON in
``<script id="shell-props">``: an entity (name, telephone, url) and a business-hours
component (``weeklyHours``, seconds since midnight, closed days omitted). That is
used only as *corroboration* — a stale payload behind correct visible values is
``METADATA_DRIFT``, never ``MISMATCH``.

Hours appear twice on the page: a folded summary showing *today only*, and an
unfolded block listing the whole week as rows (closed days are explicit "Closed"
rows). We read the block that has rows, so today's hours are never mistaken for the
week's.

Identity is guarded twice, because a listing can be merged or a place-id mistyped:

- Here, purely, as a coarse filter: the page must mention the place-id we asked
  for (in its payload or its directions link); otherwise every field is
  ``missing``. This catches redirects and merges, but a page can mention more
  than one place, so it doesn't prove the visible card is ours.
- In the checks, decisively: the non-name checks ``require`` the ``name`` check,
  so a card for some other business yields one ``name`` MISMATCH rather than a
  burst of false ones.

An unknown place-id is an HTTP 404, which the fetch layer reports as ``FETCH_ERROR``.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any
from urllib.parse import parse_qs, urlsplit

from bs4 import BeautifulSoup, Tag

from webwatch import normalize
from webwatch.checks.registry import Check, hours_checks
from webwatch.sources.base import Observation, Observed, Source

_HOURS_FIELDS = tuple(f"hours.{day}" for day in normalize.WEEKDAYS)
_SECONDS_PER_DAY = 24 * 60 * 60

# Apple's payload vocabulary.
_ENTITY = "COMPONENT_TYPE_ENTITY"
_BUSINESS_HOURS = "COMPONENT_TYPE_BUSINESS_HOURS"
_REGULAR_HOURS = "NORMAL"


def _place_id(url: str) -> str:
    """The ``place-id`` query parameter of an Apple Maps URL."""
    values = parse_qs(urlsplit(url).query).get("place-id", [])
    if len(values) != 1 or not values[0]:
        raise ValueError(f"Apple Maps URL has no single place-id: {url!r}")
    return values[0]


# --- the embedded place payload ----------------------------------------------------


def _shell_props(soup: BeautifulSoup) -> dict[str, Any] | None:
    script = soup.find("script", id="shell-props")
    if not isinstance(script, Tag):
        return None
    try:
        payload = json.loads(script.get_text())
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def _cached_places(payload: dict[str, Any] | None) -> Iterator[dict[str, Any]]:
    if payload is None:
        return
    cache = (payload.get("initialState") or {}).get("placeCache") or {}
    if isinstance(cache, dict):
        yield from (place for place in cache.values() if isinstance(place, dict))


def _payload_place_id(place: dict[str, Any]) -> str | None:
    place_id = ((place.get("mapsId") or {}).get("shardedId") or {}).get("placeId")
    return place_id if isinstance(place_id, str) else None


def _component(place: dict[str, Any], component_type: str) -> dict[str, Any] | None:
    """The first value of a payload component, or ``None`` if absent/empty."""
    for component in place.get("component") or []:
        if isinstance(component, dict) and component.get("type") == component_type:
            values = component.get("value") or []
            if values and isinstance(values[0], dict):
                return values[0]
    return None


def _clock(seconds: int) -> str:
    seconds %= _SECONDS_PER_DAY  # an overnight close is stored past midnight
    return f"{seconds // 3600:02d}:{seconds % 3600 // 60:02d}"


def _entity_values(place: dict[str, Any]) -> dict[str, Any]:
    """Name, phone, and website from the payload's entity (whichever are present)."""
    entity = (_component(place, _ENTITY) or {}).get("entity") or {}
    values: dict[str, Any] = {}
    names = entity.get("name") or []
    if names and isinstance(names[0], dict) and names[0].get("stringValue"):
        values["name"] = names[0]["stringValue"]
    if entity.get("telephone"):
        values["phone"] = entity["telephone"]
    if entity.get("url"):
        values["url"] = entity["url"]
    return values


def _business_hours(place: dict[str, Any]) -> dict[str, Any]:
    hours = (_component(place, _BUSINESS_HOURS) or {}).get("businessHours")
    return hours if isinstance(hours, dict) else {}


def _hours_values(place: dict[str, Any]) -> dict[str, str]:
    """Per-day ``hours.<day>`` corroboration from the payload, if it is well-formed."""
    weekly = _weekly_hours(_business_hours(place).get("weeklyHours"))
    return {} if weekly is None else {f"hours.{day}": v for day, v in weekly.items()}


def _hours_type(place: dict[str, Any]) -> str | None:
    """Apple's ``hoursType`` ("NORMAL" for regular hours), if stated."""
    hours_type = _business_hours(place).get("hoursType")
    return hours_type if isinstance(hours_type, str) else None


def _weekly_hours(entries: object) -> dict[str, str] | None:
    """Per-day hours text from ``weeklyHours``; a day it omits is ``"closed"``.

    Returns ``None`` (no corroboration) if the shape isn't exactly what we model —
    this is Apple's internal payload, so it must never crash or guess.
    """
    # An empty list is "no data", not "closed every day".
    if not isinstance(entries, list) or not entries:
        return None
    windows: dict[str, list[str]] = {day: [] for day in normalize.WEEKDAYS}
    for entry in entries:
        if not isinstance(entry, dict):
            return None
        days, spans = entry.get("day"), entry.get("timeRange")
        if not isinstance(days, list) or not isinstance(spans, list):
            return None
        for day in days:
            key = str(day).lower()
            if key not in windows:
                return None
            for span in spans:
                start = span.get("from") if isinstance(span, dict) else None
                end = span.get("to") if isinstance(span, dict) else None
                if not isinstance(start, int) or not isinstance(end, int):
                    return None
                windows[key].append(f"{_clock(start)} - {_clock(end)}")
    return {day: ", ".join(spans) if spans else "closed" for day, spans in windows.items()}


# --- the visible page -------------------------------------------------------------


def _page_place_ids(soup: BeautifulSoup, payload: dict[str, Any] | None) -> set[str]:
    """Every place-id the page claims to be about (payload + directions link)."""
    ids = {pid for place in _cached_places(payload) if (pid := _payload_place_id(place))}
    for link in soup.select("a[href*='destination-place-id=']"):
        query = parse_qs(urlsplit(str(link["href"])).query)
        ids.update(query.get("destination-place-id", []))
    return ids


def _cells(soup: BeautifulSoup, title: str) -> list[Tag]:
    """The Details cells (``section``s) whose heading text is exactly ``title``."""
    cells = []
    for heading in soup.find_all("h3"):
        if normalize.text(heading.get_text()) == normalize.text(title):
            section = heading.find_parent("section")
            if section is not None:
                cells.append(section)
    return cells


def _text(tag: Tag) -> str:
    return normalize.collapse_whitespace(tag.get_text(" ", strip=True))


def _exactly_one(values: list[str], what: str) -> Observed[str]:
    """``found`` for a single unambiguous value; ``missing`` for none or several."""
    if len(values) != 1:
        return Observed.missing(f"expected one {what}, found {len(values)}")
    return Observed.found(values[0])


def _name(soup: BeautifulSoup) -> Observed[str]:
    # The card title; a duplicate in the shell header is aria-hidden, and a
    # visually-hidden h1 reads "Apple Maps" — neither is the place name.
    titles = {
        _text(h1)
        for h1 in soup.select("h1.sc-header-title")
        if h1.get("aria-hidden") != "true" and _text(h1)
    }
    return _exactly_one(sorted(titles), "place title")


def _website(soup: BeautifulSoup) -> Observed[str]:
    hrefs = [str(a["href"]) for cell in _cells(soup, "Website") for a in cell.select("a[href]")]
    return _exactly_one(hrefs, "Website link")


def _phone(soup: BeautifulSoup) -> Observed[str]:
    numbers = [_text(n) for cell in _cells(soup, "Phone") for n in cell.select(".sc-phone-number")]
    return _exactly_one(numbers, "Phone number")


def _hours(soup: BeautifulSoup) -> dict[str, Observed[str]]:
    """Each weekday's visible hours; a day no row covers stays ``missing``."""
    fields: dict[str, Observed[str]] = {
        field: Observed.missing("hours block or this day not found") for field in _HOURS_FIELDS
    }
    # The today-only summary has no rows; the full-week block does.
    blocks = [cell for cell in _cells(soup, "Hours") if cell.select(".sc-hours-row")]
    if len(blocks) != 1:
        return fields
    for row in blocks[0].select(".sc-hours-row"):
        label = row.select_one(".sc-hours-day")
        hours = row.select_one(".sc-hours-range")
        if label is None or hours is None:
            continue
        ranges = hours.select(".sc-time-range")
        value = ", ".join(_text(r) for r in ranges) if ranges else _text(hours)
        for day in normalize.expand_days(_text(label)):
            fields[f"hours.{day}"] = Observed.found(value)
    return fields


def _regular_hours(soup: BeautifulSoup, hours_type: str | None) -> dict[str, Observed[str]]:
    """The visible weekly hours — unless Apple says it's showing non-regular hours.

    Holiday/temporary hours compared against our regular hours would be a false
    MISMATCH, so while they're shown every day is ``missing`` instead.
    """
    if hours_type is not None and hours_type != _REGULAR_HOURS:
        note = f"Apple is showing non-regular hours (hoursType={hours_type!r})"
        return {field: Observed.missing(note) for field in _HOURS_FIELDS}
    return _hours(soup)


class AppleMaps(Source):
    name = "apple_maps"
    url = "https://maps.apple.com/place?place-id=I807CC9ABBE1179A2"
    tracks = frozenset({"name", "url", "phone", *_HOURS_FIELDS})

    def observe(self, html: str) -> Observation:
        soup = BeautifulSoup(html, "lxml")
        payload = _shell_props(soup)
        wanted = _place_id(self.url)

        page_ids = _page_place_ids(soup, payload)
        if wanted not in page_ids:
            note = (
                f"page is about place-id {sorted(page_ids)}, not {wanted!r} (listing merged?)"
                if page_ids
                else "page does not state which place-id it is about"
            )
            return Observation(self.site, {field: Observed.missing(note) for field in self.tracks})

        place = next((p for p in _cached_places(payload) if _payload_place_id(p) == wanted), {})
        fields: dict[str, Observed[str]] = {
            "name": _name(soup),
            "url": _website(soup),
            "phone": _phone(soup),
            **_regular_hours(soup, _hours_type(place)),
        }
        structured = {**_entity_values(place), **_hours_values(place)}
        return Observation(self.site, fields, structured=structured)


SOURCE = AppleMaps()

CHECKS = [
    Check("name", lambda f: f.organization.name, normalize.text, structured_field="name"),
    Check(
        "url",
        lambda f: f.organization.url,
        normalize.url,
        structured_field="url",
        requires="name",
    ),
    Check(
        "phone",
        lambda f: f.organization.phone,
        normalize.phone,
        structured_field="phone",
        requires="name",
    ),
    *hours_checks(structured=True, requires="name"),
]
