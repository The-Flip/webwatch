# Pin the toolchain with mise

## Context

Nothing currently pins the tools that run this project. `.python-version` says `3.14`, but which
`uv` runs is whatever happens to be on `PATH`, and CI gets its own through `astral-sh/setup-uv`
with no version set. On the maintainer's machine `uv` already comes from mise's _global_ config at
`latest`, and the project's `.venv` was built from the system Python (3.14.4). `../www.theflip.museum`
already uses a project `mise.toml` to pin its runtime.

The goal is one committed declaration of the Python and `uv` versions, used by developers and CI.

## Scope

**mise pins tools. `uv` keeps owning the venv, dependencies and `uv.lock`. The `Makefile` stays.**

Replacing the `Makefile` with mise tasks was considered and rejected (see Alternatives). Daily
commands (`make test`, `make quality`, ...) do not change.

## Design

1. **`mise.toml` (new), tools only.**

   ```toml
   [tools]
   python = "3.14"
   uv = "0.13.7"
   ```

   - `uv` is pinned exactly: it is pre-1.0, it writes the lockfile, and `latest` is not a real pin
     (mise resolved it to the already-installed 0.12.5 while 0.13.7 was current).
   - `python` tracks the 3.14 line, so patch releases arrive without a commit.
   - `python` must stay in step with `.python-version` (see 2).
   - The file deliberately has no `[env]`, `[settings]` or `[tasks]`. Tools-only config installed
     from a fresh, never-trusted clone with no `mise trust` step. Adding those sections may change
     that, so anyone adding them must recheck the setup docs.

2. **Keep `.python-version`.** It looks redundant but is load-bearing: `uv` prefers its own managed
   interpreters over `PATH`, and `requires-python = ">=3.14"` has no ceiling. Without this file, a
   uv-managed 3.15 on the machine would be chosen over mise's 3.14. CI prints the interpreter version
   so a wrong one is visible.

3. **`Makefile`: `bootstrap` installs the tools, then uses them.** An activated shell only picks up
   newly installed tools at the next prompt, so a recipe that runs `mise install` and then a bare
   `uv sync` would use the wrong `uv`, or none. `bootstrap` therefore calls `mise exec -- uv ...`
   after `mise install`, and drops its `install` prerequisite, which would run a bare `uv sync`
   first. Other targets stay on `uv run`, which resolves through the activated shell. If a pin is
   not installed yet, those targets can silently fall through to another `uv`, so the docs say to
   run `mise install` whenever `mise.toml` changes. mise is a hard requirement for `bootstrap` only.

4. **CI uses `jdx/mise-action@v5`** in place of `astral-sh/setup-uv` and `uv python install`, so CI
   installs what `mise.toml` declares. That action caches mise's tools but not uv's package cache,
   which `setup-uv` was caching through `enable-cache`, so add `actions/cache` for `~/.cache/uv`
   keyed on `uv.lock`, with `restore-keys` and a final `uv cache prune --ci` (which `setup-uv` did by
   default). `uv sync --locked` now fails CI on a stale lockfile. `mise.toml` is intentionally absent from `paths-ignore`: a tool bump must
   run CI.

5. **Cron docs use `mise exec`.** The documented `/path/to/uv` would now be a version-specific path
   under mise's installs directory, which breaks on every `uv` bump. `/path/to/mise exec -- uv run webwatch notify`
   has a stable path, uses the pinned tools, and needs no shell activation. Existing
   cron entries keep working until the old path disappears; the host needs mise and `mise install`
   before switching. The docs also state that `cd` is how mise finds its config, and that
   `mise install` must run as the cron user after each pull: otherwise `mise exec` installs during
   the job, and a failed download stops it before webwatch runs, so no alert is sent.

6. **Docs and ignores.** `.gitignore` (`mise.local.toml`), `README.md`, `docs/Python.md`, `docs/Operations.md`, `docs/Project_Structure.md`,
   `docs/AGENTS.src.md` (then `make agent-docs`), and `.github/copilot-instructions.md`. Completed
   plans are history and are not rewritten.

## Unchanged, and why

- `.pre-commit-config.yaml` and the `.claude/settings.json` hook call `uv` from `PATH`. They resolve
  to the pinned `uv` in an activated shell, and behave as they do today otherwise.
- `.venv` stays uv-managed. An existing venv is not rebuilt automatically; to move to mise's Python,
  run `rm -rf .venv && mise exec -- uv sync`.

## Verified before writing this plan

In a clean clone with `env -i`, no shell activation, and isolated mise config, data and state:

- `mise install` succeeded with no `mise trust`.
- `uv sync --locked` and `uv lock --check` pass on uv 0.13.7, and `uv.lock` is unchanged.
- The venv is built from mise's Python (3.14.10). This holds with `.python-version` removed only
  because no uv-managed interpreter was installed; the review showed why the file must stay.
- `mise exec -- uv run pytest -m "not integration"`: 329 passed.
- `mise exec -- uv run webwatch list` works from a cron-like environment.
- Plain `uv` with no mise on `PATH` still works, using system Python 3.14.4.
- `mise-action` sets `MISE_TRUSTED_CONFIG_PATHS` to the working directory.

## Verification of the change

- `make bootstrap` in a clean clone under `env -i`, then `make test` through `mise exec`.
- `make quality` and `make test` in the working repo.
- `make agent-docs` leaves `CLAUDE.md` and `AGENTS.md` in sync.
- CI only runs on a pull request, so the workflow is proven by the PR's first run.

## Alternatives considered

- **Replace the `Makefile` with mise tasks.** Rejected: it would make webwatch the only Flip project
  on mise tasks, diverging from `../flipfix` and `../mailbox`, for no capability gain.
- **Cap `requires-python` at `<3.15` instead of keeping `.python-version`.** Rejected: it changes
  package metadata and the lockfile, and needs editing at every Python upgrade. Two `3.14` lines can
  drift, but `mise.toml` carries a comment saying to keep them in step.
- **Exact Python pin or a `mise.lock`.** Deferred: more churn than the project needs now. Local and
  CI may differ by a 3.14 patch release until a developer upgrades.
- **Make every target `mise exec -- uv run`.** Rejected: a hard mise dependency on every command, to
  cover shells that were not activated.

## Review feedback incorporated (Claude, standing in for agy)

`agy` was not on `PATH` on the machine where this was planned, so the maintainer approved an
independent Claude subagent as a one-off reviewer. `make review-plan` was not run.

- **High, Python selection:** the first draft deleted `.python-version`. The reviewer built a venv on
  a uv-managed 3.15.2 that way, so the file stays and CI prints the interpreter version.
- **Medium, bootstrap:** dropped the `install` prerequisite, which ran a bare `uv sync`.
- **Medium, stale pins:** documented running `mise install` when `mise.toml` changes.
- **Medium, cron:** documented the role of `cd`, and `mise install` as the cron user after each pull.
- **Medium, CI cache:** added `restore-keys` and `uv cache prune --ci`.
- **Low:** added `mise.local.toml` to `.gitignore`, corrected the README requirements, updated the
  sandboxed notes, and used `uv sync --locked` in CI.
- **Declined:** pinning mise's own version in CI, and a `make` check comparing `uv --version` with
  the pin. Both add upkeep to guard against rare, visible failures.
