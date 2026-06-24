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

import re

from webwatch import normalize
from webwatch.events import Event
from webwatch.facts import Rule
from webwatch.result import CheckResult, CheckStatus
from webwatch.sources.base import Observed


def _match_events(events: list[Event], keyword: str) -> list[Event]:
    """Events matching ``keyword`` as a whole word — by title first, then description.

    Whole-word matching (not bare substring) avoids collisions like ``"art"`` in
    ``"Party"`` (agy Phase D review).
    """
    pattern = re.compile(rf"\b{re.escape(keyword)}\b")
    by_title = [e for e in events if pattern.search(e.title.lower())]
    if by_title:
        return by_title
    return [e for e in events if pattern.search(e.description.lower())]


def _event_window(text: str) -> tuple[int, int | None]:
    """Parse an event time that may be a single start or a ``start - end`` range.

    Returns ``(start_minutes, end_minutes_or_None)``. Raises ``ValueError`` only
    when the text is not a time at all (the caller maps that to ``PARSE_ERROR``).
    """
    try:
        return normalize.time_range(text)
    except ValueError:
        return normalize.time_to_minutes(text), None


def _hhmm(minutes: int) -> str:
    return f"{minutes // 60 % 24:02d}:{minutes % 60:02d}"


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

    # Evaluate every matching event; the rule is satisfied if ANY of them passes
    # (a wrong "Repair Prep" earlier in the list shouldn't fail a correct "Repair
    # Day" later, agy Phase D review). Otherwise surface the most informative
    # failure — prefer a confirmed MISMATCH over a couldn't-read condition.
    results = [_evaluate_event(rule, event, site=site, name=name) for event in matches]
    for result in results:
        if result.status is CheckStatus.OK:
            return result
    for result in results:
        if result.status is CheckStatus.MISMATCH:
            return result
    return results[0]


def _evaluate_event(rule: Rule, event: Event, *, site: str, name: str) -> CheckResult:
    """Check one matched event against the rule's weekday and time window."""
    expected_weekday = str(rule.params.get("weekday", "")).strip()
    expected_start = str(rule.params.get("start", "")).strip()
    expected_end = str(rule.params.get("end", "")).strip()
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
            event_start, event_end = _event_window(event.time)
            expected_start_min = normalize.time_to_minutes(expected_start)
            expected_end_min = normalize.time_to_minutes(expected_end) if expected_end else None
        except ValueError as err:
            return CheckResult.parse_error(
                site, name, detail=f"could not parse event time {event.time!r}: {err}"
            )
        if event_start != expected_start_min:
            problems.append(f"start {_hhmm(event_start)} (expected {expected_start})")
        if expected_end_min is not None and event_end is not None and event_end != expected_end_min:
            problems.append(f"end {_hhmm(event_end)} (expected {expected_end})")

    expected = f"{event.title} on {expected_weekday} at {expected_start}".strip()
    observed = f"{event.title} on {event.weekday or '?'} at {event.time or '?'}"
    if problems:
        return CheckResult.mismatch(
            site, name, expected=expected, observed=observed, summary="; ".join(problems)
        )
    return CheckResult.ok(site, name, expected=expected, observed=observed)
