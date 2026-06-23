"""Render a run's results as human-readable text or JSON.

Pure formatting — the CLI prints what these return. The text report leads with a
one-line summary so an operator skimming a cron log sees the headline first.
"""

from __future__ import annotations

import json
from collections import Counter

from webwatch.result import CheckResult, CheckStatus

# Order statuses worst-first so problems surface at the top of the report.
_SEVERITY_ORDER = {
    CheckStatus.MISMATCH: 0,
    CheckStatus.STRUCTURE_CHANGED: 1,
    CheckStatus.PARSE_ERROR: 2,
    CheckStatus.BLOCKED: 3,
    CheckStatus.FETCH_ERROR: 4,
    CheckStatus.METADATA_DRIFT: 5,
    CheckStatus.OK: 6,
    CheckStatus.SKIPPED: 7,
}


def summary_line(results: list[CheckResult]) -> str:
    """A one-line tally, e.g. ``5 checks: 3 ok, 1 mismatch, 1 structure_changed``."""
    if not results:
        return "0 checks."
    counts = Counter(r.status for r in results)
    parts = [
        f"{counts[status]} {status.value}"
        for status in sorted(counts, key=lambda s: _SEVERITY_ORDER[s])
    ]
    return f"{len(results)} checks: " + ", ".join(parts)


def render_text(results: list[CheckResult]) -> str:
    """A summary line followed by one line per check, worst-first."""
    lines = [summary_line(results)]
    for result in sorted(results, key=lambda r: (_SEVERITY_ORDER[r.status], r.site, r.name)):
        detail = result.detail or result.summary
        suffix = f" — {detail}" if detail else ""
        lines.append(f"  [{result.status.value:>17}] {result.site}/{result.name}{suffix}")
    return "\n".join(lines)


def render_json(results: list[CheckResult]) -> str:
    """A JSON array of result objects (stable keys for downstream tooling)."""
    payload = [
        {
            "site": r.site,
            "name": r.name,
            "status": r.status.value,
            "summary": r.summary,
            "expected": r.expected,
            "observed": r.observed,
            "detail": r.detail,
        }
        for r in results
    ]
    return json.dumps(payload, indent=2, default=str)
