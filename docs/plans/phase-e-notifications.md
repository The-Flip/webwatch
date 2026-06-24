# Phase E — Notifications (transition-gated email) + cron

## Context

webwatch runs all its checks and reports them, but nothing tells anyone when something breaks. The
`state.py` engine already tracks per-check health and computes transitions with anti-flap hysteresis
(built and tested in Phase B). Phase E adds the last mile: a dry-run-able SMTP email that fires on
**state transitions** (a check newly failing, or recovering), and the cron wiring.

The guiding rule (from `docs/copilot-instructions.md` and the master plan): a false alarm costs
trust. Email fires on transitions, not every run; it is dry-run by default; and it never delivers to
a live recipient during testing.

## Design

1. **`webwatch/notify/email.py`**
   - `render_email(transitions, results) -> EmailContent | None`: build a subject + plain-text body
     from the run's transitions (the `Transition` objects from `state.apply_results`), looking up each
     transitioned check's current `CheckResult` for its status/detail. Returns `None` when there are
     no transitions (nothing to send). Lists newly-failing checks (with detail) and recoveries.
   - `send(content, *, dry_run, host, port, username, password, sender, recipients, printer=print)
-> bool`: builds an `email.message.EmailMessage`. **Safe by default:** if `dry_run` is true, or
     SMTP/sender/recipients aren't configured, it _prints_ the email and returns `False` (not sent)
     rather than reaching the network. Otherwise it sends via `smtplib.SMTP` (STARTTLS, optional
     login) and returns `True`. Recipients come from `WEBWATCH_EMAIL_TO` (comma-separated).

2. **CLI: `webwatch notify [--dry-run/--send]`** — the cron entry point.
   - Run the checks (`run_checks`), print the report, then: `load_state` → `apply_results` →
     `save_state`, render the email from the transitions, and `send` it. Exit with `exit_code`.
   - `--dry-run/--send` defaults to `config.EMAIL_DRY_RUN` (which defaults to true). `--send` requires
     SMTP configured; if it isn't, it falls back to printing and warns (never crashes, never silently
     drops). This is the command cron calls.
   - `webwatch check` stays side-effect-free (report + exit only); `notify` owns state + email.

3. **State/order semantics (self-review):** state is saved every run so streak counters advance
   (needed for the anti-flap threshold). A real send failure is caught, printed as a warning, and the
   command still exits with the results' code — but the alert won't automatically re-fire next run (the
   check is already marked alerting). That is a documented limitation; the periodic-digest idea from
   the master plan would mitigate it and is left for later.

4. **Cron + docs** — document the cron entry (`webwatch notify` on a schedule, with `.env` providing
   SMTP + `WEBWATCH_EMAIL_DRY_RUN=false`) and the exit-code contract in `README.md` / a short
   `docs/Operations.md`. Note that `state.json` persists between runs and must be writable by cron.

## Testing (`tests/test_notify.py`, extend `tests/test_cli.py`)

- `render_email`: an alert transition → content whose subject/body name the check and its detail; a
  recovery → a "recovered" line; no transitions → `None`.
- `send`: `dry_run=True` → the injected `printer` is called and it returns `False` (nothing sent);
  unconfigured SMTP → also prints, returns `False`; `dry_run=False` with config → `smtplib.SMTP`
  (monkeypatched) receives a `send_message` with the right From/To/Subject, returns `True`.
- `notify` CLI (hermetic): `run_checks` monkeypatched and `config.STATE_PATH` pointed at `tmp_path`,
  `config.ALERT_AFTER_FAILURES=1`. A first run with a MISMATCH writes state and (dry-run) prints an
  email; a second identical run produces no new transition (already alerting) → no email. A recovery
  run prints a recovery email. Assert state.json is written under tmp_path and no real send happens.
- Safety: a test asserts that with `dry_run` defaulting from config, the default `notify` never calls
  `smtplib.SMTP`.

## Verification

- `make quality` and `make test` green.
- `webwatch notify --dry-run` prints the report and, when a check has transitioned, the email body —
  without sending. With the current all-OK site there are no transitions, so it prints "no
  notifications to send."
- Seeding a `state.json` that marks the repair-day rule as previously OK, then running against a
  fixture where it fails, prints an alert email (dry-run).

## Review status (agy unavailable — self-review applied)

`agy` is returning HTTP 429 ("model API overloaded") right now, so an independent review is **owed**
for this plan (and the Phase D plan and the event-time-range fix) once the service recovers:
`make review-plan PLAN=docs/plans/phase-e-notifications.md`. Self-review folded in: the safe-by-default
send (dry-run + unconfigured-SMTP both print, never reach the network), the save-then-send ordering
limitation, and keeping `check` side-effect-free while `notify` owns state/email.
