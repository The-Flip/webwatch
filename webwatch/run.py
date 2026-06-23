"""Run the registered checks against their sources and collect results.

Orchestration only — argument parsing lives in ``cli.py`` and rendering in
``report.py``. A page is fetched once per source; a fetch failure becomes one
``FETCH_ERROR`` per check on that source (not many independent failures, and
never a false mismatch).
"""

from __future__ import annotations

import httpx

from webwatch import rules
from webwatch.checks import registry as checks_registry
from webwatch.checks.base import fetch_error_results
from webwatch.facts import Facts
from webwatch.fetch import FetchError
from webwatch.result import CheckResult
from webwatch.sources import registry as sources_registry
from webwatch.sources.theflip_museum import CHECKS as THEFLIP_CHECKS
from webwatch.sources.theflip_museum import SOURCE as THEFLIP_SOURCE
from webwatch.sources.theflip_museum_visit import CHECKS as VISIT_CHECKS
from webwatch.sources.theflip_museum_visit import SOURCE as VISIT_SOURCE

_BUILTINS = [
    (THEFLIP_SOURCE, THEFLIP_CHECKS),
    (VISIT_SOURCE, VISIT_CHECKS),
]


def register_builtins() -> None:
    """Register the built-in sources and their checks (idempotent)."""
    for source, checks in _BUILTINS:
        if sources_registry.get_source(source.name) is None:
            sources_registry.register_source(source)
            checks_registry.register(source.name, checks)


def run_checks(
    facts: Facts,
    *,
    site: str | None = None,
    fact: str | None = None,
    transport: httpx.BaseTransport | None = None,
) -> list[CheckResult]:
    """Fetch each (filtered) source once and run its checks against ``facts``.

    ``site`` limits to one source; ``fact`` limits to one check field or rule id.
    ``transport`` is for tests (inject an ``httpx.MockTransport``); production passes none.
    """
    register_builtins()
    results: list[CheckResult] = []

    for source in sources_registry.all_sources():
        if site is not None and source.name != site:
            continue
        checks = checks_registry.checks_for(source.name)
        if fact is not None:
            checks = [check for check in checks if check.field == fact]

        # Sources that read an events list get the facts' recurring-event rules run against them.
        event_rules = []
        if getattr(source, "provides_events", False):
            event_rules = [r for r in facts.rules if r.type == "recurring_event"]
            if fact is not None:
                event_rules = [r for r in event_rules if r.id == fact]

        if not checks and not event_rules:
            continue

        try:
            observation = source.fetch(transport=transport)
        except FetchError as err:
            names = [c.field for c in checks] + [r.id for r in event_rules]
            results.extend(fetch_error_results(source.name, names, str(err)))
            continue

        results.extend(check.run(observation, facts) for check in checks)
        results.extend(
            rules.evaluate(rule, observation.events, site=source.name) for rule in event_rules
        )

    return results
