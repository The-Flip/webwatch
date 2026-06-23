"""Tests for the theflip.museum source against its committed golden fixture.

Proves the source reads the real page correctly and that breakage surfaces as a
checker condition, never a false MISMATCH. Negative cases are produced by mutating
the golden HTML in memory (fresh parse per test) or with small synthetic pages.
"""

from __future__ import annotations

from pathlib import Path

from bs4 import BeautifulSoup

from webwatch.facts import load_facts
from webwatch.result import CheckStatus
from webwatch.sources.base import NotRead
from webwatch.sources.theflip_museum import CHECKS, SOURCE

FIXTURES = Path(__file__).parent / "fixtures"
FIXTURE = "theflip_museum_2026-06-23.html"
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
