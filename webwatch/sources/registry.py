"""Registry of source instances, keyed by their ``name``.

The run loop (Phase C) iterates registered sources, fetches each once, and runs
the source's checks (from ``webwatch.checks.registry``) against the Observation.
"""

from __future__ import annotations

from webwatch.sources.base import Source

_SOURCES: dict[str, Source] = {}


def register_source(source: Source) -> None:
    _SOURCES[source.name] = source


def get_source(name: str) -> Source | None:
    return _SOURCES.get(name)


def all_sources() -> list[Source]:
    return list(_SOURCES.values())


def clear() -> None:
    """Reset the registry (used by tests)."""
    _SOURCES.clear()
