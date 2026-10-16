"""Source for The Flip's Square donation checkout link.

The donate page (``theflip_museum_donate``) links here. This source checks that the
link is still live, i.e. that a donor who clicks through can actually pay.

The checkout page is a JS shell: only its ``<title>`` is server-rendered. Square
embeds its own state as ``window.bootstrap = {...}``, and that payload is the
observation, the same as an API response (so there's no visible/structured split and
no ``METADATA_DRIFT``). It's an undocumented internal format, so it's parsed
defensively, and an unexpected shape is "couldn't read", never "healthy". Three flags
decide the status:

- ``checkoutLink.is_deleted``: ``True`` -> ``"deleted"``
- ``checkoutLink.checkout_link_data.enabled``: ``False`` -> ``"disabled"``
- ``storeIsAcceptingPayments``: ``False`` -> ``"not accepting payments"``

A flag that's present and unhealthy is the answer, even if the others are absent.
Otherwise a non-bool flag is ``unparseable`` (``PARSE_ERROR``), an absent one is
``missing`` (``STRUCTURE_CHANGED``), and only all three healthy is ``"active"``.

Identity: the payload's ``merchantId`` and ``checkoutLinkId`` must equal the IDs in
:attr:`SquareDonation.url`. Anything else (say a redirect to another checkout or to a
landing page) is ``missing``, never a verdict about someone else's link.

A deleted link is an HTTP 404, and that 404 *is* the finding we're watching for, so
this source accepts 404/410 (see ``Source.accept_statuses``) and reports
``"not found (HTTP 404)"`` -> ``MISMATCH``, rather than a misleading
``FETCH_ERROR``. Only when the body is Square's own "couldn't find that page" page,
though: a bare 404 from a CDN or routing glitch isn't proof the link is gone, so
it's ``missing`` -> ``STRUCTURE_CHANGED``. Challenges are still ``BLOCKED``, and
5xx/network errors are still ``FETCH_ERROR``.
"""

from __future__ import annotations

import json
import re
from typing import Any, NamedTuple
from urllib.parse import urlsplit

from bs4 import BeautifulSoup

from webwatch import normalize
from webwatch.checks.registry import Check
from webwatch.facts import Facts, is_blank
from webwatch.fetch import FetchResult
from webwatch.sources.base import Observation, Observed, Source

ACTIVE = "active"
_FIELD = "link_status"
#: Marks a flag the payload doesn't carry (distinct from a present ``None``).
_ABSENT: Any = object()
#: Square's not-found page says "We couldn't find that page." (compared via _loose).
_SQUARE_NOT_FOUND = "couldntfindthatpage"
_ASSIGNMENT = re.compile(r"window\.bootstrap\s*=\s*")
_CHECKOUT_PATH = re.compile(
    r"^/merchant/(?P<merchant>[A-Za-z0-9]+)/checkout/(?P<link>[A-Za-z0-9]+)/?$"
)
_CHECKOUT_HOST = "checkout.square.site"


def checkout_ids(url: str) -> tuple[str, str]:
    """The (merchant id, checkout link id) in a canonical Square checkout URL.

    Only ``https://checkout.square.site/merchant/<merchant>/checkout/<link>`` is
    supported (not ``square.link`` short links), since the identity guard needs both
    IDs. Anything else raises ``ValueError``.
    """
    parts = urlsplit(url)
    match = _CHECKOUT_PATH.match(parts.path)
    if parts.hostname != _CHECKOUT_HOST or match is None:
        raise ValueError(f"not a canonical Square checkout URL: {url!r}")
    return match["merchant"], match["link"]


def _bootstrap(html: str) -> dict[str, Any] | None:
    """The ``window.bootstrap`` payload, or None if it's absent or not a JSON object."""
    match = _ASSIGNMENT.search(html)
    if match is None:
        return None
    try:
        payload, _end = json.JSONDecoder().raw_decode(html, match.end())
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def _as_mapping(value: Any) -> dict[str, Any]:
    """``value`` if it's a JSON object, else empty (so a ``null`` level reads as absent)."""
    return value if isinstance(value, dict) else {}


def _loose(value: str) -> str:
    """Alphanumeric-only, lowercased: apostrophe- and whitespace-insensitive containment."""
    return re.sub(r"[^a-z0-9]", "", value.lower())


class _Flag(NamedTuple):
    """One status flag in the payload, and the value that means the link is unusable."""

    status: str  # what to report when the flag is unhealthy
    value: Any  # as found, or _ABSENT
    unhealthy: bool

    @property
    def is_absent(self) -> bool:
        return self.value is _ABSENT

    @property
    def is_malformed(self) -> bool:
        return not self.is_absent and not isinstance(self.value, bool)


def _flags(payload: dict[str, Any]) -> list[_Flag]:
    """The payload's status flags, in precedence order."""
    link = _as_mapping(payload.get("checkoutLink"))
    link_data = _as_mapping(link.get("checkout_link_data"))
    return [
        _Flag("deleted", link.get("is_deleted", _ABSENT), unhealthy=True),
        _Flag("disabled", link_data.get("enabled", _ABSENT), unhealthy=False),
        _Flag(
            "not accepting payments",
            payload.get("storeIsAcceptingPayments", _ABSENT),
            unhealthy=False,
        ),
    ]


def _link_status(payload: dict[str, Any]) -> Observed[str]:
    """The checkout link's status from its bootstrap payload (see the module docstring)."""
    flags = _flags(payload)
    for flag in flags:
        if flag.value is flag.unhealthy:
            return Observed.found(flag.status)
    if malformed := [flag.status for flag in flags if flag.is_malformed]:
        return Observed.unparseable(f"non-boolean checkout flag(s) for: {', '.join(malformed)}")
    if absent := [flag.status for flag in flags if flag.is_absent]:
        return Observed.missing(f"checkout flag(s) absent for: {', '.join(absent)}")
    return Observed.found(ACTIVE)


class SquareDonation(Source):
    name = "square_donation"
    label = "Square donation link"
    url = "https://checkout.square.site/merchant/ML3SPVMTSCZBA/checkout/C3TD5MW7HG3FIIATNS4GALNL"
    tracks = frozenset({_FIELD})
    accept_statuses = frozenset({404, 410})

    def __init__(self) -> None:
        # Fails at import on a non-canonical URL, rather than as a perpetual
        # STRUCTURE_CHANGED at run time.
        self._merchant_id, self._link_id = checkout_ids(self.url)

    def observe_not_found(self, result: FetchResult) -> Observation:
        visible = _loose(BeautifulSoup(result.text, "lxml").get_text(" ", strip=True))
        if _SQUARE_NOT_FOUND in visible:
            status: Observed[str] = Observed.found(f"not found (HTTP {result.status_code})")
        else:
            status = Observed.missing(
                f"HTTP {result.status_code} without Square's not-found page; "
                "can't tell whether the link was deleted"
            )
        return Observation(self.site, {_FIELD: status})

    def observe(self, html: str) -> Observation:
        return Observation(self.site, {_FIELD: self._status(html)})

    def _status(self, html: str) -> Observed[str]:
        payload = _bootstrap(html)
        if payload is None:
            return Observed.missing("no readable window.bootstrap payload on the checkout page")
        ids = (payload.get("merchantId"), payload.get("checkoutLinkId"))
        if ids != (self._merchant_id, self._link_id):
            return Observed.missing(f"page is for checkout {ids}, not the one monitored")
        return _link_status(payload)


def _expected_status(facts: Facts) -> str:
    """``"active"`` while a donation link is configured; blank (-> ``SKIPPED``) otherwise."""
    return "" if is_blank(facts.organization.donation_url) else ACTIVE


SOURCE = SquareDonation()

CHECKS = [Check(_FIELD, _expected_status, normalize.text)]
