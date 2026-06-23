"""Tests for the assertion layer — every CheckStatus mapping and corroboration.

This is the proof that a found-but-wrong value is a MISMATCH while a couldn't-read
value is never a MISMATCH, and that stale-metadata-with-correct-visible is drift,
not a false alarm.
"""

from __future__ import annotations

from webwatch import normalize
from webwatch.checks.base import check_field
from webwatch.result import CheckStatus
from webwatch.sources.base import Observed

SITE = "fake"


def test_blank_expected_is_skipped() -> None:
    result = check_field(SITE, "phone", Observed.found("anything"), expected="")
    assert result.status is CheckStatus.SKIPPED


def test_not_supported_is_skipped() -> None:
    result = check_field(SITE, "phone", Observed.not_supported(), expected="555-1234")
    assert result.status is CheckStatus.SKIPPED


def test_found_and_matches_is_ok() -> None:
    result = check_field(SITE, "name", Observed.found("The Flip"), expected="the flip")
    assert result.status is CheckStatus.OK


def test_found_and_differs_is_mismatch() -> None:
    result = check_field(SITE, "name", Observed.found("The Flop"), expected="The Flip")
    assert result.status is CheckStatus.MISMATCH


def test_missing_is_structure_changed_not_mismatch() -> None:
    """The cardinal rule: a missing region is never a MISMATCH."""
    result = check_field(SITE, "name", Observed.missing("label gone"), expected="The Flip")
    assert result.status is CheckStatus.STRUCTURE_CHANGED


def test_unparseable_observed_reason_is_parse_error() -> None:
    result = check_field(SITE, "hours", Observed.unparseable("weird"), expected="x")
    assert result.status is CheckStatus.PARSE_ERROR


def test_normalizer_rejecting_observed_value_is_parse_error() -> None:
    """A found value that won't model (e.g. 'call us' as a phone) is PARSE_ERROR."""
    result = check_field(
        SITE,
        "phone",
        Observed.found("call us!"),
        expected="555-123-4567",
        normalizer=normalize.phone,
    )
    assert result.status is CheckStatus.PARSE_ERROR


def test_blocked_observed_is_blocked() -> None:
    result = check_field(SITE, "name", Observed.blocked("cloudflare"), expected="The Flip")
    assert result.status is CheckStatus.BLOCKED


def test_street_normalizer_equivalence_is_ok() -> None:
    result = check_field(
        SITE,
        "street",
        Observed.found("123 Main Street"),
        expected="123 Main St",
        normalizer=normalize.street,
    )
    assert result.status is CheckStatus.OK


def test_metadata_drift_when_visible_correct_but_jsonld_stale() -> None:
    """Visible value matches expected; stale JSON-LD disagrees -> drift, not MISMATCH (agy Gap B)."""
    result = check_field(
        SITE,
        "name",
        Observed.found("The Flip"),
        expected="The Flip",
        structured="The Flop",  # stale metadata
    )
    assert result.status is CheckStatus.METADATA_DRIFT


def test_no_drift_when_structured_agrees() -> None:
    result = check_field(
        SITE, "name", Observed.found("The Flip"), expected="The Flip", structured="the flip"
    )
    assert result.status is CheckStatus.OK


def test_visible_mismatch_wins_over_structured() -> None:
    """If the visible value is wrong it is a MISMATCH regardless of JSON-LD."""
    result = check_field(
        SITE,
        "name",
        Observed.found("The Flop"),
        expected="The Flip",
        structured="The Flip",  # metadata happens to be right
    )
    assert result.status is CheckStatus.MISMATCH
