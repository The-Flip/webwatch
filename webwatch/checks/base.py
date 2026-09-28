"""Assertions: turn an Observed field + an expected fact into a CheckResult.

This is where "matches / differs / couldn't read" is decided. The mapping is the
spec from ``docs/Extraction.md``; the corroboration rule is the agy-reviewed
correction (visible value decides; stale-but-visible-correct is ``METADATA_DRIFT``,
never a false ``MISMATCH``). Comparison always goes through a normalizer.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Any

from webwatch import normalize
from webwatch.facts import is_blank
from webwatch.result import CheckResult
from webwatch.sources.base import NotRead, Observed

# Sentinel: "no structured value was offered" (distinct from a present-but-empty one).
ABSENT: Any = object()

Normalizer = Callable[[Any], object]


@dataclass(frozen=True, slots=True)
class AnyOf:
    """An expected fact satisfied by any one of several accepted values.

    For facts a site may legitimately publish in more than one form — e.g. a
    listing that shows the museum's longer name. Each value is still compared
    exactly (after normalization); blank values are ignored.
    """

    values: tuple[Any, ...]


def _as_text(value: Any) -> object:
    return normalize.text(value if isinstance(value, str) else str(value))


def check_field(
    site: str,
    name: str,
    observed: Observed[Any],
    expected: Any,
    *,
    normalizer: Normalizer = _as_text,
    structured: Any = ABSENT,
) -> CheckResult:
    """Compare one observed field to its expected fact.

    ``normalizer`` canonicalizes both sides before comparison (e.g.
    ``normalize.street``). ``structured`` is the corroborating JSON-LD value, or
    ``ABSENT`` if none was offered. ``expected`` may be an :class:`AnyOf`, which
    passes if the observed value matches any of its non-blank values. A blank
    expected fact (for ``AnyOf``: every value blank), or a field the source does
    not track, is ``SKIPPED`` — never asserted against.
    """
    candidates = expected.values if isinstance(expected, AnyOf) else (expected,)
    accepted = [value for value in candidates if not is_blank(value)]
    if not accepted:
        return CheckResult.skipped(site, name, summary="no expected value set")
    # Reported as the single value, or the list of accepted values.
    reported = accepted[0] if len(accepted) == 1 else accepted

    if not observed.is_found:
        return _not_found_result(site, name, observed)

    # Found a value. Normalize both sides; a normalizer that rejects the *observed*
    # value means the page had something we can't model -> PARSE_ERROR. A normalizer
    # that rejects the *expected* fact is our own config bug, so let it raise loudly.
    accepted_norm = [normalizer(value) for value in accepted]
    try:
        observed_norm = normalizer(observed.value)
    except ValueError as err:
        return CheckResult.parse_error(site, name, detail=f"observed value not modelable: {err}")

    if observed_norm not in accepted_norm:
        return CheckResult.mismatch(site, name, expected=reported, observed=observed.value)

    # Visible value is correct. Corroborate against structured metadata if offered:
    # disagreement is drift (worth fixing), not a world-state mismatch.
    if structured is not ABSENT and not is_blank(structured):
        try:
            structured_norm = normalizer(structured)
        except ValueError:
            structured_norm = observed_norm  # unmodelable metadata -> no drift signal
        if structured_norm not in accepted_norm:
            return CheckResult.metadata_drift(
                site,
                name,
                expected=reported,
                observed=observed.value,
                detail=f"structured metadata says {structured!r} but visible value is correct",
            )

    return CheckResult.ok(site, name, expected=reported, observed=observed.value)


def _not_found_result(site: str, name: str, observed: Observed[Any]) -> CheckResult:
    note = observed.note
    match observed.reason:
        case NotRead.MISSING:
            return CheckResult.structure_changed(site, name, detail=note or "field not located")
        case NotRead.UNPARSEABLE:
            return CheckResult.parse_error(site, name, detail=note or "value unparseable")
        case NotRead.BLOCKED:
            return CheckResult.blocked(site, name, detail=note or "page blocked")
        case NotRead.NOT_SUPPORTED:
            return CheckResult.skipped(site, name, summary=note or "not tracked by this source")
        case _:  # pragma: no cover - defensive; reason is None only when is_found
            raise ValueError(f"unexpected not-found reason: {observed.reason!r}")


def fetch_error_results(site: str, names: Iterable[str], detail: str) -> list[CheckResult]:
    """One ``FETCH_ERROR`` result per check name — used when a source's fetch fails.

    A single fetch failure becomes one error per check rather than masquerading as
    many independent failures or, worse, many false mismatches.
    """
    return [CheckResult.fetch_error(site, name, detail=detail) for name in names]
