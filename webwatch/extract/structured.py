"""Pull structured data (JSON-LD / schema.org) out of a page.

Structured data is *corroboration*, not a decision (see ``docs/Extraction.md``):
it is often plugin-/SEO-managed and left stale. These helpers exist so a source
can compare the visible value against the structured one. A page usually carries
several JSON-LD blocks (the business, breadcrumbs, a search widget); the
type-filtering helpers select the right entity so callers never inspect the wrong
block (agy Phase B review, Gap F).
"""

from __future__ import annotations

from typing import Any

import extruct

# schema.org @types we treat as "the organization/place" for a business listing.
_BUSINESS_TYPES = {
    "localbusiness",
    "organization",
    "museum",
    "touristattraction",
    "place",
    "civicstructure",
}


def extract_jsonld(html: str, *, base_url: str | None = None) -> list[dict[str, Any]]:
    """Return all JSON-LD objects on the page, with any ``@graph`` flattened."""
    data = extruct.extract(html, base_url=base_url, syntaxes=["json-ld"])
    blocks: list[dict[str, Any]] = []
    for obj in data.get("json-ld", []):
        if not isinstance(obj, dict):
            continue
        graph = obj.get("@graph")
        if isinstance(graph, list):
            blocks.extend(node for node in graph if isinstance(node, dict))
        else:
            blocks.append(obj)
    return blocks


def _types_of(node: dict[str, Any]) -> set[str]:
    raw = node.get("@type", [])
    values = raw if isinstance(raw, list) else [raw]
    return {str(v).lower() for v in values}


def find_by_type(html: str, type_name: str, *, base_url: str | None = None) -> list[dict[str, Any]]:
    """All JSON-LD nodes whose ``@type`` includes ``type_name`` (case-insensitive)."""
    wanted = type_name.lower()
    return [node for node in extract_jsonld(html, base_url=base_url) if wanted in _types_of(node)]


def extract_local_business(html: str, *, base_url: str | None = None) -> dict[str, Any] | None:
    """The first JSON-LD node that looks like the business/place, or ``None``.

    Matches `LocalBusiness` and common subtypes (e.g. `Museum`) so a museum's
    listing is found whether it is typed broadly or specifically.
    """
    for node in extract_jsonld(html, base_url=base_url):
        if _types_of(node) & _BUSINESS_TYPES:
            return node
    return None


def extract_events(html: str, *, base_url: str | None = None) -> list[dict[str, Any]]:
    """All JSON-LD `Event` nodes (and subtypes ending in ``event``)."""
    events = []
    for node in extract_jsonld(html, base_url=base_url):
        if any(t == "event" or t.endswith("event") for t in _types_of(node)):
            events.append(node)
    return events
