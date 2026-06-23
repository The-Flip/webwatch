"""Load and validate ``facts.yaml`` — webwatch's canonical source of truth.

Returns a typed :class:`Facts` structure. Malformed *shape* fails loudly with
:class:`FactsError`; *empty* values are allowed and meaningful — a blank static
fact or a disabled rule means "not verified / don't check this", which checks map
to ``SKIPPED`` rather than asserting against a blank. See ``docs/Facts.md``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from webwatch import config


class FactsError(Exception):
    """``facts.yaml`` is missing or structurally invalid."""


@dataclass(frozen=True, slots=True)
class Address:
    street: str = ""
    city: str = ""
    region: str = ""
    postal_code: str = ""
    country: str = ""


@dataclass(frozen=True, slots=True)
class Organization:
    name: str = ""
    url: str = ""
    address: Address = field(default_factory=Address)
    phone: str = ""
    email: str = ""
    #: weekday name -> raw hours value ("closed", a window dict, or a list of them)
    hours: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class Rule:
    id: str
    type: str
    description: str = ""
    enabled: bool = True
    #: type-specific fields (everything besides id/type/description/enabled)
    params: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class Facts:
    organization: Organization = field(default_factory=Organization)
    rules: tuple[Rule, ...] = ()


_RULE_RESERVED = {"id", "type", "description", "enabled"}


def is_blank(value: Any) -> bool:
    """True if a fact value is unset and a check should be ``SKIPPED``."""
    if value is None:
        return True
    if isinstance(value, str):
        return value.strip() == ""
    if isinstance(value, dict | list | tuple):
        return len(value) == 0
    return False


def _require_mapping(value: Any, where: str) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise FactsError(f"{where} must be a mapping, got {type(value).__name__}")
    return value


def _parse_address(data: Any) -> Address:
    mapping = _require_mapping(data, "organization.address")
    return Address(
        street=str(mapping.get("street", "")),
        city=str(mapping.get("city", "")),
        region=str(mapping.get("region", "")),
        postal_code=str(mapping.get("postal_code", "")),
        country=str(mapping.get("country", "")),
    )


def _parse_organization(data: Any) -> Organization:
    mapping = _require_mapping(data, "organization")
    return Organization(
        name=str(mapping.get("name", "")),
        url=str(mapping.get("url", "")),
        address=_parse_address(mapping.get("address")),
        phone=str(mapping.get("phone", "")),
        email=str(mapping.get("email", "")),
        hours=_require_mapping(mapping.get("hours"), "organization.hours"),
    )


def _parse_rule(data: Any, index: int) -> Rule:
    mapping = _require_mapping(data, f"rules[{index}]")
    if "id" not in mapping or "type" not in mapping:
        raise FactsError(f"rules[{index}] must have 'id' and 'type'")
    params = {k: v for k, v in mapping.items() if k not in _RULE_RESERVED}
    return Rule(
        id=str(mapping["id"]),
        type=str(mapping["type"]),
        description=str(mapping.get("description", "")),
        enabled=bool(mapping.get("enabled", True)),
        params=params,
    )


def parse_facts(data: Any) -> Facts:
    """Build :class:`Facts` from already-loaded YAML data (no I/O)."""
    top = _require_mapping(data, "facts")
    rules_data = top.get("rules") or []
    if not isinstance(rules_data, list):
        raise FactsError("rules must be a list")
    rules = tuple(_parse_rule(rule, i) for i, rule in enumerate(rules_data))
    return Facts(organization=_parse_organization(top.get("organization")), rules=rules)


def load_facts(path: str | Path | None = None) -> Facts:
    """Load, parse, and validate ``facts.yaml`` from ``path`` (default from config)."""
    facts_path = Path(path) if path is not None else Path(config.FACTS_PATH)
    if not facts_path.exists():
        raise FactsError(f"facts file not found: {facts_path}")
    try:
        data = yaml.safe_load(facts_path.read_text(encoding="utf-8"))
    except yaml.YAMLError as err:
        raise FactsError(f"could not parse {facts_path}: {err}") from err
    return parse_facts(data)
