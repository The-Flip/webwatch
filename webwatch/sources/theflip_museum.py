"""Source for the museum's own website, https://www.theflip.museum/.

What the homepage actually exposes (verified from a captured fixture): the name,
postal address, and email — all in a JSON-LD ``Museum`` node, and all also shown
in the footer. It does **not** publish a phone number or opening hours on the
homepage, so this source does not track those (they are ``NOT_SUPPORTED`` -> a
check ``SKIPPED``, never a false structure alarm). Hours will get their own source
on the "Plan Your Visit" page in a later phase.

Anchoring decision (documented deliberately): the homepage has no microdata or
microformats, so the stable machine-readable anchor for these facts is the JSON-LD
``Museum`` node. To honor "visible text is authoritative" (``docs/Extraction.md``)
without a per-field visible anchor, each JSON-LD value is trusted only if it also
appears in the page's visible text; if JSON-LD is missing, or its value is not
visible on the page, the field is reported ``STRUCTURE_CHANGED`` rather than
guessed. So a value is asserted only when structured data *and* the visible page
agree it is there.

**Deliberate exception — holiday hours.** The ``Museum`` node's
``specialOpeningHoursSpecification`` is not shown anywhere on the homepage, yet it
is a published claim in its own right: it is the feed search engines and map apps
ingest. So it is read as-is (dated entries, attributed to holidays by date in
``webwatch.holiday_hours``) and judged independently against ``facts.yaml``; the
``/visit`` page's rows are its visible counterpart, checked by that source. Per
schema.org, ``opens == closes == "00:00"`` means closed (not open all day).
Malformed entries are ``unrecognized``, never guessed.
"""

from __future__ import annotations

import datetime as dt
import re
from typing import Any

from bs4 import BeautifulSoup

from webwatch import normalize
from webwatch.checks.registry import Check
from webwatch.events import extract_events
from webwatch.extract import structured
from webwatch.sources.base import HolidayListing, ListedHours, Observation, Observed, Source

# JSON-LD address keys -> our flat field names.
_ADDRESS_FIELDS = {
    "address.street": "streetAddress",
    "address.city": "addressLocality",
    "address.region": "addressRegion",
    "address.postal_code": "postalCode",
}


def _loose(value: str) -> str:
    """Alphanumeric-only, lowercased — for whitespace/punctuation-insensitive containment."""
    return re.sub(r"[^a-z0-9]", "", value.lower())


def _museum_node(html: str) -> dict[str, Any] | None:
    """The JSON-LD ``Museum`` node if present, else any business node, else None."""
    museums = structured.find_by_type(html, "Museum")
    if museums:
        return museums[0]
    return structured.extract_local_business(html)


#: A special-hours entry spanning longer than this isn't a holiday closure we model.
_MAX_SPECIAL_SPAN = dt.timedelta(days=31)
_CLOCK = re.compile(r"^(\d{1,2}:\d{2})(?::\d{2})?$")


def _clock(value: object) -> str | None:
    """``"HH:MM"`` from a schema.org time (seconds dropped), or None if not a time."""
    match = _CLOCK.match(value.strip()) if isinstance(value, str) else None
    return match.group(1) if match else None


def _special_hours(entry: dict[str, Any]) -> Observed[str]:
    opens, closes = _clock(entry.get("opens")), _clock(entry.get("closes"))
    if opens is None or closes is None:
        return Observed.unparseable(
            f"unreadable opens/closes: {entry.get('opens')!r} / {entry.get('closes')!r}"
        )
    if opens == closes == "00:00":
        return Observed.found("closed")  # schema.org's encoding of "closed all day"
    return Observed.found(f"{opens} - {closes}")


def _schema_date(value: object) -> dt.date:
    """A schema.org Date or DateTime as its date; raises ``ValueError`` otherwise."""
    if not isinstance(value, str):
        raise ValueError(f"not a date: {value!r}")
    return dt.datetime.fromisoformat(value).date()


def _special_entry(entry: object) -> ListedHours | None:
    """One dated entry, or None if it can't be attributed to any date."""
    if not isinstance(entry, dict):
        return None
    try:
        start = _schema_date(entry.get("validFrom"))
        end = _schema_date(entry.get("validThrough") or entry.get("validFrom"))
    except ValueError:
        return None
    if end < start or end - start > _MAX_SPECIAL_SPAN:
        return None
    label = str(start) if start == end else f"{start}..{end}"
    return ListedHours(label, _special_hours(entry), start=start, end=end)


def _holiday_listing(node: dict[str, Any] | None) -> Observed[HolidayListing]:
    if node is None:
        return Observed.missing("no JSON-LD Museum node on the page")
    raw = node.get("specialOpeningHoursSpecification")
    if raw is None:
        return Observed.found(HolidayListing())  # none posted (off-season)
    entries = raw if isinstance(raw, list) else [raw]
    items: list[ListedHours] = []
    unrecognized: list[str] = []
    for entry in entries:
        item = _special_entry(entry)
        if item is None:
            unrecognized.append(repr(entry)[:80])
        else:
            items.append(item)
    return Observed.found(HolidayListing(tuple(items), tuple(unrecognized)))


class TheFlipMuseum(Source):
    name = "theflip_museum"
    label = "Website"
    url = "https://www.theflip.museum/"
    tracks = frozenset({"name", "email", *_ADDRESS_FIELDS})
    provides_events = True
    provides_holiday_hours = True
    holiday_hours_dated = True

    def observe(self, html: str) -> Observation:
        node = _museum_node(html)
        visible = _loose(BeautifulSoup(html, "lxml").get_text(" ", strip=True))
        address = (node or {}).get("address") or {}

        raw = {"name": (node or {}).get("name"), "email": (node or {}).get("email")}
        for field, jsonld_key in _ADDRESS_FIELDS.items():
            raw[field] = address.get(jsonld_key) if isinstance(address, dict) else None

        fields = {
            field: self._corroborate(field, value, node, visible) for field, value in raw.items()
        }
        parsed = extract_events(html)
        events: Observed[Any] = (
            Observed.found(parsed)
            if parsed is not None
            else Observed.missing("no upcoming events section found")
        )
        return Observation(self.site, fields, events=events, holiday_hours=_holiday_listing(node))

    @staticmethod
    def _corroborate(
        field: str, value: Any, node: dict[str, Any] | None, visible: str
    ) -> Observed[str]:
        """Trust a JSON-LD value only if it is also visible on the page."""
        if node is None:
            return Observed.missing("no JSON-LD Museum node on the page")
        if value is None or str(value).strip() == "":
            return Observed.missing(f"{field} absent from the JSON-LD node")
        if _loose(str(value)) not in visible:
            return Observed.missing(f"{field} is in JSON-LD but not visible on the page")
        return Observed.found(str(value))


SOURCE = TheFlipMuseum()

CHECKS = [
    Check("name", lambda f: f.organization.name, normalize.text),
    Check("email", lambda f: f.organization.email, normalize.text),
    Check("address.street", lambda f: f.organization.address.street, normalize.street),
    Check("address.city", lambda f: f.organization.address.city, normalize.text),
    Check("address.region", lambda f: f.organization.address.region, normalize.text),
    Check("address.postal_code", lambda f: f.organization.address.postal_code, normalize.text),
]
