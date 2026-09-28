"""Tests for report rendering (text + JSON)."""

from __future__ import annotations

import json

from webwatch.report import render_json, render_matrix, render_text, summary_line
from webwatch.result import CheckResult, CheckStatus


def _results() -> list[CheckResult]:
    return [
        CheckResult.ok("site", "name", expected="The Flip", observed="The Flip"),
        CheckResult.mismatch("site", "hours", expected="9-5", observed="10-6"),
        CheckResult.structure_changed("site", "address", detail="block gone"),
    ]


def test_summary_line_counts() -> None:
    line = summary_line(_results())
    assert line.startswith("3 checks:")
    assert "1 mismatch" in line
    assert "1 ok" in line


def test_summary_line_empty() -> None:
    assert summary_line([]) == "0 checks."


def test_render_text_problems_first() -> None:
    text = render_text(_results())
    lines = text.splitlines()
    # After the summary line, the worst status (mismatch) comes before ok.
    body = lines[1:]
    mismatch_idx = next(i for i, ln in enumerate(body) if "mismatch" in ln)
    ok_idx = next(i for i, ln in enumerate(body) if "] site/name" in ln)
    assert mismatch_idx < ok_idx
    assert "block gone" in text  # detail shown for structure_changed


def test_render_json_is_valid_and_complete() -> None:
    payload = json.loads(render_json(_results()))
    assert len(payload) == 3
    statuses = {row["status"] for row in payload}
    assert statuses == {"ok", "mismatch", "structure_changed"}
    assert all({"site", "name", "status", "summary"} <= row.keys() for row in payload)


# --- check-by-site matrix -----------------------------------------------------------


def _matrix_lines(
    statuses: dict[tuple[str, str], CheckStatus], labels: dict[str, str]
) -> list[str]:
    return render_matrix(statuses, labels).splitlines()


def test_matrix_rows_are_checks_and_columns_are_labelled_sites() -> None:
    lines = _matrix_lines(
        {
            ("apple_maps", "name"): CheckStatus.OK,
            ("website", "email"): CheckStatus.OK,
        },
        {"website": "Website", "apple_maps": "Apple Maps"},
    )
    assert lines[0].split() == ["check", "Website", "Apple", "Maps"]
    assert lines[2].split() == ["name", "·", "ok"]  # name row first; not checked on Website
    assert lines[3].split() == ["email", "ok", "·"]


def test_matrix_groups_hours_days_and_shows_the_worst() -> None:
    statuses = {("g", f"hours.{day}"): CheckStatus.OK for day in ("monday", "tuesday")}
    statuses[("g", "hours.sunday")] = CheckStatus.MISMATCH
    lines = _matrix_lines(statuses, {"g": "Google"})
    assert [line.split() for line in lines[2:]] == [["hours", "MISMATCH"]]


def test_matrix_unknown_sites_follow_labelled_ones() -> None:
    lines = _matrix_lines(
        {("zeta", "name"): CheckStatus.OK, ("alpha", "name"): CheckStatus.BLOCKED},
        {"zeta": "Zeta"},
    )
    assert lines[0].split() == ["check", "Zeta", "alpha"]
    assert lines[2].split() == ["name", "ok", "blocked"]
