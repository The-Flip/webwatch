"""Configuration and secrets, read from the environment.

This module is the *only* place that reads environment variables. Everything
else imports the typed values from here. Values come from the process
environment or a local ``.env`` file (see ``.env.example``), via
``python-decouple``.
"""

from __future__ import annotations

from decouple import config

# --- HTTP fetching ---

#: How we identify ourselves to the sites we check. Include a contact URL so a
#: site owner who sees us in their logs knows who we are and why.
USER_AGENT: str = config(
    "WEBWATCH_USER_AGENT",
    default="webwatch/0.1 (+https://www.theflip.museum/; monitoring our own listings)",
)

#: Per-request timeout, in seconds.
HTTP_TIMEOUT: float = config("WEBWATCH_HTTP_TIMEOUT", default=30, cast=float)

#: How many times to retry transient failures (429 / 5xx) before giving up.
HTTP_MAX_RETRIES: int = config("WEBWATCH_HTTP_MAX_RETRIES", default=3, cast=int)

#: Minimum delay (seconds) between requests to the same domain — basic politeness
#: so we don't hammer a host while checking several facts on it.
HTTP_DOMAIN_DELAY: float = config("WEBWATCH_HTTP_DOMAIN_DELAY", default=1.0, cast=float)

# --- Facts & state ---

#: The museum's local timezone — "midnight of the day an event ends" is local midnight.
TIMEZONE: str = config("WEBWATCH_TIMEZONE", default="America/Chicago")

#: Path to the canonical expected facts and dynamic rules.
FACTS_PATH: str = config("WEBWATCH_FACTS_PATH", default="facts.yaml")

#: Path where run-to-run check state is persisted (alert-on-transition / anti-flap).
STATE_PATH: str = config("WEBWATCH_STATE_PATH", default="state.json")

#: A check must fail this many consecutive runs before it alerts (absorbs blips).
ALERT_AFTER_FAILURES: int = config("WEBWATCH_ALERT_AFTER_FAILURES", default=2, cast=int)

#: A check must be healthy this many consecutive runs before a fired alert clears.
RECOVER_AFTER_SUCCESSES: int = config("WEBWATCH_RECOVER_AFTER_SUCCESSES", default=1, cast=int)

# --- Email notification (transactional SMTP) ---

#: When true, emails are printed instead of sent. Defaults to true so nothing is
#: ever delivered by accident; flip it off explicitly in production.
EMAIL_DRY_RUN: bool = config("WEBWATCH_EMAIL_DRY_RUN", default=True, cast=bool)

SMTP_HOST: str = config("SMTP_HOST", default="")
SMTP_PORT: int = config("SMTP_PORT", default=587, cast=int)
SMTP_USERNAME: str = config("SMTP_USERNAME", default="")
SMTP_PASSWORD: str = config("SMTP_PASSWORD", default="")
EMAIL_FROM: str = config("WEBWATCH_EMAIL_FROM", default="")
EMAIL_TO: str = config("WEBWATCH_EMAIL_TO", default="")
