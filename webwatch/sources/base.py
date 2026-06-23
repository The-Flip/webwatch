"""Sources: per-site scrapers that fetch a page once and produce an Observation.

A source owns the site-specific knowledge (URL, anchors, how to read each field)
and nothing about comparison — that is the checks layer's job. The key type is
:class:`Observed`, which makes "we read value X" vs "we could not read it" a
type-level distinction with an explicit reason, so a check never mistakes a
missing region for a real value. See ``docs/Extraction.md`` and ``docs/Checks.md``.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

import httpx

from webwatch.extract.anchors import Anchor, Found
from webwatch.fetch import FetchResult, fetch


class NotRead(StrEnum):
    """Why a field could not be read. Each maps to a distinct ``CheckStatus``."""

    MISSING = "missing"  # a tracked field we expected but couldn't locate -> STRUCTURE_CHANGED
    UNPARSEABLE = "unparseable"  # located but un-modelable -> PARSE_ERROR
    BLOCKED = "blocked"  # the page blocked us -> BLOCKED
    NOT_SUPPORTED = "not_supported"  # this source legitimately never publishes it -> SKIPPED


@dataclass(frozen=True, slots=True)
class Observed[T]:
    """Either a located value or a reason it wasn't read.

    Callers must check :attr:`is_found` before reading :attr:`value`. The reason
    is what keeps "missing" from masquerading as a real (often empty) value.
    """

    value: T | None = None
    reason: NotRead | None = None
    note: str = ""

    @classmethod
    def found(cls, value: T) -> Observed[T]:
        return cls(value=value)

    @classmethod
    def missing(cls, note: str = "") -> Observed[T]:
        return cls(reason=NotRead.MISSING, note=note)

    @classmethod
    def unparseable(cls, note: str = "") -> Observed[T]:
        return cls(reason=NotRead.UNPARSEABLE, note=note)

    @classmethod
    def blocked(cls, note: str = "") -> Observed[T]:
        return cls(reason=NotRead.BLOCKED, note=note)

    @classmethod
    def not_supported(cls, note: str = "") -> Observed[T]:
        return cls(reason=NotRead.NOT_SUPPORTED, note=note)

    @classmethod
    def from_anchor(cls, anchor: Anchor) -> Observed[str]:
        """Convert an :class:`~webwatch.extract.anchors.Anchor` result honestly.

        A located value becomes ``found``; a ``NotFound`` becomes ``missing`` (never
        a guessed or empty value). Shared so every source maps anchors the same way.
        """
        if isinstance(anchor, Found):
            return Observed.found(anchor.value)
        return Observed.missing(anchor.reason)

    @property
    def is_found(self) -> bool:
        return self.reason is None


@dataclass(frozen=True, slots=True)
class Observation:
    """Everything one source read from its page in a single fetch.

    ``fields`` are the visible/authoritative reads. ``structured`` holds the
    corroborating values pulled from JSON-LD (field name -> value), used by the
    checks layer to detect metadata drift without letting metadata decide.
    """

    site: str
    fields: dict[str, Observed[Any]] = field(default_factory=dict)
    structured: dict[str, Any] = field(default_factory=dict)

    def get(self, name: str) -> Observed[Any]:
        """The read for ``name``; ``NOT_SUPPORTED`` if this source doesn't track it."""
        return self.fields.get(name, Observed.not_supported(f"{self.site} does not track {name!r}"))


class Source(ABC):
    """A monitored page. Subclasses declare what they track and how to read it."""

    #: Stable identifier used in reports, the registry, and fixtures.
    name: str
    #: The page to fetch.
    url: str
    #: Fact names this source is designed to read. Anything else is NOT_SUPPORTED.
    tracks: frozenset[str]

    @abstractmethod
    def observe(self, html: str) -> Observation:
        """Parse ``html`` into an :class:`Observation`. Pure: no I/O."""

    def blocked_observation(self, note: str) -> Observation:
        """Every tracked field as ``BLOCKED`` — used when the fetch hit a challenge."""
        return Observation(self.site, {name: Observed.blocked(note) for name in self.tracks})

    @property
    def site(self) -> str:
        return self.name

    def fetch(self, *, transport: httpx.BaseTransport | None = None) -> Observation:
        """Fetch the page once and observe it.

        A blocked page yields an all-``BLOCKED`` observation. A fetch failure
        raises :class:`~webwatch.fetch.FetchError` for the caller to map to
        ``FETCH_ERROR`` (so one failure doesn't masquerade as many).
        """
        result: FetchResult = fetch(self.url, transport=transport)
        if result.blocked:
            return self.blocked_observation(result.block_reason or "blocked")
        return self.observe(result.text)
