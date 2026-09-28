"""Render a run's results as human-readable text or JSON, and the digest's
check-by-site status table.

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


# --- the check-by-site matrix (digest) ----------------------------------------------

# Short cell labels, so the table stays narrow enough for an email.
_CELL = {
    CheckStatus.OK: "ok",
    CheckStatus.MISMATCH: "MISMATCH",
    CheckStatus.METADATA_DRIFT: "drift",
    CheckStatus.STRUCTURE_CHANGED: "changed",
    CheckStatus.PARSE_ERROR: "unparsed",
    CheckStatus.BLOCKED: "blocked",
    CheckStatus.FETCH_ERROR: "fetch err",
    CheckStatus.SKIPPED: "skipped",
}
_NOT_CHECKED = "·"
# Identity and contact first; anything unlisted (rules, event checks) follows in
# the order first seen.
_ROW_ORDER = (
    "name",
    "url",
    "phone",
    "email",
    "address.street",
    "address.city",
    "address.region",
    "address.postal_code",
    "business_status",
    "hours",
)


def _row(check_name: str) -> str:
    """The table row a check belongs to; the seven ``hours.<day>`` checks share one."""
    return "hours" if check_name.startswith("hours.") else check_name


def _ordered_sites(checked: set[str], site_labels: dict[str, str]) -> list[str]:
    """Labelled sites in label order, then any others by name."""
    return [s for s in site_labels if s in checked] + sorted(checked - set(site_labels))


def _ordered_rows(checks: list[str]) -> list[str]:
    """Rows in ``_ROW_ORDER`` first, then the rest in first-seen order."""
    seen = dict.fromkeys(_row(check) for check in checks)
    return [r for r in _ROW_ORDER if r in seen] + [r for r in seen if r not in _ROW_ORDER]


def _worst_per_cell(
    statuses: dict[tuple[str, str], CheckStatus],
) -> dict[tuple[str, str], CheckStatus]:
    """``(row, site)`` -> the most severe status among the checks in that cell."""
    cells: dict[tuple[str, str], CheckStatus] = {}
    for (site, check), status in statuses.items():
        key = (_row(check), site)
        if key not in cells or _SEVERITY_ORDER[status] < _SEVERITY_ORDER[cells[key]]:
            cells[key] = status
    return cells


def _format_table(table: list[list[str]]) -> str:
    """Left-aligned columns, two spaces apart, with a rule under the header row."""
    widths = [max(len(line[i]) for line in table) for i in range(len(table[0]))]
    lines = [
        "  ".join(cell.ljust(width) for cell, width in zip(line, widths, strict=True)).rstrip()
        for line in table
    ]
    lines.insert(1, "  ".join("-" * width for width in widths))
    return "\n".join(lines)


def render_matrix(statuses: dict[tuple[str, str], CheckStatus], site_labels: dict[str, str]) -> str:
    """A plain-text table of checks (rows) by sites (columns) with each latest status.

    Unlike the reports above, this renders persisted state (the latest status of
    every tracked check, from ``state.latest_statuses``), not a single run.
    ``site_labels`` gives the column headings, in column order. A grouped row
    (hours) shows its worst day. ``·`` means no result for that check on that site
    — the site doesn't check it, or hasn't reported it yet.
    """
    sites = _ordered_sites({site for site, _ in statuses}, site_labels)
    rows = _ordered_rows([check for _, check in statuses])
    cells = _worst_per_cell(statuses)
    header = ["check", *(site_labels.get(site, site) for site in sites)]
    body = [
        [
            row,
            *(
                _CELL[cells[(row, site)]] if (row, site) in cells else _NOT_CHECKED
                for site in sites
            ),
        ]
        for row in rows
    ]
    return _format_table([header, *body])
