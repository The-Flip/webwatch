"""Run-to-run state, so notifications fire on *transitions* — not every run.

A monitoring tool that emails on every run while a known problem persists trains
operators to ignore it. So we persist each check's recent health and alert only
when a check crosses into a problem state, with hysteresis to absorb flapping.

Per the agy review (Gap E), health is a two-way partition, not the exact status:
``OK``/``SKIPPED`` are HEALTHY, everything else is UNHEALTHY. The unhealthy streak
therefore keeps climbing even if the *kind* of failure changes between runs
(``FETCH_ERROR`` then ``STRUCTURE_CHANGED`` then ``BLOCKED``), so a persistent
problem still escalates instead of resetting on each status change.

Known limitation: a check that strictly *alternates* healthy/unhealthy every run
never reaches the consecutive threshold, so a ~50% flap is not alerted. A windowed
failure-rate signal would catch it; that is deferred until a real source shows the
need rather than adding speculative machinery now.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

from webwatch import config
from webwatch.result import CheckResult, CheckStatus

_HEALTHY = frozenset({CheckStatus.OK, CheckStatus.SKIPPED})


def _key(site: str, name: str) -> str:
    return f"{site}\t{name}"


@dataclass(slots=True)
class CheckState:
    status: str
    unhealthy_streak: int = 0
    healthy_streak: int = 0
    alerting: bool = False
    #: whether the current alert has been successfully handed off to notification.
    #: An alert that failed to send stays ``False`` so the next run retries it.
    notified: bool = False


@dataclass(frozen=True, slots=True)
class Transition:
    """A check that just crossed into ('alert') or out of ('recover') a problem."""

    site: str
    name: str
    kind: str  # "alert" | "recover"
    status: CheckStatus


State = dict[str, CheckState]


def load_state(path: str | Path | None = None) -> State:
    """Load persisted state, or an empty state if the file doesn't exist."""
    state_path = Path(path) if path is not None else Path(config.STATE_PATH)
    if not state_path.exists():
        return {}
    raw = json.loads(state_path.read_text(encoding="utf-8"))
    return {key: CheckState(**value) for key, value in raw.get("checks", {}).items()}


def save_state(state: State, path: str | Path | None = None) -> None:
    """Persist state as JSON."""
    state_path = Path(path) if path is not None else Path(config.STATE_PATH)
    payload = {"checks": {key: asdict(value) for key, value in state.items()}}
    state_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def apply_results(
    previous: State,
    results: list[CheckResult],
    *,
    alert_after: int | None = None,
    recover_after: int | None = None,
) -> tuple[State, list[Transition]]:
    """Fold a run's results into state, returning the new state and any transitions.

    A check must be unhealthy for ``alert_after`` consecutive runs before it
    raises an alert, and healthy for ``recover_after`` consecutive runs before the
    alert clears. Thresholds default from config.
    """
    threshold = config.ALERT_AFTER_FAILURES if alert_after is None else alert_after
    recover = config.RECOVER_AFTER_SUCCESSES if recover_after is None else recover_after

    new_state: State = {}
    transitions: list[Transition] = []

    for result in results:
        key = _key(result.site, result.name)
        prior = previous.get(key)
        was_alerting = prior.alerting if prior else False
        notified = prior.notified if prior else False
        healthy = result.status in _HEALTHY

        if healthy:
            healthy_streak = (prior.healthy_streak + 1) if prior else 1
            unhealthy_streak = 0
        else:
            unhealthy_streak = (prior.unhealthy_streak + 1) if prior else 1
            healthy_streak = 0

        alerting = was_alerting
        recovered = False
        if not was_alerting and unhealthy_streak >= threshold:
            alerting = True
            notified = False  # a fresh alert, not yet handed to notification
        elif was_alerting and healthy_streak >= recover:
            alerting = False
            notified = False
            recovered = True

        # Recovery is one-shot; an alert re-fires every run until it is notified,
        # so a send that failed last run is retried (no silently-dropped alarm).
        if recovered:
            transitions.append(Transition(result.site, result.name, "recover", result.status))
        elif alerting and not notified:
            transitions.append(Transition(result.site, result.name, "alert", result.status))

        new_state[key] = CheckState(
            status=result.status.value,
            unhealthy_streak=unhealthy_streak,
            healthy_streak=healthy_streak,
            alerting=alerting,
            notified=notified,
        )

    return new_state, transitions


def mark_notified(state: State, transitions: list[Transition]) -> None:
    """Mark each alerted check as notified — call only after a send did not fail.

    Persisting ``notified=True`` is what stops an alert from re-firing every run;
    if the send raised, skip this so the next run retries.
    """
    for transition in transitions:
        if transition.kind == "alert":
            check_state = state.get(_key(transition.site, transition.name))
            if check_state is not None:
                check_state.notified = True
