"""Tests for the /donate source: the golden fixture plus the mutation matrix.

The donate page's one tracked fact is where its donate button sends people. Every
negative case mutates the committed fixture in memory (the CTA link, or extra links
beside it) and asserts the honest status for it.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path

import httpx
from bs4 import BeautifulSoup, Tag

from webwatch.facts import Facts, load_facts
from webwatch.result import CheckStatus
from webwatch.sources.theflip_museum_donate import CHECKS, SOURCE

FIXTURE = (Path(__file__).parent / "fixtures" / "theflip_museum_donate_2026-10-15.html").read_text(
    encoding="utf-8"
)
FACTS = load_facts("facts.yaml")
OTHER_SQUARE_LINK = "https://checkout.square.site/merchant/ML3SPVMTSCZBA/checkout/ZZZZZZZZZZZZZZZZ"


def _status(html: str, facts: Facts = FACTS) -> CheckStatus:
    (check,) = CHECKS
    return check.run(SOURCE.observe(html), facts).status


def _soup() -> BeautifulSoup:
    return BeautifulSoup(FIXTURE, "lxml")


def _cta(soup: BeautifulSoup) -> Tag:
    """The fixture's "Donate Now" button (found by text, as a person would)."""
    links = [a for a in soup.find_all("a") if a.get_text(strip=True) == "Donate Now"]
    assert len(links) == 1, "fixture no longer has exactly one 'Donate Now' link"
    return links[0]


def _add_main_link(soup: BeautifulSoup, href: str, text: str) -> str:
    main = soup.find("main")
    assert isinstance(main, Tag)
    link = soup.new_tag("a", href=href)
    link.string = text
    main.append(link)
    return str(soup)


# --- against the real fixture -------------------------------------------------


def test_donation_url_matches_facts_against_fixture() -> None:
    assert _status(FIXTURE) is CheckStatus.OK


def test_internal_nav_donate_links_are_not_candidates() -> None:
    """Nav/footer "Donate" links point at /donate itself; only the off-site CTA counts."""
    observed = SOURCE.observe(FIXTURE).get("donation_url")
    assert observed.is_found
    assert "checkout.square.site" in str(observed.value)


# --- region missing -> STRUCTURE_CHANGED --------------------------------------


def test_cta_removed_is_structure_changed() -> None:
    soup = _soup()
    _cta(soup).decompose()
    assert _status(str(soup)) is CheckStatus.STRUCTURE_CHANGED


def test_cta_relabelled_is_structure_changed() -> None:
    soup = _soup()
    _cta(soup).string = "Support our museum"
    assert _status(str(soup)) is CheckStatus.STRUCTURE_CHANGED


def test_cta_made_relative_is_structure_changed() -> None:
    soup = _soup()
    _cta(soup)["href"] = "/give"
    assert _status(str(soup)) is CheckStatus.STRUCTURE_CHANGED


def test_cta_with_hostless_href_is_structure_changed() -> None:
    soup = _soup()
    _cta(soup)["href"] = "https:///checkout"
    assert _status(str(soup)) is CheckStatus.STRUCTURE_CHANGED


def test_unparseable_href_is_not_a_candidate_and_does_not_crash() -> None:
    soup = _soup()
    _add_main_link(soup, "http://[broken", "Contact us")  # unrelated, malformed
    _cta(soup)["href"] = "https://[broken/checkout"
    assert _status(str(soup)) is CheckStatus.STRUCTURE_CHANGED


def test_disagreeing_donate_ctas_are_structure_changed() -> None:
    html = _add_main_link(_soup(), OTHER_SQUARE_LINK, "Donate")
    assert _status(html) is CheckStatus.STRUCTURE_CHANGED


def test_cta_outside_main_is_ignored() -> None:
    """A donate link only in the footer isn't the page's call to action."""
    soup = _soup()
    cta = _cta(soup)
    footer = soup.find("footer")
    assert isinstance(footer, Tag)
    footer.append(cta.extract())
    assert _status(str(soup)) is CheckStatus.STRUCTURE_CHANGED


# --- read, differs -> MISMATCH ------------------------------------------------


def test_cta_pointing_at_another_square_link_is_mismatch() -> None:
    soup = _soup()
    _cta(soup)["href"] = OTHER_SQUARE_LINK
    assert _status(str(soup)) is CheckStatus.MISMATCH


def test_cta_pointing_at_another_site_is_mismatch() -> None:
    soup = _soup()
    _cta(soup)["href"] = "https://www.paypal.com/donate/?hosted_button_id=X"
    assert _status(str(soup)) is CheckStatus.MISMATCH


def test_square_ids_are_case_sensitive() -> None:
    soup = _soup()
    cta = _cta(soup)
    cta["href"] = str(cta["href"]).lower()
    assert _status(str(soup)) is CheckStatus.MISMATCH


# --- tolerated variations -> OK -----------------------------------------------


def test_second_cta_to_the_same_link_is_ok() -> None:
    href = str(_cta(_soup())["href"]) + "/"  # cosmetic trailing slash
    assert _status(_add_main_link(_soup(), href, "Make a Donation")) is CheckStatus.OK


def test_in_kind_and_alternative_payment_links_do_not_disturb() -> None:
    soup = _soup()
    _add_main_link(soup, "https://forms.gle/abc", "Donate a machine")
    html = _add_main_link(soup, "https://www.paypal.com/donate", "Donate via PayPal")
    assert _status(html) is CheckStatus.OK


def test_image_only_cta_is_recognized() -> None:
    soup = _soup()
    cta = _cta(soup)
    cta.clear()
    cta.append(soup.new_tag("img", src="/donate.png", alt="Donate Now"))
    assert _status(str(soup)) is CheckStatus.OK


def test_aria_labelled_cta_is_recognized() -> None:
    soup = _soup()
    cta = _cta(soup)
    cta.string = "→"
    cta["aria-label"] = "Donate"
    assert _status(str(soup)) is CheckStatus.OK


# --- blocked / skipped --------------------------------------------------------


def test_challenge_page_is_blocked() -> None:
    challenge = "<html><title>Just a moment...</title></html>"
    transport = httpx.MockTransport(lambda _r: httpx.Response(200, html=challenge))
    (check,) = CHECKS
    observation = SOURCE.fetch(transport=transport)
    assert check.run(observation, FACTS).status is CheckStatus.BLOCKED


def test_blank_donation_url_fact_is_skipped() -> None:
    facts = dataclasses.replace(
        FACTS, organization=dataclasses.replace(FACTS.organization, donation_url="")
    )
    assert _status(FIXTURE, facts) is CheckStatus.SKIPPED
