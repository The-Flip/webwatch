"""Transition-gated email notification.

Email is built from the run's *transitions* (a check newly failing or recovering),
not from every result — so a persistent problem doesn't spam. It is **safe by
default**: :func:`send` prints instead of delivering when dry-run is on or SMTP
isn't configured, so a misconfiguration or a test never reaches the network.
"""

from __future__ import annotations

import smtplib
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from email.message import EmailMessage

from webwatch import config
from webwatch.result import CheckResult
from webwatch.state import Transition


@dataclass(frozen=True, slots=True)
class EmailContent:
    subject: str
    body: str


def render_email(transitions: list[Transition], results: list[CheckResult]) -> EmailContent | None:
    """Build the notification from this run's transitions, or ``None`` if there are none."""
    if not transitions:
        return None

    by_key = {(r.site, r.name): r for r in results}
    alerts = [t for t in transitions if t.kind == "alert"]
    recoveries = [t for t in transitions if t.kind == "recover"]

    lines: list[str] = []
    if alerts:
        lines.append(f"{len(alerts)} check(s) need attention:")
        for t in alerts:
            result = by_key.get((t.site, t.name))
            detail = (result.detail or result.summary) if result else ""
            suffix = f" — {detail}" if detail else ""
            lines.append(f"  - {t.site}/{t.name} [{t.status.value}]{suffix}")
        lines.append("")
    if recoveries:
        lines.append(f"{len(recoveries)} check(s) recovered:")
        for t in recoveries:
            lines.append(f"  - {t.site}/{t.name} [now {t.status.value}]")
        lines.append("")

    if alerts:
        subject = f"[webwatch] {len(alerts)} problem(s)"
        if recoveries:
            subject += f", {len(recoveries)} recovered"
    else:
        subject = f"[webwatch] {len(recoveries)} recovered"
    return EmailContent(subject, "\n".join(lines).rstrip())


def _recipient_list(recipients: str | Iterable[str]) -> list[str]:
    if isinstance(recipients, str):
        return [r.strip() for r in recipients.split(",") if r.strip()]
    return [r for r in recipients if r]


def send(
    content: EmailContent,
    *,
    dry_run: bool,
    host: str,
    port: int,
    username: str,
    password: str,
    sender: str,
    recipients: str | Iterable[str],
    printer: Callable[[str], None] = print,
) -> bool:
    """Send the email, or print it. Returns ``True`` only if actually delivered.

    Prints (and returns ``False``) when ``dry_run`` is set or SMTP/sender/recipients
    aren't configured — it never reaches the network in those cases.
    """
    to = _recipient_list(recipients)
    configured = bool(host and sender and to)
    if dry_run or not configured:
        reason = "dry-run" if dry_run else "SMTP not configured"
        printer(
            f"[webwatch] email not sent ({reason}):\nSubject: {content.subject}\n\n{content.body}"
        )
        return False

    message = EmailMessage()
    message["Subject"] = content.subject
    message["From"] = sender
    message["To"] = ", ".join(to)
    message.set_content(content.body)

    with smtplib.SMTP(host, port) as server:
        server.starttls()
        if username and password:
            server.login(username, password)
        server.send_message(message)
    return True


def send_from_config(
    content: EmailContent, *, dry_run: bool, printer: Callable[[str], None] = print
) -> bool:
    """:func:`send` wired to the values in :mod:`webwatch.config`."""
    return send(
        content,
        dry_run=dry_run,
        host=config.SMTP_HOST,
        port=config.SMTP_PORT,
        username=config.SMTP_USERNAME,
        password=config.SMTP_PASSWORD,
        sender=config.EMAIL_FROM,
        recipients=config.EMAIL_TO,
        printer=printer,
    )
