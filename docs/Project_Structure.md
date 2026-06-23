# Project Structure

```text
webwatch/                   # repo root (distribution & command are named "webwatch")
├── webwatch/               # the application package (import name == command == webwatch)
│   ├── __init__.py
│   ├── __main__.py         # `python -m webwatch`
│   ├── cli.py              # Click CLI — entry point for the `webwatch` command
│   ├── config.py           # Environment-backed settings — the only reader of env vars
│   ├── fetch.py            # The single HTTP boundary (retry/backoff, UA, politeness)
│   ├── facts.py            # Load + validate facts.yaml
│   ├── rules.py            # Evaluate dynamic rules (clock injected for testability)
│   ├── normalize.py        # Canonicalize values before comparison
│   ├── result.py           # CheckStatus / CheckResult — the core abstraction
│   ├── state.py            # Run-to-run state (alert-on-transition / anti-flap)
│   ├── report.py           # Render text/JSON reports; build the email body
│   ├── extract/            # Robust extraction primitives
│   │   ├── structured.py   #   JSON-LD / schema.org / microdata (extruct)
│   │   └── anchors.py      #   semantic/label anchors
│   ├── sources/            # Per-site scrapers
│   │   ├── base.py         #   Source ABC: fetch() -> Observation; declares its anchors
│   │   ├── registry.py     #   registry of sources
│   │   └── theflip_museum.py
│   ├── checks/             # Assertions over an Observation
│   │   ├── base.py
│   │   └── registry.py
│   └── notify/
│       └── email.py        # dry-run-able SMTP email
├── facts.yaml              # Canonical expected facts + rules (hand-maintained)
├── tests/                  # pytest suite (mocks HTTP; no live calls by default)
│   ├── conftest.py         # fixture loaders + transport factories
│   └── fixtures/           # committed real-website HTML snapshots (one golden per source)
├── scripts/                # Dev/build scripts
│   ├── build_agent_docs.py     # Generates CLAUDE.md / AGENTS.md from docs/AGENTS.src.md
│   ├── check_agent_docs_edit.sh
│   └── capture_fixture.py      # fetch a live page and save it under tests/fixtures
├── docs/                   # Developer documentation (this folder)
│   ├── AGENTS.src.md       # Source for the generated agent docs
│   └── plans/              # Design docs, reviewed by agy before implementation
├── CLAUDE.md / AGENTS.md   # GENERATED — do not edit directly
├── pyproject.toml          # Project metadata + tool config (ruff, mypy, pytest, coverage)
└── Makefile                # Common commands (wrap `uv run ...`)
```

> Unlike `../mailbox` (whose import package is `flipmail` to dodge the stdlib
> `mailbox` module), `webwatch` has no stdlib collision: the distribution, the
> command, and the import package are all `webwatch`.

## Conventions

- **Where code goes**
  - Anything that makes an HTTP request lives behind `webwatch/fetch.py`. Don't call `httpx` elsewhere.
  - Site-specific knowledge (URL, anchors, how to read each field) lives in that site's `webwatch/sources/` module — nowhere else.
  - Generic, reusable extraction belongs in `webwatch/extract/`; if two sources need the same trick, lift it here.
  - Comparison/canonicalization lives in `webwatch/normalize.py`. Checks call it; they don't reimplement it.
  - Configuration and secret access lives in `webwatch/config.py`. Don't read `os.environ` or `decouple.config` anywhere else.
  - Reusable helpers shared across modules get their own module — never dump them in `__init__.py`.
- **Fetch once, then assert.** Sources fetch and produce an `Observation`; checks consume it. Checks never fetch.
- **One responsibility per module.** Keep `fetch.py` about transport; keep extraction generic in `extract/`; keep site quirks in `sources/`; keep "matches vs differs vs unreadable" in `checks/`.
- **Tests mirror the package.** `webwatch/result.py` is tested by `tests/test_result.py`. A source `webwatch/sources/theflip_museum.py` is tested by `tests/test_theflip_museum.py` against a committed fixture. Tests never hit the live web unless marked `@pytest.mark.integration` (see [Testing.md](Testing.md)).
- **Scripts are not part of the package.** Files in `scripts/` are standalone (run via `uv run python scripts/...`) and may use `print`.

## Generated files

`CLAUDE.md` and `AGENTS.md` are generated from `docs/AGENTS.src.md` by `scripts/build_agent_docs.py`. Edit the source, then run `make agent-docs`. A pre-commit hook regenerates them and blocks direct edits.
