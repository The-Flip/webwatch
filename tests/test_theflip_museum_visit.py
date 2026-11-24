"""Tests for the /visit hours source: day-range parsing and the mutation matrix.

Hours are read from the visible card, so the negative cases mutate that card. The
section-divider handling gets direct coverage too (``expand_days`` is tested with
the other normalizers in ``test_normalize.py``).
"""

from __future__ import annotations

from pathlib import Path

from bs4 import BeautifulSoup, Tag

from webwatch.facts import load_facts
from webwatch.result import CheckStatus
from webwatch.sources.base import NotRead
from webwatch.sources.theflip_museum_visit import CHECKS, SOURCE

FIXTURE = Path(__file__).parent / "fixtures" / "theflip_museum_visit_2026-06-24.html"
FACTS = load_facts("facts.yaml")


def _card(rows: list[tuple[str, str]]) -> str:
    """A minimal Hours card; rows are (day-label, time-value), with divider noise."""
    inner = "".join(
        f'<div class="row"><span>{label}</span><span>{value}</span></div>'
        '<div class="section-divider"></div>'
        for label, value in rows
    )
    return f'<html><body><div class="card"><h3>Hours</h3><div class="list">{inner}</div></div></body></html>'


def _status(field: str, html: str) -> CheckStatus:
    observation = SOURCE.observe(html)
    check = next(c for c in CHECKS if c.field == field)
    return check.run(observation, FACTS).status


# --- against the real fixture -------------------------------------------------


def test_all_hours_match_facts_against_fixture() -> None:
    observation = SOURCE.observe(FIXTURE.read_text(encoding="utf-8"))
    statuses = {check.field: check.run(observation, FACTS).status for check in CHECKS}
    assert set(statuses.values()) == {CheckStatus.OK}, statuses


# --- mutation matrix ----------------------------------------------------------


def test_missing_hours_card_is_structure_changed() -> None:
    html = "<html><body><p>No hours here.</p></body></html>"
    assert _status("hours.monday", html) is CheckStatus.STRUCTURE_CHANGED


def test_section_divider_rows_do_not_crash() -> None:
    # Card includes section-divider siblings; parsing must still yield the day.
    assert _status("hours.monday", _card([("Monday - Saturday", "10a - 8p")])) is CheckStatus.OK


def test_changed_time_is_mismatch() -> None:
    assert _status("hours.monday", _card([("Monday", "9a - 5p")])) is CheckStatus.MISMATCH


def test_unparseable_time_is_parse_error() -> None:
    assert _status("hours.monday", _card([("Monday", "ten-ish")])) is CheckStatus.PARSE_ERROR


def test_closed_when_facts_expect_open_is_mismatch() -> None:
    assert _status("hours.monday", _card([("Monday", "Closed")])) is CheckStatus.MISMATCH


def test_day_omitted_from_card_is_structure_changed() -> None:
    html = _card([("Monday", "10a - 8p")])  # only Monday present
    assert _status("hours.monday", html) is CheckStatus.OK
    assert _status("hours.sunday", html) is CheckStatus.STRUCTURE_CHANGED


# --- the Holiday Hours section: negative cases mutate the 2026-11-24 golden page ---------

HOLIDAY_FIXTURE = Path(__file__).parent / "fixtures" / "theflip_museum_visit_2026-11-24.html"


def _holiday_soup() -> BeautifulSoup:
    """A fresh parse of the golden page, for in-memory mutation."""
    return BeautifulSoup(HOLIDAY_FIXTURE.read_text(encoding="utf-8"), "lxml")


def _heading(soup: BeautifulSoup) -> Tag:
    heading = soup.find("h4", string="Holiday Hours")
    assert isinstance(heading, Tag)
    return heading


def _section(soup: BeautifulSoup) -> tuple[Tag, Tag]:
    """The "Holiday Hours" heading and the list of rows under it."""
    heading = _heading(soup)
    rows = heading.find_next_sibling("div")
    assert isinstance(rows, Tag)
    return heading, rows


def _row(soup: BeautifulSoup, label: str) -> Tag:
    span = soup.find("span", string=label)
    assert span is not None and isinstance(span.parent, Tag)
    return span.parent


def _relabel(soup: BeautifulSoup, label: str, new: str) -> None:
    span = soup.find("span", string=label)
    assert span is not None
    span.string = new


def _body(soup: BeautifulSoup) -> Tag:
    assert soup.body is not None
    return soup.body


def _listing(html: str | BeautifulSoup):
    return SOURCE.observe(str(html)).holiday_hours


def _off_season(soup: BeautifulSoup) -> BeautifulSoup:
    """The golden page with its holiday section removed, as it is off-season."""
    for element in _section(soup):
        element.decompose()
    return soup


def test_regular_hours_ok_against_holiday_fixture() -> None:
    observation = SOURCE.observe(HOLIDAY_FIXTURE.read_text(encoding="utf-8"))
    statuses = {check.field: check.run(observation, FACTS).status for check in CHECKS}
    assert set(statuses.values()) == {CheckStatus.OK}, statuses


def test_rows_under_the_holiday_heading_never_become_regular_hours() -> None:
    # A holiday row whose label reads like a weekday must not overwrite Monday.
    soup = _holiday_soup()
    _relabel(soup, "Christmas Day", "Monday")
    assert _status("hours.monday", str(soup)) is CheckStatus.OK


def test_holiday_listing_from_fixture() -> None:
    listing = _listing(HOLIDAY_FIXTURE.read_text(encoding="utf-8"))
    assert listing.is_found
    assert listing.value is not None
    assert [(i.holiday, i.hours.value) for i in listing.value.items] == [
        ("thanksgiving", "Closed"),
        ("christmas_eve", "10a - 3p"),
        ("christmas", "Closed"),
        ("new_years_eve", "10a - 3p"),
        ("new_years_day", "Closed"),
    ]
    assert listing.value.unrecognized == ()


def test_unrecognized_holiday_label_is_kept_not_guessed() -> None:
    soup = _holiday_soup()
    _relabel(soup, "Christmas Eve", "Xmas Eve")
    listing = _listing(soup)
    assert listing.value is not None
    assert "christmas_eve" not in {i.holiday for i in listing.value.items}
    assert listing.value.unrecognized == ("Xmas Eve",)


def test_no_holiday_section_is_an_empty_listing() -> None:
    # Off-season the section is removed; that is a real reading, not a failure.
    listing = _listing(_off_season(_holiday_soup()))
    assert listing.is_found
    assert listing.value is not None
    assert listing.value.items == ()


def test_missing_hours_card_makes_holiday_listing_missing() -> None:
    soup = _holiday_soup()
    hours = soup.find("h3", string="Hours")
    assert hours is not None and hours.parent is not None
    hours.parent.decompose()
    assert not _listing(soup).is_found


def test_holiday_section_moved_outside_the_card_is_not_none_listed() -> None:
    # The section moved to its own card: we must not conclude "nothing posted".
    soup = _holiday_soup()
    moved = soup.new_tag("div")
    for element in _section(soup):
        moved.append(element.extract())
    _body(soup).append(moved)
    assert not _listing(soup).is_found


def test_holiday_row_outside_the_card_without_a_heading_is_not_none_listed() -> None:
    soup = _holiday_soup()
    heading, rows = _section(soup)
    row = _row(soup, "Christmas Day").extract()
    heading.decompose()
    rows.decompose()
    _body(soup).append(row)
    assert not _listing(soup).is_found


def test_one_row_moved_outside_the_card_is_not_read_as_absent() -> None:
    # The heading and the other rows remain; Thanksgiving alone moved.
    soup = _holiday_soup()
    _body(soup).append(_row(soup, "Thanksgiving").extract())
    assert not _listing(soup).is_found


def test_holiday_rows_left_in_the_card_without_their_heading_are_not_none_listed() -> None:
    soup = _holiday_soup()
    _heading(soup).decompose()
    assert not _listing(soup).is_found


def test_holiday_heading_with_no_readable_rows_is_not_none_listed() -> None:
    # The heading is there but the row markup changed: we can't read the section,
    # which is not the same as "nothing posted".
    soup = _holiday_soup()
    for span in _section(soup)[1].find_all("span"):
        span.name = "p"
    assert not _listing(soup).is_found


def test_one_unreadable_row_is_unrecognized_not_absent() -> None:
    soup = _holiday_soup()
    for span in _row(soup, "Thanksgiving").find_all("span"):
        span.name = "p"
    listing = _listing(soup)
    assert listing.value is not None
    assert "thanksgiving" not in {i.holiday for i in listing.value.items}
    assert listing.value.unrecognized == ("Thanksgiving",)


def test_blank_holiday_hours_value_is_unparseable_not_found() -> None:
    soup = _holiday_soup()
    _row(soup, "Thanksgiving").find_all("span")[1].string = " "
    listing = _listing(soup)
    assert listing.value is not None
    assert listing.value.items[0].hours.reason is NotRead.UNPARSEABLE


def test_unrelated_holiday_heading_elsewhere_is_not_a_moved_section() -> None:
    # Off-season, an events heading like "Holiday Pinball Party" is not holiday hours.
    soup = _off_season(_holiday_soup())
    heading = soup.new_tag("h4")
    heading.string = "Holiday Pinball Party"
    _body(soup).append(heading)
    listing = _listing(soup)
    assert listing.is_found
    assert listing.value is not None and listing.value.items == ()
