"""The result of a single check — webwatch's core abstraction.

The whole point of webwatch is to separate *three* outcomes that naive scrapers
conflate:

1. The value is present and correct (``OK``).
2. The value is present but wrong (``MISMATCH``) — a real, actionable problem.
3. We could not read the value at all — the page changed, broke, or blocked us
   (``STRUCTURE_CHANGED`` / ``PARSE_ERROR`` / ``BLOCKED`` / ``FETCH_ERROR``).

A fourth, subtler case (``METADATA_DRIFT``) sits beside these: the visible value
is correct, but the page's structured metadata disagrees — worth fixing, but not
a claim that the world is wrong.

Conflating (2) and (3) is what produces false positives ("the address is wrong!"
when really the page was redesigned) and false negatives (silently passing
because an empty extraction "matched" nothing). Keeping them distinct is the
design rule the rest of the codebase is built around. See ``docs/Extraction.md``.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any

# Process exit codes, returned by ``webwatch check``.
EXIT_OK = 0
#: At least one MISMATCH — published information is genuinely out of sync.
EXIT_DATA_PROBLEM = 1
#: At least one checker condition (couldn't read/fetch) — our checker needs attention.
EXIT_CHECKER_PROBLEM = 2


class CheckStatus(StrEnum):
    """The outcome of a check.

    Read the module docstring before adding a status. The split between "the data
    is wrong" and "we couldn't read the data" must never blur.
    """

    OK = "ok"
    """Value extracted with confidence and matches the expected fact."""

    MISMATCH = "mismatch"
    """Value extracted with confidence but differs from the expected fact.

    A real problem: the published info is out of sync. The *only* status that
    asserts the world is wrong — so it must only be produced when a value was
    genuinely located and read.
    """

    STRUCTURE_CHANGED = "structure_changed"
    """The data region could not be located by any strategy (or strategies
    disagreed). The page's structure broke our extraction — needs human review.
    Never a data mismatch."""

    PARSE_ERROR = "parse_error"
    """The region was located but its value is malformed/unparseable into the
    canonical model. Structure intact, value un-modelable — needs human review."""

    BLOCKED = "blocked"
    """The page returned but is a CAPTCHA / challenge / login wall / bot block /
    empty JS-hydration shell. An access problem, not a structural code change."""

    FETCH_ERROR = "fetch_error"
    """The page could not be fetched (network/HTTP failure after retries)."""

    METADATA_DRIFT = "metadata_drift"
    """The visible value is correct, but the page's structured metadata (JSON-LD)
    disagrees with it. The published info a human sees is fine, so this is NOT a
    ``MISMATCH``; but the stale metadata can mislead search engines and is worth
    fixing. A needs-attention condition, not a world-state error."""

    SKIPPED = "skipped"
    """The check was disabled or not applicable this run."""

    @property
    def is_ok(self) -> bool:
        return self is CheckStatus.OK

    @property
    def is_data_problem(self) -> bool:
        """A confirmed, actionable data discrepancy."""
        return self is CheckStatus.MISMATCH

    @property
    def is_checker_problem(self) -> bool:
        """We couldn't produce a trustworthy answer — needs human/operator attention."""
        return self in _CHECKER_PROBLEMS

    @property
    def is_problem(self) -> bool:
        """Any non-OK, non-skipped outcome."""
        return self.is_data_problem or self.is_checker_problem


_CHECKER_PROBLEMS = frozenset(
    {
        CheckStatus.STRUCTURE_CHANGED,
        CheckStatus.PARSE_ERROR,
        CheckStatus.BLOCKED,
        CheckStatus.FETCH_ERROR,
        CheckStatus.METADATA_DRIFT,
    }
)


@dataclass(frozen=True, slots=True)
class CheckResult:
    """The outcome of checking one fact on one site.

    ``expected`` / ``observed`` are filled in only when meaningful (``OK`` and
    ``MISMATCH``). ``detail`` carries operator-facing context — e.g. which anchor
    went missing for ``STRUCTURE_CHANGED``, or which challenge page we hit for
    ``BLOCKED`` — so a human can triage without re-running by hand.
    """

    site: str
    name: str
    status: CheckStatus
    summary: str = ""
    expected: Any = None
    observed: Any = None
    detail: str | None = None

    # --- intention-revealing constructors -------------------------------------

    @classmethod
    def ok(
        cls, site: str, name: str, *, expected: Any, observed: Any, summary: str = ""
    ) -> CheckResult:
        return cls(site, name, CheckStatus.OK, summary or "matches", expected, observed)

    @classmethod
    def mismatch(
        cls, site: str, name: str, *, expected: Any, observed: Any, summary: str = ""
    ) -> CheckResult:
        return cls(
            site,
            name,
            CheckStatus.MISMATCH,
            summary or "published value differs from expected",
            expected,
            observed,
        )

    @classmethod
    def structure_changed(
        cls, site: str, name: str, *, detail: str, summary: str = ""
    ) -> CheckResult:
        return cls(
            site,
            name,
            CheckStatus.STRUCTURE_CHANGED,
            summary or "could not locate the data region",
            detail=detail,
        )

    @classmethod
    def parse_error(cls, site: str, name: str, *, detail: str, summary: str = "") -> CheckResult:
        return cls(
            site,
            name,
            CheckStatus.PARSE_ERROR,
            summary or "value could not be parsed",
            detail=detail,
        )

    @classmethod
    def blocked(cls, site: str, name: str, *, detail: str, summary: str = "") -> CheckResult:
        return cls(site, name, CheckStatus.BLOCKED, summary or "access was blocked", detail=detail)

    @classmethod
    def metadata_drift(
        cls, site: str, name: str, *, expected: Any, observed: Any, detail: str, summary: str = ""
    ) -> CheckResult:
        return cls(
            site,
            name,
            CheckStatus.METADATA_DRIFT,
            summary or "visible value is correct but structured metadata is stale",
            expected,
            observed,
            detail,
        )

    @classmethod
    def fetch_error(cls, site: str, name: str, *, detail: str, summary: str = "") -> CheckResult:
        return cls(
            site,
            name,
            CheckStatus.FETCH_ERROR,
            summary or "could not fetch the page",
            detail=detail,
        )

    @classmethod
    def skipped(cls, site: str, name: str, *, summary: str = "") -> CheckResult:
        return cls(site, name, CheckStatus.SKIPPED, summary or "skipped")


def exit_code(results: list[CheckResult]) -> int:
    """Collapse a run's results into a process exit code.

    A confirmed data discrepancy (``MISMATCH``) is the headline outcome and wins
    over a checker condition; checker conditions in turn win over all-clear. This
    lets a cron wrapper route "data is wrong" (1) differently from "our checker
    broke" (2). The full per-check breakdown lives in the report regardless.
    """
    if any(r.status.is_data_problem for r in results):
        return EXIT_DATA_PROBLEM
    if any(r.status.is_checker_problem for r in results):
        return EXIT_CHECKER_PROBLEM
    return EXIT_OK
