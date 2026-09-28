# Operations

How webwatch runs in production: the cron entry, notifications, state, and exit codes.

## Commands

- **`webwatch check`** — run every check, print the report, set the exit code. Side-effect-free
  (no state, no email). Use it interactively or in CI.
- **`webwatch notify`** — the **cron entry point**. Runs the checks, updates run-to-run state, and
  emails when a check _transitions_ (newly fails or recovers). Same exit codes as `check`.
- **`webwatch digest`** — a standing summary of every check still open, read from the saved state
  (it does _not_ re-run checks). Run on a slower cadence than `notify` so persistent problems don't
  fall silent after their one transition email. It ends with a table of checks (rows) by site
  (columns) showing each check's latest status, so an all-clear also shows what was checked. The
  seven daily hours checks share one row, which shows the worst day, and `·` means there's no result
  for that check on that site (it doesn't check it, or hasn't reported it yet). `--only-problems` suppresses the all-clear heartbeat.
  Exits 0 whenever it delivers (even with problems); non-zero only on a tool failure.

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

Use port **587** (STARTTLS) — port 25 is blocked on most hosts. For Gmail app passwords use
`SMTP_HOST=smtp.gmail.com`; leave `SMTP_USERNAME`/`SMTP_PASSWORD` blank to relay without auth (an
IP-allowlisted Workspace relay). `WEBWATCH_SMTP_TIMEOUT` (default 30s) bounds the connection so a
dead port can't hang a cron run.

## Google Places API key (google_maps source)

The `google_maps` source reads Google's Places API (New) and needs `WEBWATCH_GOOGLE_PLACES_API_KEY` in
`.env`. In Google Cloud:

1. Enable billing and **Places API (New)** on the project.
2. Create an API key.
3. Restrict the key to that API.

One run a day uses about 30 Place Details calls a month, well inside Google's free monthly usage. If
the key is unset, every `google_maps` check reports `FETCH_ERROR` (unhealthy, so it alerts), never a
silent skip. The key is sent only in a request header.

**Verify delivery** without waiting for a real problem:

```bash
webwatch notify --test          # prints the test email (dry-run)
webwatch notify --test --send   # actually sends it (needs SMTP configured)
```

A failed send is reported: `notify` warns and retries on the next run (the alert is only marked
notified once a send succeeds, so a transient SMTP outage never silently drops an alarm).

## State

`webwatch notify` persists per-check health to `WEBWATCH_STATE_PATH` (default `state.json`, which is
git-ignored). The file must be writable by the cron user and persist between runs. Deleting it resets
the alert/recovery memory (the next run re-evaluates from scratch).

## Cron

Run `notify` on a schedule. Provide the environment (via `.env` or the crontab) and ensure the
working directory holds `facts.yaml` and the writable `state.json`. **Set `WEBWATCH_EMAIL_DRY_RUN=false`**
— it defaults to `true` (dry-run), so otherwise these jobs only print the email to the log instead of
sending it:

```cron
# Daily at 7am: run checks, update state, email on any change.
0 7 * * *  cd /path/to/webwatch && /path/to/uv run webwatch notify >> /var/log/webwatch.log 2>&1

# Monday at 8am: email a standing summary of anything still open (no re-scrape).
0 8 * * 1  cd /path/to/webwatch && /path/to/uv run webwatch digest >> /var/log/webwatch.log 2>&1
```

`notify` gives immediate on-change alerts; `digest` reminds you of unresolved problems on a slower
cadence. Inspect the latest run by hand any time with `webwatch check`.
