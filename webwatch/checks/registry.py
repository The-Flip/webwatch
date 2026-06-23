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

from webwatch.checks.base import ABSENT, Normalizer, _as_text, check_field
from webwatch.facts import Facts
from webwatch.result import CheckResult
from webwatch.sources.base import Observation


@dataclass(frozen=True, slots=True)
class Check:
    """One assertion: read ``field`` from an Observation, compare to ``expected(facts)``."""

    field: str
    expected: Callable[[Facts], Any]
    normalizer: Normalizer = _as_text
    #: key into ``Observation.structured`` for corroboration, if any
    structured_field: str | None = None

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


_REGISTRY: dict[str, list[Check]] = {}


def register(source_name: str, checks: list[Check]) -> None:
    """Register the checks that run against a source's Observation."""
    _REGISTRY.setdefault(source_name, []).extend(checks)


def checks_for(source_name: str) -> list[Check]:
    return list(_REGISTRY.get(source_name, []))


def registered_sources() -> list[str]:
    return list(_REGISTRY)


def clear() -> None:
    """Reset the registry (used by tests)."""
    _REGISTRY.clear()
