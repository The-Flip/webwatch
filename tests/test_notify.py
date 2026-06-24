"""Tests for email rendering and the safe-by-default send path."""

from __future__ import annotations

from typing import ClassVar

import pytest

import webwatch.notify.email as mail
from webwatch.notify.email import EmailContent, render_digest, render_email, send
from webwatch.result import CheckResult, CheckStatus
from webwatch.state import Transition


def _alert(name: str = "hours") -> Transition:
    return Transition("site", name, "alert", CheckStatus.MISMATCH)


def _recover(name: str = "hours") -> Transition:
    return Transition("site", name, "recover", CheckStatus.OK)


def test_render_email_none_without_transitions() -> None:
    assert render_email([], []) is None


def test_render_email_alert_names_check_and_detail() -> None:
    results = [CheckResult.mismatch("site", "hours", expected="9-5", observed="10-6")]
    content = render_email([_alert()], results)
    assert content is not None
    assert "1 problem" in content.subject
    assert "site/hours" in content.body
    assert "differs" in content.body  # the mismatch summary/detail


def test_render_email_recovery_only() -> None:
    content = render_email([_recover()], [CheckResult.ok("site", "hours", expected=1, observed=1)])
    assert content is not None
    assert "recovered" in content.subject
    assert "recovered" in content.body


def test_render_digest_lists_open_problems() -> None:
    content = render_digest([("site", "hours", "mismatch"), ("site", "addr", "blocked")], total=5)
    assert "2 open problem" in content.subject
    assert "site/hours [mismatch]" in content.body
    assert "site/addr [blocked]" in content.body


def test_render_digest_all_clear() -> None:
    content = render_digest([], total=5)
    assert "all clear" in content.subject
    assert "all 5" in content.body


# --- send: safe by default ----------------------------------------------------


class _FakeSMTP:
    instances: ClassVar[list[_FakeSMTP]] = []

    def __init__(self, host: str, port: int, timeout: float | None = None) -> None:
        self.host, self.port, self.timeout = host, port, timeout
        self.started = False
        self.logged: tuple[str, str] | None = None
        self.sent: list[object] = []
        _FakeSMTP.instances.append(self)

    def __enter__(self) -> _FakeSMTP:
        return self

    def __exit__(self, *_a: object) -> bool:
        return False

    def starttls(self) -> None:
        self.started = True

    def login(self, user: str, password: str) -> None:
        self.logged = (user, password)

    def send_message(self, message: object) -> None:
        self.sent.append(message)


def test_send_dry_run_prints_and_does_not_deliver(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(mail.smtplib, "SMTP", _never_smtp)
    printed: list[str] = []
    sent = send(
        EmailContent("subj", "body"),
        dry_run=True,
        host="smtp.test",
        port=587,
        username="u",
        password="p",
        sender="from@x",
        recipients="to@x",
        printer=printed.append,
    )
    assert sent is False
    assert printed and "dry-run" in printed[0]


def test_dry_run_with_configured_smtp_warns(monkeypatch: pytest.MonkeyPatch) -> None:
    """SMTP configured but dry-run on is easy to miss in cron — warn visibly (agy review)."""
    monkeypatch.setattr(mail.smtplib, "SMTP", _never_smtp)
    printed: list[str] = []
    send(
        EmailContent("s", "b"),
        dry_run=True,
        host="smtp.test",
        port=587,
        username="u",
        password="p",
        sender="from@x",
        recipients="to@x",
        printer=printed.append,
    )
    assert any("WARNING" in line and "dry-run" in line for line in printed)


def test_send_unconfigured_prints_and_does_not_deliver(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(mail.smtplib, "SMTP", _never_smtp)
    printed: list[str] = []
    sent = send(
        EmailContent("s", "b"),
        dry_run=False,
        host="",  # not configured
        port=587,
        username="",
        password="",
        sender="",
        recipients="",
        printer=printed.append,
    )
    assert sent is False
    assert printed and "not configured" in printed[0]


def test_send_delivers_when_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    _FakeSMTP.instances.clear()
    monkeypatch.setattr(mail.smtplib, "SMTP", _FakeSMTP)
    sent = send(
        EmailContent("subj", "body"),
        dry_run=False,
        host="smtp.test",
        port=587,
        username="u",
        password="p",
        sender="from@x",
        recipients="a@x, b@x",
        timeout=12.0,
    )
    assert sent is True
    smtp = _FakeSMTP.instances[-1]
    assert smtp.started and smtp.logged == ("u", "p")
    assert smtp.timeout == 12.0  # a timeout is always passed so a dead port can't hang
    message = smtp.sent[0]
    assert message["Subject"] == "subj"  # type: ignore[index]
    assert message["From"] == "from@x"  # type: ignore[index]
    assert "a@x" in message["To"] and "b@x" in message["To"]  # type: ignore[index]


def _never_smtp(*_a: object, **_k: object) -> object:
    raise AssertionError("SMTP must not be contacted for a dry-run or unconfigured send")
