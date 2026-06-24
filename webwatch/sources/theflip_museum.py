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
"""

from __future__ import annotations

import re
from typing import Any

from bs4 import BeautifulSoup

from webwatch import normalize
from webwatch.checks.registry import Check
from webwatch.events import extract_events
from webwatch.extract import structured
from webwatch.sources.base import Observation, Observed, Source

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


class TheFlipMuseum(Source):
    name = "theflip_museum"
    url = "https://www.theflip.museum/"
    tracks = frozenset({"name", "email", *_ADDRESS_FIELDS})
    provides_events = True

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
        return Observation(self.site, fields, events=events)

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
