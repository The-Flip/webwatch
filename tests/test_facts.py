"""Tests for loading and validating facts.yaml."""

from __future__ import annotations

import pytest

from webwatch import facts
from webwatch.facts import FactsError, is_blank, load_facts, parse_facts


def test_parse_minimal_organization() -> None:
    data = {
        "organization": {
            "name": "The Flip",
            "address": {"street": "123 Main St", "city": "Springfield"},
            "hours": {"saturday": {"open": "10:00", "close": "17:00"}},
        }
    }
    result = parse_facts(data)
    assert result.organization.name == "The Flip"
    assert result.organization.address.street == "123 Main St"
    assert result.organization.hours["saturday"] == {"open": "10:00", "close": "17:00"}


def test_parse_rules_separates_params() -> None:
    data = {
        "rules": [
            {
                "id": "weekly-repair-day",
                "type": "recurring_event",
                "description": "Repair day",
                "enabled": False,
                "frequency": "weekly",
                "weekday": "saturday",
            }
        ]
    }
    (rule,) = parse_facts(data).rules
    assert rule.id == "weekly-repair-day"
    assert rule.enabled is False
    assert rule.params == {"frequency": "weekly", "weekday": "saturday"}


def test_rule_requires_id_and_type() -> None:
    with pytest.raises(FactsError):
        parse_facts({"rules": [{"description": "no id or type"}]})


def test_bad_top_level_shape_raises() -> None:
    with pytest.raises(FactsError):
        parse_facts([1, 2, 3])  # not a mapping


@pytest.mark.parametrize("value", ["", "   ", None, {}, []])
def test_is_blank_true(value: object) -> None:
    assert is_blank(value)


@pytest.mark.parametrize("value", ["x", {"a": 1}, ["a"], 0])
def test_is_blank_false(value: object) -> None:
    assert not is_blank(value)


def test_load_missing_file_raises() -> None:
    with pytest.raises(FactsError):
        load_facts("/nonexistent/facts.yaml")


def test_load_real_facts_template(tmp_path) -> None:
    path = tmp_path / "facts.yaml"
    path.write_text("organization:\n  name: The Flip\nrules: []\n", encoding="utf-8")
    result = load_facts(path)
    assert result.organization.name == "The Flip"
    assert result.rules == ()


def test_repo_facts_yaml_parses() -> None:
    """The committed facts.yaml template must always be valid."""
    result = load_facts("facts.yaml")
    assert result.organization.name == "The Flip"
    assert any(rule.id == "weekly-repair-day" for rule in result.rules)


def test_module_exposes_dataclasses() -> None:
    assert facts.Address().street == ""


def test_listing_names_parse_as_a_tuple() -> None:
    parsed = parse_facts(
        {"organization": {"name": "The Flip", "listing_names": ["The Flip Museum"]}}
    )
    assert parsed.organization.listing_names == ("The Flip Museum",)


def test_listing_names_default_to_empty() -> None:
    assert parse_facts({"organization": {"name": "The Flip"}}).organization.listing_names == ()


@pytest.mark.parametrize("bad", ["The Flip Museum", [1, 2], {"a": "b"}])
def test_listing_names_must_be_a_list_of_strings(bad: object) -> None:
    with pytest.raises(FactsError, match="listing_names"):
        parse_facts({"organization": {"listing_names": bad}})


def test_listing_names_require_a_name() -> None:
    with pytest.raises(FactsError, match=r"requires organization\.name"):
        parse_facts({"organization": {"name": "", "listing_names": ["The Flip Museum"]}})
