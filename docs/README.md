# Development Guide

The development documentation for Webwatch, which monitors The Flip's web presence.

- **[CONTRIBUTING.md](../CONTRIBUTING.md)** — Contribution workflow (plans, branches, PRs, quality checks)
- **[Architecture.md](Architecture.md)** — System components and how they fit together
- **[Project_Structure.md](Project_Structure.md)** — Directory layout and where code goes
- **[Extraction.md](Extraction.md)** — The extraction doctrine: `CheckStatus`, structured-data-first, anchors, normalization, breakage detection. **Read this before reading any web page.**
- **[Facts.md](Facts.md)** — The `facts.yaml` schema and dynamic-rule types
- **[Checks.md](Checks.md)** — How to add a new site, source, and checks (with fixtures)
- **[Python.md](Python.md)** — Python coding rules (uv, secrets, linting, error handling)
- **[Testing.md](Testing.md)** — Test patterns, mocking HTTP, fixtures, integration tests
- **[Operations.md](Operations.md)** — Running from cron: the `notify` entry point, email, state, exit codes
- **[plans/](plans/README.md)** — Design docs, reviewed by `agy` before implementation

The agent-facing guides [`CLAUDE.md`](../CLAUDE.md) and [`AGENTS.md`](../AGENTS.md) are **generated** from [`AGENTS.src.md`](AGENTS.src.md). Edit the source and run `make agent-docs`; never edit the generated files directly.
