# Operations

How webwatch runs in production: the cron entry, notifications, state, and exit codes.

## Commands

- **`webwatch check`** — run every check, print the report, set the exit code. Side-effect-free
  (no state, no email). Use it interactively or in CI.
- **`webwatch notify`** — the **cron entry point**. Runs the checks, updates run-to-run state, and
  emails when a check _transitions_ (newly fails or recovers). Same exit codes as `check`.

## Exit codes

| Code | Meaning                                                                                                                                            |
| ---- | -------------------------------------------------------------------------------------------------------------------------------------------------- |
| 0    | All checks OK (or skipped).                                                                                                                        |
| 1    | At least one `MISMATCH` — published information is genuinely out of sync.                                                                          |
| 2    | At least one checker condition (`STRUCTURE_CHANGED` / `PARSE_ERROR` / `BLOCKED` / `FETCH_ERROR` / `METADATA_DRIFT`) — our checker needs attention. |

A confirmed data discrepancy (1) takes precedence over a checker condition (2). Cron wrappers can
route the two differently.

## Notifications

Email fires on **state transitions**, not every run — a known problem that persists does not spam.
A check must be unhealthy for `WEBWATCH_ALERT_AFTER_FAILURES` consecutive runs before it alerts, and
healthy for `WEBWATCH_RECOVER_AFTER_SUCCESSES` runs before the alert clears (anti-flap). See
[`webwatch/state.py`](../webwatch/state.py).

**Safe by default.** `webwatch notify` is dry-run unless told otherwise (`WEBWATCH_EMAIL_DRY_RUN`
defaults to `true`, and `--send` is required to deliver). When dry-run is on — or SMTP isn't fully
configured — the email is _printed_, never sent. To actually deliver, configure SMTP in `.env` and
set `WEBWATCH_EMAIL_DRY_RUN=false` (or pass `--send`):

```bash
# .env
SMTP_HOST=smtp.example.org
SMTP_PORT=587
SMTP_USERNAME=...
SMTP_PASSWORD=...
WEBWATCH_EMAIL_FROM=webwatch@theflip.museum
WEBWATCH_EMAIL_TO=ops@theflip.museum,curator@theflip.museum
WEBWATCH_EMAIL_DRY_RUN=false
```

> Known limitation: state is saved each run (so streak counters advance). If a real send fails, the
> error is logged and the run still exits with its result code, but that alert won't automatically
> re-fire (the check is already marked alerting). A periodic digest of still-open problems would
> mitigate this and is left for later.

## State

`webwatch notify` persists per-check health to `WEBWATCH_STATE_PATH` (default `state.json`, which is
git-ignored). The file must be writable by the cron user and persist between runs. Deleting it resets
the alert/recovery memory (the next run re-evaluates from scratch).

## Cron

Run `notify` on a schedule. Provide the environment (via `.env` or the crontab) and ensure the
working directory holds `facts.yaml` and the writable `state.json`:

```cron
# Check every morning at 7am; email fires only on transitions.
0 7 * * *  cd /path/to/webwatch && /path/to/uv run webwatch notify >> /var/log/webwatch.log 2>&1
```

Inspect the latest run by hand any time with `webwatch check`.
