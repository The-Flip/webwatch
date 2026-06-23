"""Tests for event extraction from the Upcoming Events section."""

from __future__ import annotations

from pathlib import Path

from webwatch.events import extract_events

FIXTURE = Path(__file__).parent / "fixtures" / "theflip_museum_visit_2026-06-23.html"


def test_extracts_events_from_fixture() -> None:
    events = extract_events(FIXTURE.read_text(encoding="utf-8"))
    assert events is not None
    titles = [e.title for e in events]
    assert "Saturday Repair Day" in titles
    repair = next(e for e in events if "Repair" in e.title)
    assert repair.weekday == "Friday"  # the site lists it on Friday (the real discrepancy)
    assert repair.time == "3:22 PM"
    assert repair.recurring is True
    assert (repair.month, repair.day) == ("Jun", "26")


def test_non_recurring_event_has_no_tag() -> None:
    events = extract_events(FIXTURE.read_text(encoding="utf-8"))
    assert events is not None
    tour = next(e for e in events if "Tour" in e.title)
    assert tour.recurring is False


def test_missing_section_returns_none() -> None:
    assert extract_events("<html><body><p>No events.</p></body></html>") is None


def test_event_with_partial_meta_does_not_crash() -> None:
    html = (
        "<html><body><section><div><h2>Upcoming Events</h2></div>"
        '<div class="card"><div><span>Jul</span><span>4</span></div>'
        "<h4>Mystery Event</h4><p>Saturday</p></div></section></body></html>"
    )
    events = extract_events(html)
    assert events is not None
    (event,) = events
    assert event.title == "Mystery Event"
    assert event.weekday == "Saturday"
    assert event.time == ""  # no time shown -> empty, not a crash
