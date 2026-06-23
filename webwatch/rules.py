"""Evaluate dynamic rules from facts.yaml against a source's observed events.

Currently one rule type: ``recurring_event`` (e.g. the weekly volunteer repair
day). The honest-status discipline carries over from field checks: if the events
list couldn't be read it's ``STRUCTURE_CHANGED`` (we can't judge), an expected
event that's genuinely absent is a ``MISMATCH``, a matched event whose weekday or
time disagrees is a ``MISMATCH``, and a matched event missing the weekday/time
text is ``STRUCTURE_CHANGED`` for that aspect — never a silent pass. See
``docs/Facts.md`` and ``docs/plans/phase-d-rules-engine.md``.
"""

from __future__ import annotations

from webwatch import normalize
from webwatch.events import Event
from webwatch.facts import Rule
from webwatch.result import CheckResult
from webwatch.sources.base import Observed


def _match_events(events: list[Event], keyword: str) -> list[Event]:
    """Events matching ``keyword`` — by title first, description only as fallback."""
    by_title = [e for e in events if keyword in e.title.lower()]
    if by_title:
        return by_title
    return [e for e in events if keyword in e.description.lower()]


def evaluate(rule: Rule, observed_events: Observed[list[Event]], *, site: str) -> CheckResult:
    """Evaluate one rule against a source's observed events, as a CheckResult."""
    name = rule.id
    if not rule.enabled:
        return CheckResult.skipped(site, name, summary="rule disabled")
    if rule.type != "recurring_event":
        return CheckResult.skipped(site, name, summary=f"unsupported rule type {rule.type!r}")

    keyword = str(rule.params.get("match", "")).strip().lower()
    if not keyword:
        return CheckResult.skipped(site, name, summary="rule has no 'match' keyword")

    if not observed_events.is_found:
        return CheckResult.structure_changed(site, name, detail="could not read the events list")

    events: list[Event] = observed_events.value or []
    matches = _match_events(events, keyword)
    if not matches:
        return CheckResult.mismatch(
            site,
            name,
            expected=f"a recurring event matching {keyword!r}",
            observed="not in the upcoming schedule",
            summary=f"expected recurring event ({keyword!r}) not found",
        )

    # Prefer an event explicitly tagged "Recurring".
    event = next((e for e in matches if e.recurring), matches[0])
    expected_weekday = str(rule.params.get("weekday", "")).strip()
    expected_start = str(rule.params.get("start", "")).strip()
    problems: list[str] = []

    if expected_weekday:
        if not event.weekday:
            return CheckResult.structure_changed(
                site, name, detail=f"event {event.title!r} shows no weekday"
            )
        if normalize.text(event.weekday) != normalize.text(expected_weekday):
            problems.append(f"weekday {event.weekday} (expected {expected_weekday})")

    if expected_start:
        if not event.time:
            return CheckResult.structure_changed(
                site, name, detail=f"event {event.title!r} shows no time"
            )
        try:
            event_minutes = normalize.time_to_minutes(event.time)
            expected_minutes = normalize.time_to_minutes(expected_start)
        except ValueError as err:
            return CheckResult.parse_error(
                site, name, detail=f"could not parse event time {event.time!r}: {err}"
            )
        if event_minutes != expected_minutes:
            problems.append(f"start {event.time} (expected {expected_start})")

    expected = f"{event.title} on {expected_weekday} at {expected_start}".strip()
    observed = f"{event.title} on {event.weekday or '?'} at {event.time or '?'}"
    if problems:
        return CheckResult.mismatch(
            site, name, expected=expected, observed=observed, summary="; ".join(problems)
        )
    return CheckResult.ok(site, name, expected=expected, observed=observed)
