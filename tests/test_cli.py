"""Tests for the CLI wiring: argument parsing, rendering, and exit codes.

``check`` is exercised with ``run_checks`` monkeypatched, so these stay hermetic
(no network) and focus on the CLI's own behavior. End-to-end runs over a fixture
transport live in test_run.py.
"""

from __future__ import annotations

import pytest
from click.testing import CliRunner

from webwatch import __version__
from webwatch import cli as cli_module
from webwatch.cli import cli
from webwatch.result import EXIT_DATA_PROBLEM, EXIT_OK, CheckResult


def test_version() -> None:
    result = CliRunner().invoke(cli, ["--version"])
    assert result.exit_code == 0
    assert __version__ in result.output


def test_help_lists_commands() -> None:
    result = CliRunner().invoke(cli, ["--help"])
    assert result.exit_code == 0
    for command in ("check", "list", "facts"):
        assert command in result.output


def test_check_all_ok_exits_zero(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        cli_module,
        "run_checks",
        lambda *a, **k: [CheckResult.ok("s", "name", expected="x", observed="x")],
    )
    result = CliRunner().invoke(cli, ["check"])
    assert result.exit_code == EXIT_OK
    assert "1 checks" in result.output


def test_check_mismatch_exits_one(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        cli_module,
        "run_checks",
        lambda *a, **k: [CheckResult.mismatch("s", "hours", expected="9-5", observed="10-6")],
    )
    result = CliRunner().invoke(cli, ["check"])
    assert result.exit_code == EXIT_DATA_PROBLEM
    assert "mismatch" in result.output


def test_check_json_format(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        cli_module,
        "run_checks",
        lambda *a, **k: [CheckResult.ok("s", "name", expected="x", observed="x")],
    )
    result = CliRunner().invoke(cli, ["check", "--format", "json"])
    assert result.exit_code == EXIT_OK
    assert '"status": "ok"' in result.output


def test_list_shows_theflip_museum() -> None:
    result = CliRunner().invoke(cli, ["list"])
    assert result.exit_code == 0
    assert "theflip_museum" in result.output
    assert "address.street" in result.output


def test_facts_validate() -> None:
    result = CliRunner().invoke(cli, ["facts", "--validate"])
    assert result.exit_code == 0
    assert "valid" in result.output


def test_facts_show() -> None:
    result = CliRunner().invoke(cli, ["facts"])
    assert result.exit_code == 0
    assert "Organization: The Flip" in result.output
    assert "Rules:" in result.output
