"""Run the registered checks against their sources and collect results.

Orchestration only — argument parsing lives in ``cli.py`` and rendering in
``report.py``. A page is fetched once per source; a fetch failure becomes one
``FETCH_ERROR`` per check on that source (not many independent failures, and
never a false mismatch).
"""

from __future__ import annotations

import httpx

from webwatch.checks import registry as checks_registry
from webwatch.checks.base import fetch_error_results
from webwatch.facts import Facts
from webwatch.fetch import FetchError
from webwatch.result import CheckResult
from webwatch.sources import registry as sources_registry
from webwatch.sources.theflip_museum import CHECKS as THEFLIP_CHECKS
from webwatch.sources.theflip_museum import SOURCE as THEFLIP_SOURCE


def register_builtins() -> None:
    """Register the built-in sources and their checks (idempotent)."""
    if sources_registry.get_source(THEFLIP_SOURCE.name) is None:
        sources_registry.register_source(THEFLIP_SOURCE)
        checks_registry.register(THEFLIP_SOURCE.name, THEFLIP_CHECKS)


def run_checks(
    facts: Facts,
    *,
    site: str | None = None,
    fact: str | None = None,
    transport: httpx.BaseTransport | None = None,
) -> list[CheckResult]:
    """Fetch each (filtered) source once and run its checks against ``facts``.

    ``site`` limits to one source; ``fact`` limits to one check field. ``transport``
    is for tests (inject an ``httpx.MockTransport``); production passes none.
    """
    register_builtins()
    results: list[CheckResult] = []

    for source in sources_registry.all_sources():
        if site is not None and source.name != site:
            continue
        checks = checks_registry.checks_for(source.name)
        if fact is not None:
            checks = [check for check in checks if check.field == fact]
        if not checks:
            continue

        try:
            observation = source.fetch(transport=transport)
        except FetchError as err:
            results.extend(fetch_error_results(source.name, [c.field for c in checks], str(err)))
            continue

        results.extend(check.run(observation, facts) for check in checks)

    return results
