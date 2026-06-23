"""Tests for the core result abstraction.

These pin down the rule webwatch is built on: ``MISMATCH`` (data is wrong) and
the checker conditions (we couldn't read the data) are different kinds of
outcome and route to different exit codes.
"""

from __future__ import annotations

import pytest

from webwatch.result import (
    EXIT_CHECKER_PROBLEM,
    EXIT_DATA_PROBLEM,
    EXIT_OK,
    CheckResult,
    CheckStatus,
    exit_code,
)

CHECKER_STATUSES = [
    CheckStatus.STRUCTURE_CHANGED,
    CheckStatus.PARSE_ERROR,
    CheckStatus.BLOCKED,
    CheckStatus.FETCH_ERROR,
]


def test_only_mismatch_is_a_data_problem() -> None:
    assert CheckStatus.MISMATCH.is_data_problem
    for status in [*CHECKER_STATUSES, CheckStatus.OK, CheckStatus.SKIPPED]:
        assert not status.is_data_problem


@pytest.mark.parametrize("status", CHECKER_STATUSES)
def test_checker_conditions_are_not_data_problems(status: CheckStatus) -> None:
    """A page we couldn't read must never look like a confirmed data discrepancy."""
    assert status.is_checker_problem
    assert not status.is_data_problem


def test_ok_and_skipped_are_not_problems() -> None:
    assert not CheckStatus.OK.is_problem
    assert not CheckStatus.SKIPPED.is_problem


def test_exit_code_all_ok() -> None:
    results = [CheckResult.ok("s", "hours", expected=1, observed=1)]
    assert exit_code(results) == EXIT_OK


def test_exit_code_mismatch_wins_over_checker_problem() -> None:
    """A confirmed discrepancy is the headline outcome even when a checker also broke."""
    results = [
        CheckResult.structure_changed("s", "address", detail="hours block gone"),
        CheckResult.mismatch("s", "hours", expected="9-5", observed="10-6"),
    ]
    assert exit_code(results) == EXIT_DATA_PROBLEM


def test_exit_code_checker_problem_without_mismatch() -> None:
    results = [CheckResult.blocked("s", "address", detail="cloudflare challenge")]
    assert exit_code(results) == EXIT_CHECKER_PROBLEM


def test_constructors_set_expected_status() -> None:
    assert CheckResult.ok("s", "n", expected=1, observed=1).status is CheckStatus.OK
    assert CheckResult.mismatch("s", "n", expected=1, observed=2).status is CheckStatus.MISMATCH
    assert CheckResult.parse_error("s", "n", detail="x").status is CheckStatus.PARSE_ERROR
    assert CheckResult.fetch_error("s", "n", detail="timeout").status is CheckStatus.FETCH_ERROR
