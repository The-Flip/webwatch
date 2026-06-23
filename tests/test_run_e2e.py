"""End-to-end (hermetic): facts + a fake source + checks -> results -> report.

No network. Proves the pieces compose and that the run's exit code reflects the
worst outcome, including a programmatically-broken page.
"""

from __future__ import annotations

import pytest
from bs4 import BeautifulSoup

from webwatch import normalize
from webwatch.checks import registry
from webwatch.checks.registry import Check, checks_for
from webwatch.extract import structured
from webwatch.extract.anchors import Found, by_itemprop, by_microformat
from webwatch.facts import parse_facts
from webwatch.report import render_text
from webwatch.result import EXIT_CHECKER_PROBLEM, EXIT_OK, CheckStatus, exit_code
from webwatch.sources.base import Observation, Observed, Source

GOLDEN = """
<html><head>
<script type="application/ld+json">
{"@type":"Museum","name":"The Flip","telephone":"+1 555 123 4567"}
</script></head><body>
<h1 class="p-name">The Flip</h1>
<span itemprop="telephone">(555) 123-4567</span>
</body></html>
"""

FACTS = parse_facts({"organization": {"name": "The Flip", "phone": "+1 555 123 4567"}})


def _observed(anchor: object) -> Observed[str]:
    return (
        Observed.found(anchor.value) if isinstance(anchor, Found) else Observed.missing("not found")
    )


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
                "name": _observed(by_microformat(soup, "p-name")),
                "phone": _observed(by_itemprop(soup, "telephone")),
            },
            structured={"name": business.get("name")},
        )


@pytest.fixture
def registered_checks():
    registry.clear()
    registry.register(
        "fake_museum",
        [
            Check("name", lambda f: f.organization.name, normalize.text, structured_field="name"),
            Check("phone", lambda f: f.organization.phone, normalize.phone),
        ],
    )
    yield
    registry.clear()


def _run(html: str) -> list:
    obs = FakeSource().observe(html)
    return [check.run(obs, FACTS) for check in checks_for("fake_museum")]


def test_clean_page_all_ok(registered_checks) -> None:
    results = _run(GOLDEN)
    assert {r.status for r in results} == {CheckStatus.OK}
    assert exit_code(results) == EXIT_OK
    assert "2 checks" in render_text(results)


def test_broken_page_is_checker_problem_not_data(registered_checks) -> None:
    soup = BeautifulSoup(GOLDEN, "lxml")
    soup.select_one(".p-name").decompose()
    results = _run(str(soup))
    statuses = {r.name: r.status for r in results}
    assert statuses["name"] is CheckStatus.STRUCTURE_CHANGED  # broke, not a false mismatch
    assert statuses["phone"] is CheckStatus.OK
    assert exit_code(results) == EXIT_CHECKER_PROBLEM
