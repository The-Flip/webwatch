"""Smoke tests for the CLI scaffold.

These confirm the command surface is wired up and exit codes behave. Real check
dispatch is added in a later phase; until then ``check`` finds nothing to do and
exits 0.
"""

from __future__ import annotations

from click.testing import CliRunner

from webwatch import __version__
from webwatch.cli import cli
from webwatch.result import EXIT_OK


def test_version() -> None:
    result = CliRunner().invoke(cli, ["--version"])
    assert result.exit_code == 0
    assert __version__ in result.output


def test_help_lists_commands() -> None:
    result = CliRunner().invoke(cli, ["--help"])
    assert result.exit_code == 0
    for command in ("check", "list", "facts", "notify"):
        assert command in result.output


def test_check_with_no_registered_checks_exits_ok() -> None:
    result = CliRunner().invoke(cli, ["check", "--all"])
    assert result.exit_code == EXIT_OK
    assert "No checks registered" in result.output


def test_list_runs() -> None:
    result = CliRunner().invoke(cli, ["list"])
    assert result.exit_code == 0
