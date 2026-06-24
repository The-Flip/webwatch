"""Tests for the /visit hours source: day-range parsing and the mutation matrix.

Hours are read from the visible card, so the negative cases mutate that card. The
day-range helper and the section-divider handling get direct coverage too.
"""

from __future__ import annotations

from pathlib import Path

from webwatch.facts import load_facts
from webwatch.result import CheckStatus
from webwatch.sources.theflip_museum_visit import CHECKS, SOURCE, expand_days

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


# --- day-range helper ---------------------------------------------------------


def test_expand_full_range() -> None:
    assert expand_days("Monday - Saturday") == [
        "monday",
        "tuesday",
        "wednesday",
        "thursday",
        "friday",
        "saturday",
    ]


def test_expand_single_day() -> None:
    assert expand_days("Sunday") == ["sunday"]


def test_expand_non_day_is_empty() -> None:
    assert expand_days("Private Tours") == []


def test_expand_wraps_around_week() -> None:
    assert expand_days("Saturday - Tuesday") == ["saturday", "sunday", "monday", "tuesday"]


def test_expand_abbreviations_and_to() -> None:
    assert expand_days("Mon - Fri") == ["monday", "tuesday", "wednesday", "thursday", "friday"]
    assert expand_days("Mon to Wed") == ["monday", "tuesday", "wednesday"]


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
