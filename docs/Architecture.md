# Architecture

Webwatch is a small Python CLI that checks the places The Flip appears on the web and reports when published information is wrong or out of sync. It runs from cron. There is no web server and no database; the only persistent state is a small JSON file used to avoid alert spam.

## Components

- **`webwatch.config`** — Loads configuration and secrets from the environment (via `python-decouple`). The single place that reads `os.environ`. Everything else imports typed values from here.
- **`webwatch.fetch`** — The one HTTP boundary. Wraps `httpx` with a descriptive User-Agent, timeout, retry/backoff for transient errors, and a per-domain politeness delay. All network access goes through here so it is uniform and easy to mock.
- **`webwatch.extract`** — Robust extraction primitives, independent of any one site:
  - `structured.py` — pulls JSON-LD / schema.org / microdata via `extruct`.
  - `anchors.py` — locates values by stable semantic anchors (label text, microformats, roles).
- **`webwatch.sources`** — One module per site. A `Source` fetches its page **once** and returns a typed `Observation` (the facts it could read, each tagged with how confidently). Sources own the site-specific knowledge: which URL, which anchors, how to read each field.
- **`webwatch.normalize`** — Canonicalizes values (whitespace, phone formats, street abbreviations, hours/timezone) so comparison is semantic, not literal.
- **`webwatch.checks`** — Assertions. Given a `Source`'s `Observation` and the canonical `facts.yaml`/rules, each check produces a `CheckResult`. This is where "matches / differs / couldn't read" is decided.
- **`webwatch.facts` / `webwatch.rules`** — Load and validate `facts.yaml`; evaluate dynamic rules (e.g. recurring events) against a clock that is injected for testability.
- **`webwatch.result`** — `CheckStatus` and `CheckResult`: the core abstraction (see [Extraction.md](Extraction.md)).
- **`webwatch.state`** — Loads/saves run-to-run state (last status, consecutive-failure counts) so notifications can fire on transitions instead of every run.
- **`webwatch.report`** — Renders the per-check report (text or JSON) and builds the email body.
- **`webwatch.notify`** — Sends the problem email over SMTP; dry-run by default.
- **`webwatch.cli`** — The `webwatch` command that wires it together.

## Data flow

```text
facts.yaml ─┐
            ▼
config ─▶ fetch(httpx) ─▶ Source.fetch() ─▶ Observation ─▶ checks ─▶ CheckResult[]
                              ▲                                            │
                          extract/                                        ▼
                      (structured + anchors)            state (transition?) ─▶ report ─▶ notify (email)
                                                                             │
                                                                             ▼
                                                                       exit code (0/1/2)
```

## Design principles

- **One boundary to the outside world.** Every fetch goes through `fetch.py`; every site's quirks live in its `sources/` module. This keeps the core testable (mock the transport) and the failure handling uniform.
- **Fetch once, then assert.** A page is fetched a single time into an `Observation`; checks compare fields of that observation to facts. Checks never fetch.
- **Honest degradation.** Extraction reports _that it failed to read_ (`STRUCTURE_CHANGED` / `PARSE_ERROR` / `BLOCKED`) rather than guessing. The only status that claims the world is wrong is `MISMATCH`, and only when a value was genuinely read. See [Extraction.md](Extraction.md).
- **Structured data corroborates; it does not decide.** JSON-LD is convenient but often stale. Visible text is authoritative.
- **Quiet until something changes.** Alerts fire on state transitions after a small consecutive-failure threshold, so a transient blip or a long-known issue doesn't spam.
- **Fail fast.** Surface specific exceptions with useful context rather than returning `None`.

## What this project is _not_

- Not a Django app, not a web server, not a database project. (That's `../flipfix`.)
- Not a general-purpose crawler. It checks a known, curated set of pages for known facts.
- Not the system of record for the museum's details — `facts.yaml` is, and a human maintains it.
