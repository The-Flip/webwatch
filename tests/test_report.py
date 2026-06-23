"""Tests for report rendering (text + JSON)."""

from __future__ import annotations

import json

from webwatch.report import render_json, render_text, summary_line
from webwatch.result import CheckResult


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
