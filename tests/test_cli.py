"""Tests for the CLI wiring: argument parsing, rendering, and exit codes.

``check`` is exercised with ``run_checks`` monkeypatched, so these stay hermetic
(no network) and focus on the CLI's own behavior. End-to-end runs over a fixture
transport live in test_run.py.
"""

from __future__ import annotations

import smtplib

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


# --- notify (cron entry point) ------------------------------------------------


def _seed_notify(monkeypatch: pytest.MonkeyPatch, tmp_path, result: CheckResult) -> None:
    """Point notify at a temp state file, alert after one failure, never hit SMTP."""
    monkeypatch.setattr(cli_module, "run_checks", lambda *a, **k: [result])
    monkeypatch.setattr("webwatch.config.STATE_PATH", str(tmp_path / "state.json"))
    monkeypatch.setattr("webwatch.config.ALERT_AFTER_FAILURES", 1)
    monkeypatch.setattr("webwatch.config.EMAIL_DRY_RUN", True)
    monkeypatch.setattr("webwatch.notify.email.smtplib.SMTP", _explode)


def _explode(*_a: object, **_k: object) -> object:
    raise AssertionError("default notify must never contact SMTP")


def test_notify_alerts_on_first_failure_then_quiet(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    mismatch = CheckResult.mismatch("s", "hours", expected="9-5", observed="10-6")
    _seed_notify(monkeypatch, tmp_path, mismatch)

    first = CliRunner().invoke(cli, ["notify"])
    assert first.exit_code == EXIT_DATA_PROBLEM
    assert "dry-run" in first.output and "s/hours" in first.output
    assert (tmp_path / "state.json").exists()

    # Second identical run: already alerting, so no new transition -> no email.
    second = CliRunner().invoke(cli, ["notify"])
    assert "No notifications to send" in second.output


def test_notify_no_transitions_when_all_ok(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    ok = CheckResult.ok("s", "hours", expected=1, observed=1)
    _seed_notify(monkeypatch, tmp_path, ok)
    result = CliRunner().invoke(cli, ["notify"])
    assert result.exit_code == EXIT_OK
    assert "No notifications to send" in result.output


@pytest.mark.parametrize("error", [smtplib.SMTPException("smtp down"), OSError("dns fail")])
def test_notify_retries_when_send_fails(
    monkeypatch: pytest.MonkeyPatch, tmp_path, error: Exception
) -> None:
    """A failed send is caught (no crash) and re-fires next run — no dropped alarm."""
    mismatch = CheckResult.mismatch("s", "hours", expected="9-5", observed="10-6")
    monkeypatch.setattr(cli_module, "run_checks", lambda *a, **k: [mismatch])
    monkeypatch.setattr("webwatch.config.STATE_PATH", str(tmp_path / "state.json"))
    monkeypatch.setattr("webwatch.config.ALERT_AFTER_FAILURES", 1)

    def boom(*_a: object, **_k: object) -> bool:
        raise error

    monkeypatch.setattr(cli_module, "send_from_config", boom)

    first = CliRunner().invoke(cli, ["notify", "--send"])
    assert first.exit_code == EXIT_DATA_PROBLEM
    assert "failed to send" in first.output  # caught, not a traceback

    # The alert wasn't recorded as notified, so it re-fires (and re-fails) next run.
    second = CliRunner().invoke(cli, ["notify", "--send"])
    assert "failed to send" in second.output
