"""Tests for event extraction from the Upcoming Events section."""

from __future__ import annotations

from pathlib import Path

from webwatch.events import extract_events

FIXTURE = Path(__file__).parent / "fixtures" / "theflip_museum_visit_2026-06-24.html"


def test_extracts_events_from_fixture() -> None:
    events = extract_events(FIXTURE.read_text(encoding="utf-8"))
    assert events is not None
    repair = next(e for e in events if "Repair" in e.title)
    assert repair.title == "Saturday Repair Day"
    assert repair.weekday == "Saturday"
    assert "10:00 AM" in repair.time and "5:00 PM" in repair.time
    assert repair.recurring is True
    assert (repair.month, repair.day) == ("Jun", "27")


def test_non_recurring_event_has_no_tag() -> None:
    html = (
        "<html><body><section><div><h2>Upcoming Events</h2></div>"
        '<div class="card"><div><span>Jul</span><span>4</span></div>'
        "<h4>One-Off Party</h4><p>Friday</p></div></section></body></html>"
    )
    events = extract_events(html)
    assert events is not None
    assert events[0].recurring is False


def test_missing_section_returns_none() -> None:
    assert extract_events("<html><body><p>No events.</p></body></html>") is None


def test_empty_section_with_message_returns_empty_list() -> None:
    """Heading + an explicit 'no events' message -> [] (empty schedule), not None (agy review)."""
    html = (
        "<html><body><section><div><h2>Upcoming Events</h2></div>"
        "<p>No upcoming events.</p></section></body></html>"
    )
    assert extract_events(html) == []


def test_no_cards_and_no_empty_message_fails_safe_to_none() -> None:
    """Heading present but neither cards nor an empty-state message -> None (likely broken markup)."""
    html = (
        "<html><body><section><div><h2>Upcoming Events</h2></div>"
        "<div><article>Restructured content with no parseable cards</article></div>"
        "</section></body></html>"
    )
    assert extract_events(html) is None


def test_location_is_not_mistaken_for_time() -> None:
    """A card with a weekday and location but no time -> time stays empty (agy review)."""
    meta = "Friday " + chr(0xB7) + " 108 N. State St., Suite 015"
    html = (
        "<html><body><section><div><h2>Upcoming Events</h2></div>"
        '<div class="card"><div><span>Jul</span><span>4</span></div>'
        f"<h4>Open House</h4><p>{meta}</p></div></section></body></html>"
    )
    events = extract_events(html)
    assert events is not None
    (event,) = events
    assert event.weekday == "Friday"
    assert event.time == ""


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
