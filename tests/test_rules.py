"""Tests for the rules engine (recurring_event evaluation)."""

from __future__ import annotations

from pathlib import Path

from webwatch.events import Event, extract_events
from webwatch.facts import Rule, load_facts
from webwatch.result import CheckStatus
from webwatch.rules import evaluate
from webwatch.sources.base import Observed

FIXTURE = Path(__file__).parent / "fixtures" / "theflip_museum_visit_2026-06-23.html"
SITE = "test"


def _rule(*, enabled: bool = True, type: str = "recurring_event", **params: object) -> Rule:
    base: dict[str, object] = {
        "match": "repair",
        "weekday": "saturday",
        "start": "10:00",
        "end": "16:00",
    }
    base.update(params)
    return Rule(id="weekly-repair-day", type=type, enabled=enabled, params=base)


def _events(*events: Event) -> Observed[list[Event]]:
    return Observed.found(list(events))


def _repair(**overrides: object) -> Event:
    fields: dict[str, object] = {
        "title": "Saturday Repair Day",
        "weekday": "Saturday",
        "time": "10:00 AM",
        "recurring": True,
    }
    fields.update(overrides)
    return Event(**fields)  # type: ignore[arg-type]


def test_golden_fixture_flags_weekday_and_time() -> None:
    """The committed page lists the repair day on Friday at a placeholder time."""
    events = extract_events(FIXTURE.read_text(encoding="utf-8"))
    rule = load_facts("facts.yaml").rules[0]
    result = evaluate(rule, Observed.found(events), site=SITE)
    assert result.status is CheckStatus.MISMATCH
    assert "Friday" in result.summary
    assert "3:22 PM" in result.summary


def test_correct_event_is_ok() -> None:
    result = evaluate(_rule(), _events(_repair()), site=SITE)
    assert result.status is CheckStatus.OK


def test_expected_event_absent_is_mismatch() -> None:
    other = Event(title="Open House Night", weekday="Friday", time="7 PM")
    result = evaluate(_rule(), _events(other), site=SITE)
    assert result.status is CheckStatus.MISMATCH
    assert "not found" in result.summary


def test_unreadable_events_is_structure_changed() -> None:
    result = evaluate(_rule(), Observed.missing("no events section"), site=SITE)
    assert result.status is CheckStatus.STRUCTURE_CHANGED


def test_disabled_rule_is_skipped() -> None:
    result = evaluate(_rule(enabled=False), _events(_repair()), site=SITE)
    assert result.status is CheckStatus.SKIPPED


def test_rule_without_match_keyword_is_skipped() -> None:
    result = evaluate(_rule(match=""), _events(_repair()), site=SITE)
    assert result.status is CheckStatus.SKIPPED


def test_unparseable_event_time_is_parse_error() -> None:
    result = evaluate(_rule(), _events(_repair(time="whenever")), site=SITE)
    assert result.status is CheckStatus.PARSE_ERROR


def test_matched_event_missing_weekday_is_structure_changed() -> None:
    result = evaluate(_rule(), _events(_repair(weekday="")), site=SITE)
    assert result.status is CheckStatus.STRUCTURE_CHANGED


def test_prefers_recurring_match() -> None:
    one_off = Event(title="Repair Day Special", weekday="Saturday", time="9 AM", recurring=False)
    recurring = _repair(title="Saturday Repair Day")
    # The recurring event matches facts -> OK even though a one-off also matches.
    result = evaluate(_rule(), _events(one_off, recurring), site=SITE)
    assert result.status is CheckStatus.OK
