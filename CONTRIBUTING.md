# Contributing

This guide covers how to contribute to Webwatch and submit a PR.

## Getting Started

- Configure your environment via [README.md](README.md)
- Understand the conventions in [docs/README.md](docs/README.md) — especially [docs/Extraction.md](docs/Extraction.md)

## Plan first, then build

Significant changes start as a plan in [`docs/plans/`](docs/plans/README.md), reviewed by the `agy`
CLI (`make review-plan PLAN=docs/plans/<name>.md`) before implementation. Record the review feedback
in the plan. Small, obvious fixes don't need a plan.

## Workflow

- **Create a branch** (e.g. `feat/google-business-check`, `fix/hours-normalization`, `docs/extraction-doctrine`)
- **Make your changes & tests**

```bash
make quality     # Format, lint, check Python types
make test        # Run the fast test suite
```

- **Commit changes** ([Conventional Commits](https://www.conventionalcommits.org/); pre-commit hooks run formatting, linting, and security checks)
- **Push your branch**
- **Open a Pull Request** against `main`
- **Wait for CI** (GitHub Actions runs formatting, linting, type checking, and tests)
- **Merge when green**

## Before you trust a check

A check that cries wolf is worse than no check. Any change to extraction, a check, or a
notification must:

- Keep "the value is wrong" (`MISMATCH`) distinct from "I can't read the page"
  (`STRUCTURE_CHANGED` / `PARSE_ERROR` / `BLOCKED`) — a broken page must never yield a false `MISMATCH`
- Compare values through `normalize.py`, not raw strings
- Be covered by **programmatic-mutation tests** that prove each negative status from the golden fixture
- For notifications: support a **dry-run**, fire only on state transition, and never email a live recipient during testing

State how you verified this in the PR's test plan.
