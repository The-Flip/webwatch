"""Tests for the theflip.museum source against its committed golden fixture.

Proves the source reads the real page correctly and that breakage surfaces as a
checker condition, never a false MISMATCH. Negative cases are produced by mutating
the golden HTML in memory (fresh parse per test) or with small synthetic pages.
"""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

import pytest
from bs4 import BeautifulSoup

from webwatch.facts import load_facts
from webwatch.result import CheckStatus
from webwatch.sources.base import NotRead
from webwatch.sources.theflip_museum import CHECKS, SOURCE

FIXTURES = Path(__file__).parent / "fixtures"
FIXTURE = "theflip_museum_2026-06-24.html"
FACTS = load_facts("facts.yaml")


def golden() -> str:
    return (FIXTURES / FIXTURE).read_text(encoding="utf-8")


def _check(field: str, observation) -> CheckStatus:
    check = next(c for c in CHECKS if c.field == field)
    return check.run(observation, FACTS).status


def _synthetic(street: str, *, street_visible: bool) -> str:
    """A minimal Museum page; the street may or may not appear in the visible body."""
    body = street if street_visible else "no street shown here"
    return f"""
    <html><head><script type="application/ld+json">
    {{"@type":"Museum","name":"The Flip","email":"hello@theflip.museum",
      "address":{{"@type":"PostalAddress","streetAddress":"{street}",
      "addressLocality":"Chicago","addressRegion":"IL","postalCode":"60602"}}}}
    </script></head><body>{body} The Flip hello@theflip.museum Chicago IL 60602</body></html>
    """


def test_all_tracked_fields_match_facts() -> None:
    observation = SOURCE.observe(golden())
    statuses = {check.field: check.run(observation, FACTS).status for check in CHECKS}
    assert set(statuses.values()) == {CheckStatus.OK}, statuses


def test_phone_and_hours_are_not_tracked() -> None:
    """The homepage doesn't publish these, so they are NOT_SUPPORTED -> SKIPPED, not alarms."""
    assert "phone" not in SOURCE.tracks
    observation = SOURCE.observe(golden())
    assert observation.get("phone").reason is NotRead.NOT_SUPPORTED


def test_missing_jsonld_is_structure_changed() -> None:
    soup = BeautifulSoup(golden(), "lxml")
    for script in soup.select('script[type="application/ld+json"]'):
        script.decompose()
    observation = SOURCE.observe(str(soup))
    assert observation.get("address.street").reason is NotRead.MISSING
    assert _check("address.street", observation) is CheckStatus.STRUCTURE_CHANGED


def test_jsonld_value_not_visible_is_structure_changed() -> None:
    """JSON-LD present but its street isn't visible on the page -> we don't trust it."""
    observation = SOURCE.observe(_synthetic("999 Hidden Way", street_visible=False))
    assert observation.get("address.street").reason is NotRead.MISSING
    assert _check("address.street", observation) is CheckStatus.STRUCTURE_CHANGED
    # Other fields are still fine, proving the guard is per-field.
    assert _check("address.city", observation) is CheckStatus.OK


def test_changed_value_is_mismatch() -> None:
    observation = SOURCE.observe(_synthetic("999 Fake Boulevard", street_visible=True))
    assert observation.get("address.street").is_found
    assert _check("address.street", observation) is CheckStatus.MISMATCH


# --- holiday hours (JSON-LD specialOpeningHoursSpecification) ---------------------

HOLIDAY_FIXTURE = "theflip_museum_2026-11-24.html"


def holiday_golden() -> str:
    return (FIXTURES / HOLIDAY_FIXTURE).read_text(encoding="utf-8")


def with_special_hours(spec: object, *, drop: bool = False) -> str:
    """The holiday fixture with the Museum node's special hours replaced (or removed)."""
    soup = BeautifulSoup(holiday_golden(), "lxml")
    for script in soup.select('script[type="application/ld+json"]'):
        node = json.loads(script.get_text())
        if isinstance(node, dict) and node.get("@type") == "Museum":
            if drop:
                node.pop("specialOpeningHoursSpecification", None)
            else:
                node["specialOpeningHoursSpecification"] = spec
            script.string = json.dumps(node)
    return str(soup)


def _spec(start: str, opens: object = "00:00", closes: object = "00:00", end: str | None = None):
    return {
        "@type": "OpeningHoursSpecification",
        "validFrom": start,
        "validThrough": end or start,
        "opens": opens,
        "closes": closes,
    }


def test_holiday_listing_from_fixture() -> None:
    listing = SOURCE.observe(holiday_golden()).holiday_hours
    assert listing.value is not None
    assert [(i.start, i.end, i.hours.value) for i in listing.value.items] == [
        (dt.date(2026, 11, 26), dt.date(2026, 11, 26), "closed"),
        (dt.date(2026, 12, 24), dt.date(2026, 12, 24), "10:00 - 15:00"),
        (dt.date(2026, 12, 25), dt.date(2026, 12, 25), "closed"),
        (dt.date(2026, 12, 31), dt.date(2026, 12, 31), "10:00 - 15:00"),
        (dt.date(2027, 1, 1), dt.date(2027, 1, 1), "closed"),
    ]
    assert listing.value.unrecognized == ()


def test_midnight_to_midnight_is_closed_not_open_all_day() -> None:
    listing = SOURCE.observe(with_special_hours(_spec("2026-11-26"))).holiday_hours
    assert listing.value is not None
    assert listing.value.items[0].hours.value == "closed"


def test_seconds_are_trimmed() -> None:
    html = with_special_hours([_spec("2026-12-24", "10:00:00", "15:00:00")])
    listing = SOURCE.observe(html).holiday_hours
    assert listing.value is not None
    assert listing.value.items[0].hours.value == "10:00 - 15:00"


def test_single_entry_object_is_accepted() -> None:
    listing = SOURCE.observe(with_special_hours(_spec("2026-11-26"))).holiday_hours
    assert listing.value is not None
    assert len(listing.value.items) == 1


def test_no_special_hours_key_is_an_empty_listing() -> None:
    listing = SOURCE.observe(with_special_hours(None, drop=True)).holiday_hours
    assert listing.is_found
    assert listing.value is not None
    assert listing.value.items == ()


def test_no_museum_node_makes_holiday_listing_missing() -> None:
    soup = BeautifulSoup(holiday_golden(), "lxml")
    for script in soup.select('script[type="application/ld+json"]'):
        script.decompose()
    assert not SOURCE.observe(str(soup)).holiday_hours.is_found


@pytest.mark.parametrize(
    "entry",
    [
        _spec("next thursday"),
        _spec("2026-12-26", end="2026-12-24"),  # reversed range
        _spec("2026-11-01", end="2026-12-31"),  # implausibly long
        "closed on thanksgiving",
    ],
)
def test_malformed_entry_is_unrecognized_not_guessed(entry: object) -> None:
    listing = SOURCE.observe(with_special_hours([entry])).holiday_hours
    assert listing.value is not None
    assert listing.value.items == ()
    assert len(listing.value.unrecognized) == 1


def test_valid_date_with_unreadable_times_is_kept_as_unparseable() -> None:
    listing = SOURCE.observe(with_special_hours([_spec("2026-12-24", opens=None)])).holiday_hours
    assert listing.value is not None
    (item,) = listing.value.items
    assert item.start == dt.date(2026, 12, 24)
    assert item.hours.reason is NotRead.UNPARSEABLE


def test_datetime_valid_from_is_read_as_its_date() -> None:
    # schema.org allows DateTime for validFrom/validThrough.
    spec = _spec("2026-12-24T00:00:00", "10:00", "15:00", end="2026-12-24T23:59:59")
    listing = SOURCE.observe(with_special_hours([spec])).holiday_hours
    assert listing.value is not None
    (item,) = listing.value.items
    assert (item.start, item.end) == (dt.date(2026, 12, 24), dt.date(2026, 12, 24))
