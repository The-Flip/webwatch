# Webwatch — Monitoring The Flip's Web Presence

Webwatch checks the places [The Flip](https://www.theflip.museum/) pinball museum appears on the
web — its own site first, and map/listing/event sites over time — and reports when published
information is wrong or out of sync. It verifies both static facts (address, hours) and dynamic
ones (upcoming events, recurring volunteer days).

It is a sibling of [`flipfix`](../flipfix) (the museum's maintenance-tracking app) and
[`mailbox`](../mailbox) (mailing-list management), and deliberately mirrors their tooling and
conventions.

## What makes it trustworthy

Scrapers break when pages change. Webwatch is built so that a broken page is **reported as broken**
rather than silently producing a wrong answer. Every check returns one of:

- `OK` — value found and matches the expected fact
- `MISMATCH` — value found but differs → the published info is genuinely out of sync
- `STRUCTURE_CHANGED` — the data couldn't be located → the page changed; needs human review
- `PARSE_ERROR` — the data was located but is unparseable → needs human review
- `BLOCKED` — a CAPTCHA / challenge / login wall / JS-only shell → an access problem, not a layout bug
- `FETCH_ERROR` — the page couldn't be fetched

The distinction between "the value is wrong" and "I can no longer read this page" is the whole
point — it prevents both false alarms and silent misses. See
[docs/Extraction.md](docs/Extraction.md).

## Requirements

- Python 3.14+
- [`uv`](https://docs.astral.sh/uv/) for dependency and environment management

## Setup

```bash
make bootstrap
```

This syncs dependencies with `uv`, installs pre-commit hooks, and creates `.env` from
`.env.example`. Then edit `.env` to configure SMTP (for email alerts) and runtime options.

## Common commands

```bash
make test        # Fast test suite (hermetic — no network)
make quality     # Format, lint, typecheck
make check       # Run all checks against live sites
make test-all    # Full suite including @integration tests (live network)
```

## CLI

Webwatch ships a `webwatch` command. `make bootstrap` (or `uv sync`) installs it into the project
venv, so `uv run webwatch …` works immediately. To type plain `webwatch` from anywhere:

```bash
uv tool install --editable .   # adds `webwatch` to ~/.local/bin (editable: tracks the source)
```

```bash
webwatch --help
webwatch check --all                 # run every check, print a report, set the exit code
webwatch check --site theflip_museum # just one site
webwatch list                        # list registered sites and checks
webwatch facts --validate            # show / validate the loaded facts.yaml + rules
webwatch notify --dry-run            # run, update state, and preview the email (no send)
webwatch notify --test --send        # send a one-off test email to verify SMTP
webwatch digest --dry-run            # preview a summary of all still-open problems (from saved state)
```

Exit codes: `0` all OK · `1` at least one `MISMATCH` (data out of sync) · `2` at least one checker
condition (`STRUCTURE_CHANGED` / `PARSE_ERROR` / `BLOCKED` / `FETCH_ERROR`). Cron and alerting can
treat "data wrong" differently from "our checker broke."

## Running from cron

Use `webwatch notify` (it tracks state and emails on transitions); `check` is the side-effect-free
interactive command. See [docs/Operations.md](docs/Operations.md).

```cron
# Check every morning at 7am; email fires only on state transitions.
0 7 * * *  cd /path/to/webwatch && /path/to/uv run webwatch notify >> /var/log/webwatch.log 2>&1
```

## Documentation

Developer documentation lives in [docs/](docs/README.md). Start with
[docs/Extraction.md](docs/Extraction.md) before writing any code that reads a web page.

> Significant changes are planned in [docs/plans/](docs/plans/README.md) and reviewed by the `agy`
> CLI before implementation.
