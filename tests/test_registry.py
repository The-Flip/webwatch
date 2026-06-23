"""Tests for the source and check registries."""

from __future__ import annotations

import pytest

from webwatch.checks import registry as checks_registry
from webwatch.checks.registry import Check
from webwatch.sources import registry as sources_registry
from webwatch.sources.base import Observation, Source


class _Src(Source):
    name = "demo"
    url = "https://demo.test/"
    tracks = frozenset({"name"})

    def observe(self, html: str) -> Observation:  # pragma: no cover - not exercised here
        return Observation(self.site)


@pytest.fixture(autouse=True)
def _clean():
    sources_registry.clear()
    checks_registry.clear()
    yield
    sources_registry.clear()
    checks_registry.clear()


def test_source_registry_register_get_all() -> None:
    source = _Src()
    sources_registry.register_source(source)
    assert sources_registry.get_source("demo") is source
    assert sources_registry.all_sources() == [source]
    assert sources_registry.get_source("missing") is None


def test_check_registry_accumulates_and_lists() -> None:
    checks_registry.register("demo", [Check("name", lambda f: f.organization.name)])
    checks_registry.register("demo", [Check("phone", lambda f: f.organization.phone)])
    assert [c.field for c in checks_registry.checks_for("demo")] == ["name", "phone"]
    assert checks_registry.registered_sources() == ["demo"]
    assert checks_registry.checks_for("unknown") == []
