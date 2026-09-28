"""Tests for the source and check registries."""

from __future__ import annotations

from collections.abc import Callable

import pytest

from webwatch.checks import registry as checks_registry
from webwatch.checks.registry import Check, PrerequisiteGate
from webwatch.facts import Facts, load_facts
from webwatch.sources import registry as sources_registry
from webwatch.sources.base import Observation, Observed, Source

FACTS = load_facts("facts.yaml")


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


# --- prerequisites (Check.requires) ------------------------------------------------


def _check(field: str, requires: str | None = None) -> Check:
    return Check(field, lambda f: f.organization.name, requires=requires)


def test_register_rejects_unknown_prerequisite() -> None:
    with pytest.raises(ValueError, match="unknown check 'nmae'"):
        checks_registry.register("demo", [_check("name"), _check("phone", requires="nmae")])


def test_register_rejects_circular_prerequisites() -> None:
    with pytest.raises(ValueError, match="circular"):
        checks_registry.register("demo", [_check("a", requires="b"), _check("b", requires="a")])


def test_register_rejects_self_prerequisite() -> None:
    with pytest.raises(ValueError, match="circular"):
        checks_registry.register("demo", [_check("a", requires="a")])


def test_gate_runs_each_check_once() -> None:
    calls: list[str] = []

    def expected(field: str) -> Callable[[Facts], str]:
        def _get(facts: Facts) -> str:
            calls.append(field)
            return facts.organization.name

        return _get

    name = Check("name", expected("name"))
    phone = Check("phone", expected("phone"), requires="name")
    observation = Observation("demo", {"name": Observed.found("The Flip")})
    gate = PrerequisiteGate([name, phone], observation, FACTS)
    gate.run(phone)  # evaluates "name" on demand
    gate.run(name)  # reuses that result
    assert calls.count("name") == 1
