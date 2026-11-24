"""Tests for the /visit hours source: day-range parsing and the mutation matrix.

Hours are read from the visible card, so the negative cases mutate that card. The
section-divider handling gets direct coverage too (``expand_days`` is tested with
the other normalizers in ``test_normalize.py``).
"""

from __future__ import annotations

from pathlib import Path

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


# --- regular hours alongside the Holiday Hours section ---------------------------

HOLIDAY_FIXTURE = Path(__file__).parent / "fixtures" / "theflip_museum_visit_2026-11-24.html"


def _card_with_holidays(rows: list[tuple[str, str]], holiday_rows: list[tuple[str, str]]) -> str:
    """A card shaped like the live page: regular rows, an h4 heading, holiday rows."""

    def block(pairs: list[tuple[str, str]]) -> str:
        return "".join(
            f'<div class="row"><span>{label}</span><span>{value}</span></div>'
            '<div class="section-divider"></div>'
            for label, value in pairs
        )

    return (
        '<html><body><div class="card"><h3>Hours</h3>'
        f'<div class="list">{block(rows)}</div>'
        f'<h4>Holiday Hours</h4><div class="list">{block(holiday_rows)}</div>'
        "</div></body></html>"
    )


def test_regular_hours_ok_against_holiday_fixture() -> None:
    observation = SOURCE.observe(HOLIDAY_FIXTURE.read_text(encoding="utf-8"))
    statuses = {check.field: check.run(observation, FACTS).status for check in CHECKS}
    assert set(statuses.values()) == {CheckStatus.OK}, statuses


def test_rows_under_the_holiday_heading_never_become_regular_hours() -> None:
    # A holiday row whose label reads like a weekday must not overwrite Monday.
    html = _card_with_holidays(
        [("Monday - Saturday", "10a - 8p"), ("Sunday", "11a - 6p")],
        [("Monday", "Closed")],
    )
    assert _status("hours.monday", html) is CheckStatus.OK


# --- holiday listing extraction ---------------------------------------------------


def _listing(html: str):
    return SOURCE.observe(html).holiday_hours


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
    html = _card_with_holidays([("Sunday", "11a - 6p")], [("Xmas", "Closed")])
    listing = _listing(html)
    assert listing.value is not None
    assert listing.value.items == ()
    assert listing.value.unrecognized == ("Xmas",)


def test_no_holiday_section_is_an_empty_listing() -> None:
    # Off-season the section is removed; that is a real reading, not a failure.
    listing = _listing(_card([("Monday - Saturday", "10a - 8p")]))
    assert listing.is_found
    assert listing.value is not None
    assert listing.value.items == ()


def test_missing_hours_card_makes_holiday_listing_missing() -> None:
    listing = _listing("<html><body><p>No hours here.</p></body></html>")
    assert not listing.is_found


def test_holiday_rows_moved_outside_the_card_are_not_read_as_none_listed() -> None:
    # The section moved to its own card: we must not conclude "nothing posted".
    html = _card([("Monday - Saturday", "10a - 8p")]).replace(
        "</body>",
        "<div><h3>Holiday Hours</h3><div><span>Thanksgiving</span><span>Closed</span></div></div></body>",
    )
    assert not _listing(html).is_found


def test_holiday_row_outside_the_card_without_a_heading_is_not_none_listed() -> None:
    html = _card([("Monday - Saturday", "10a - 8p")]).replace(
        "</body>", "<div><span>Christmas Day</span><span>Closed</span></div></body>"
    )
    assert not _listing(html).is_found


def test_holiday_heading_with_no_readable_rows_is_not_none_listed() -> None:
    # The heading is there but the row markup changed: we can't read the section,
    # which is not the same as "nothing posted".
    html = HOLIDAY_FIXTURE.read_text(encoding="utf-8")
    start = html.index("Holiday Hours</h4>")
    end = html.index("</div></div>", html.index("New Year&#x27;s Day", start))
    mutated = html[:start] + html[start:end].replace("<span", "<p").replace("</span>", "</p>")
    assert not _listing(mutated + html[end:]).is_found


def test_blank_holiday_hours_value_is_unparseable_not_found() -> None:
    html = _card_with_holidays([("Sunday", "11a - 6p")], [("Thanksgiving", " ")])
    listing = _listing(html)
    assert listing.value is not None
    hours = listing.value.items[0].hours
    assert hours.reason is NotRead.UNPARSEABLE


def test_unrelated_holiday_heading_elsewhere_is_not_a_moved_section() -> None:
    # Off-season, an events heading like "Holiday Pinball Party" is not holiday hours.
    html = _card([("Monday - Saturday", "10a - 8p")]).replace(
        "</body>", "<div><h4>Holiday Pinball Party</h4><p>Dec 12</p></div></body>"
    )
    listing = _listing(html)
    assert listing.is_found
    assert listing.value is not None and listing.value.items == ()
