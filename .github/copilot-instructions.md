# Copilot Instructions for Webwatch

This guide enables AI coding agents to work productively in this codebase. Follow it so code, docs, and workflows align with project conventions.

## Big Picture

- **Webwatch** monitors where The Flip pinball museum appears on the web (its own site, map/listing profiles, event aggregators) and reports when published information is wrong or out of sync. It is a CLI run from cron — there is no web server or database.
- **Language/runtime:** Python 3.14, managed by [`uv`](https://docs.astral.sh/uv/). Run everything via `uv run` (the `Makefile` wraps common commands).
- **Core deps:** `click` (CLI), `httpx` (fetching), `python-decouple` (config), `extruct` + `beautifulsoup4` + `lxml` (extraction), `pyyaml` (facts).

## Project Structure

- `webwatch/` — the application package (import name and command are both `webwatch`)
  - `cli.py` — Click CLI, entry point for the `webwatch` command
  - `config.py` — the only reader of environment variables (User-Agent, timeouts, SMTP, paths)
  - `fetch.py` — the single HTTP boundary: retry/backoff, User-Agent, per-domain politeness delay
  - `facts.py` / `rules.py` — load `facts.yaml`; evaluate dynamic rules
  - `normalize.py` — canonicalize values (address/phone/hours/whitespace) before comparison
  - `result.py` — `CheckStatus` / `CheckResult`, the core abstraction
  - `state.py` — run-to-run state for alert-on-transition and anti-flap
  - `extract/` — robust extraction primitives (structured-data + semantic anchors)
  - `sources/` — per-site scrapers: fetch a page once → typed `Observation`
  - `checks/` — assertions comparing an `Observation` to facts/rules → `CheckResult`
  - `notify/` — dry-run-able SMTP email
- `tests/` — pytest suite; HTTP mocked at the transport boundary against committed fixtures
- `docs/` — developer docs; `AGENTS.src.md` generates `CLAUDE.md`/`AGENTS.md`
- `scripts/` — standalone dev/build scripts

## Conventions

- All HTTP fetching goes through `webwatch/fetch.py`. Never call `httpx` elsewhere.
- A page is fetched **once** per source into an `Observation`; checks assert against it. Don't re-fetch per fact.
- **The cardinal rule:** an extractor must distinguish "I found the region, the value is X" from "I couldn't find the region." Only the former feeds a MATCH/MISMATCH. A missing region is `STRUCTURE_CHANGED`, a located-but-unparseable value is `PARSE_ERROR`, a block/challenge page is `BLOCKED` — **never a guessed value or a false `MISMATCH`.** See `docs/Extraction.md`.
- Structured data (JSON-LD) is **corroboration, not a short-circuit**; visible text is authoritative.
- Compare values via `webwatch/normalize.py`, never raw string `==`.
- All config/secrets come from `webwatch/config.py` via `python-decouple`. Never hardcode; keep `.env.example` in sync.
- Raise specific exceptions with context; never swallow errors in a bare `except`.
- Add dependencies with `uv add` / `uv add --dev`, latest stable. Don't add `# noqa` / `# type: ignore` without approval.
- Tests mirror the package and stay hermetic; live-fetch tests must be `@pytest.mark.integration`. Derive negative cases by mutating the golden fixture programmatically — don't commit mutated fixtures.

## Notification safety

A false alarm trains operators to ignore alerts. Email fires on **state transitions** (after N consecutive failures), not every run; notification code must be dry-run-able and must never deliver to a live recipient during testing.

## Quality Gates

```bash
make quality   # format + lint + typecheck
make test      # fast suite
```

`CLAUDE.md` and `AGENTS.md` are **generated** from `docs/AGENTS.src.md` — edit the source and run `make agent-docs`, never the generated files.

## Plans are reviewed before implementation

Significant changes get a plan in `docs/plans/` that is reviewed by the `agy` CLI (`make review-plan PLAN=...`) before coding. See `docs/plans/README.md`.
