# Periodic status digest

## Context

`webwatch notify` emails on _transitions_ — a check fires once when it newly fails and once when it
recovers. That is right for avoiding spam, but it leaves a gap: a problem that persists for weeks is
announced only once, then goes quiet. An operator who missed (or forgot) that first email has no
recurring reminder that something is still wrong. This was recorded as the one known limitation of
the notification system.

The fix is a **periodic digest**: a separate, scheduled email that summarizes the _current_ status —
every open problem right now — regardless of transitions. Run daily `notify` for immediate alerts;
run `digest` weekly for a standing "here's everything still broken (or all-clear)" summary.

## Design (revised after the agy review — reads state, does not re-scrape)

1. **The digest reads `state.json`; it does not run checks (agy #1, #2).** The original idea was a
   fresh scrape, but that would bypass the anti-flap threshold — a transient glitch at digest time
   would be reported as an "open problem" (alert fatigue), and it would double the scraping (bot-
   detection risk). Instead the digest reports the _persistent_ state: the checks `notify` has
   recorded as `alerting = True` (i.e. they crossed `ALERT_AFTER_FAILURES`). This is fast, needs no
   network, and shows exactly the still-open problems. `notify` (daily) keeps the state current;
   `digest` (weekly) summarizes it.

2. **`webwatch/state.py` — `alerting_checks(state) -> list[(site, name, status)]`.** A small helper
   (state owns the key format) returning the currently-alerting checks, worst-first.

3. **`webwatch/notify/email.py` — `render_digest(open_problems, total) -> EmailContent`.** Always
   returns content (a snapshot):
   - open problems → subject `"[webwatch] status digest: N open problem(s)"`; body lists each
     `site/name [status]`.
   - none → subject `"[webwatch] status digest: all clear"`; body notes all `total` checks healthy.
     Takes a plain list + count, so email.py stays decoupled from `State` internals.

4. **`webwatch digest [--dry-run/--send] [--only-problems]` CLI command.** Loads state (read-only —
   no scrape, no write), computes the open problems, renders the digest, and sends it (reusing
   `send_from_config`, same safe-by-default dry-run as `notify`).
   - **Exit code (agy #3):** exits `0` on successful execution **even when problems are listed** —
     the digest's job is to deliver the summary, and a non-zero exit would make cron send its own
     duplicate error mail. Non-zero is reserved for _tool_ failures (bad facts/config load, or a send
     that raised). So `digest` does **not** use `exit_code(results)`.
   - **`--only-problems` (agy #4):** suppress the "all clear" heartbeat — if there are no open
     problems, print a line and send nothing. Default sends the all-clear (a useful "monitor alive"
     signal).
   - **Stateless w.r.t. mutation:** `digest` never writes `state.json`; `notify` remains the only
     command that mutates state.

5. **Docs.** `docs/Operations.md` + README get the `digest` command and a weekly cron line, and spell
   out the division of labor: `notify` = on-change alerts (daily, writes state); `digest` = standing
   status from that state (weekly, read-only).

## Testing (`tests/test_notify.py`, `tests/test_cli.py`, `tests/test_state.py`)

- `state.alerting_checks`: returns only the `alerting=True` checks with their `(site, name, status)`.
- `render_digest`: a non-empty open list → subject "N open problem(s)" and each problem named; empty
  → "all clear" with the total. (Pure function.)
- `digest` CLI (hermetic; `config.STATE_PATH` → a `tmp_path` seeded via `save_state`): a state with an
  alerting check, dry-run → prints the digest naming it, **exit 0**, no SMTP contact, and
  `state.json` is unchanged (no write). An all-OK state → "all clear"; with `--only-problems` →
  "nothing to send" and no email. A `--send` path with `send_from_config` raising → clean error
  (non-zero), not a traceback. A run with no checks ever recorded (empty state) → all clear.

## Verification

- `make quality` / `make test` green.
- `webwatch digest` (dry-run) prints the digest from the recorded state — "all clear" when nothing is
  alerting, and the open problems when some are.

## Out of scope

- A `--refresh` flag to scrape fresh before digesting (agy noted it as the place for a fresh run):
  deferred — reading state is the right default and covers the use case; revisit if wanted.
- Auto-cadence inside `notify` (tracking "days since last digest"): a separate command on its own
  cron schedule is simpler and explicit.

## Review feedback incorporated (agy)

`agy` reviewed the plan; all four findings folded in (the design changed materially as a result):

- **#1 (High) / #2 (Medium):** the digest now reads `state.json` and reports persistently-`alerting`
  checks instead of running a fresh stateless scrape — so it respects the anti-flap threshold (no
  transient-glitch fatigue) and adds no network load / bot-detection risk.
- **#3 (Medium):** `digest` exits `0` even when problems are listed (non-zero only for tool failures),
  so cron doesn't send a duplicate error mail alongside the digest.
- **#4 (Low):** added `--only-problems` to suppress the all-clear heartbeat.
