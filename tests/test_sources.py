"""Tests for the Source base: fetch-once, blocked handling, and the mutation matrix.

A FakeSource over tiny inline HTML stands in for a real site. The mutation tests
prove the whole source -> Observation -> check path turns a broken page into the
right status (never a false MISMATCH). Each test parses fresh HTML so in-place
mutations don't bleed (agy test-hygiene note).
"""

from __future__ import annotations

import httpx
import pytest
from bs4 import BeautifulSoup

from webwatch.checks.base import check_field
from webwatch.extract import structured
from webwatch.extract.anchors import Found, by_itemprop, by_microformat
from webwatch.fetch import FetchError
from webwatch.result import CheckStatus
from webwatch.sources.base import Observation, Observed, Source

GOLDEN = """
<html><head>
<script type="application/ld+json">
{"@context":"https://schema.org","@type":"Museum",
 "name":"The Flip","telephone":"+1 555 123 4567"}
</script>
</head><body>
<h1 class="p-name">The Flip</h1>
<span itemprop="telephone">(555) 123-4567</span>
</body></html>
"""


def _to_observed(anchor: object) -> Observed[str]:
    if isinstance(anchor, Found):
        return Observed.found(anchor.value)
    return Observed.missing(getattr(anchor, "reason", "not found"))


class FakeSource(Source):
    name = "fake_museum"
    url = "https://fake.test/"
    tracks = frozenset({"name", "phone"})

    def observe(self, html: str) -> Observation:
        soup = BeautifulSoup(html, "lxml")
        business = structured.extract_local_business(html) or {}
        return Observation(
            site=self.site,
            fields={
                "name": _to_observed(by_microformat(soup, "p-name")),
                "phone": _to_observed(by_itemprop(soup, "telephone")),
            },
            structured={"name": business.get("name")},
        )


def test_observe_reads_visible_and_structured() -> None:
    obs = FakeSource().observe(GOLDEN)
    assert obs.get("name").is_found
    assert obs.get("name").value == "The Flip"
    assert obs.structured["name"] == "The Flip"


def test_untracked_field_is_not_supported() -> None:
    obs = FakeSource().observe(GOLDEN)
    assert obs.get("address").reason is not None  # not tracked -> NOT_SUPPORTED


def test_fetch_success(serve_html) -> None:
    obs = FakeSource().fetch(transport=serve_html(GOLDEN))
    assert obs.get("name").value == "The Flip"


def test_fetch_blocked_marks_all_tracked_fields_blocked(serve_html) -> None:
    challenge = "<html><title>Just a moment...</title></html>"
    obs = FakeSource().fetch(transport=serve_html(challenge))
    assert (
        check_field("fake_museum", "name", obs.get("name"), "The Flip").status
        is CheckStatus.BLOCKED
    )


def test_fetch_error_propagates(make_transport, monkeypatch) -> None:
    monkeypatch.setattr("webwatch.config.HTTP_MAX_RETRIES", 0)  # fail fast, no real sleeping

    def boom(_request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("boom")

    with pytest.raises(FetchError):
        FakeSource().fetch(transport=make_transport(boom))


def test_mutation_removed_region_is_structure_changed() -> None:
    soup = BeautifulSoup(GOLDEN, "lxml")
    soup.select_one(".p-name").decompose()  # the page lost its name heading
    obs = FakeSource().observe(str(soup))
    result = check_field("fake_museum", "name", obs.get("name"), expected="The Flip")
    assert result.status is CheckStatus.STRUCTURE_CHANGED


def test_mutation_changed_value_is_mismatch() -> None:
    soup = BeautifulSoup(GOLDEN, "lxml")
    soup.select_one(".p-name").string = "The Flop"
    obs = FakeSource().observe(str(soup))
    result = check_field("fake_museum", "name", obs.get("name"), expected="The Flip")
    assert result.status is CheckStatus.MISMATCH
