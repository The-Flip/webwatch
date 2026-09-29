"""The registry of checks, and the ``Check`` spec that binds them together.

A :class:`Check` says: which observed field to read, how to pull the expected
value out of :class:`~webwatch.facts.Facts`, how to normalize for comparison, and
(optionally) which structured value corroborates it. The run loop (Phase C) asks
the registry for a source's checks and runs each against the source's Observation.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from webwatch import normalize
from webwatch.checks.base import ABSENT, AnyOf, Normalizer, _as_text, check_field
from webwatch.facts import Facts
from webwatch.result import CheckResult, CheckStatus
from webwatch.sources.base import Observation


@dataclass(frozen=True, slots=True)
class Check:
    """One assertion: read ``field`` from an Observation, compare to ``expected(facts)``."""

    field: str
    expected: Callable[[Facts], Any]
    normalizer: Normalizer = _as_text
    #: key into ``Observation.structured`` for corroboration, if any
    structured_field: str | None = None
    #: field of another check on the same source that must be ``OK`` before this one
    #: is asserted (e.g. a listing's identity) — enforced by :class:`PrerequisiteGate`
    requires: str | None = None

    def run(self, observation: Observation, facts: Facts) -> CheckResult:
        structured = ABSENT
        if self.structured_field is not None:
            structured = observation.structured.get(self.structured_field, ABSENT)
        return check_field(
            observation.site,
            self.field,
            observation.get(self.field),
            self.expected(facts),
            normalizer=self.normalizer,
            structured=structured,
        )


def listing_name(facts: Facts) -> AnyOf:
    """The names a listing site may show: the canonical name or an accepted alternative."""
    return AnyOf((facts.organization.name, *facts.organization.listing_names))


#: The seven per-weekday hours fields, in weekday order.
HOURS_FIELDS = tuple(f"hours.{day}" for day in normalize.WEEKDAYS)


def _hours_getter(day: str) -> Callable[[Facts], Any]:
    """A factory so each check captures its own ``day`` (no late-binding closure trap)."""
    return lambda facts: facts.organization.hours.get(day)


def hours_checks(*, structured: bool = False, requires: str | None = None) -> list[Check]:
    """One ``hours.<day>`` check per weekday, compared through ``normalize.day_hours``.

    ``structured`` corroborates each day against ``Observation.structured["hours.<day>"]``;
    ``requires`` gates every day on another check (see :attr:`Check.requires`).
    """
    return [
        Check(
            f"hours.{day}",
            _hours_getter(day),
            normalize.day_hours,
            structured_field=f"hours.{day}" if structured else None,
            requires=requires,
        )
        for day in normalize.WEEKDAYS
    ]


class PrerequisiteGate:
    """Runs one source's checks against its Observation, honoring :attr:`Check.requires`.

    A check whose prerequisite isn't ``OK`` (e.g. a listing whose name says it's a
    different place) is reported ``STRUCTURE_CHANGED`` instead of being asserted —
    so one wrong identity can't fan out into a burst of false ``MISMATCH``es.
    ``checks`` must be *all* the source's checks: a prerequisite the caller doesn't
    report (``--fact``) is still evaluated. Each check runs at most once.
    """

    def __init__(self, checks: list[Check], observation: Observation, facts: Facts) -> None:
        validate_prerequisites(checks)
        self._by_field = {check.field: check for check in checks}
        self._observation = observation
        self._facts = facts
        self._results: dict[str, CheckResult] = {}

    def run(self, check: Check) -> CheckResult:
        if check.field not in self._results:
            self._results[check.field] = self._evaluate(check)
        return self._results[check.field]

    def _evaluate(self, check: Check) -> CheckResult:
        if check.requires is not None:
            status = self.run(self._by_field[check.requires]).status
            if status is not CheckStatus.OK:
                return CheckResult.structure_changed(
                    self._observation.site,
                    check.field,
                    detail=f"prerequisite check {check.requires!r} was {status}",
                    summary=f"not asserted: prerequisite {check.requires!r} did not pass",
                )
        return check.run(self._observation, self._facts)


def validate_prerequisites(checks: list[Check]) -> None:
    """Raise ``ValueError`` unless every ``requires`` names a sibling check, acyclically.

    A typo'd or circular prerequisite is our own configuration bug; it must fail
    loudly at registration, not surface later as a misleading page-changed result.
    """
    by_field = {check.field: check for check in checks}
    for check in checks:
        seen = {check.field}
        current = check
        while current.requires is not None:
            if current.requires not in by_field:
                raise ValueError(
                    f"check {current.field!r} requires unknown check {current.requires!r}"
                )
            if current.requires in seen:
                raise ValueError(f"circular prerequisites involving check {check.field!r}")
            seen.add(current.requires)
            current = by_field[current.requires]


_REGISTRY: dict[str, list[Check]] = {}


def register(source_name: str, checks: list[Check]) -> None:
    """Register the checks that run against a source's Observation."""
    combined = [*_REGISTRY.get(source_name, []), *checks]
    validate_prerequisites(combined)
    _REGISTRY[source_name] = combined


def checks_for(source_name: str) -> list[Check]:
    return list(_REGISTRY.get(source_name, []))


def registered_sources() -> list[str]:
    return list(_REGISTRY)


def clear() -> None:
    """Reset the registry (used by tests)."""
    _REGISTRY.clear()
