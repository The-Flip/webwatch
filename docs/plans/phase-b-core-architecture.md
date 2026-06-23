# Phase B — Core architecture

## Context

Phase A delivered the scaffold: tooling (uv/ruff/mypy/pytest/pre-commit/CI), the agent-control docs,
the `webwatch.config` env reader, the `webwatch.result` core abstraction (`CheckStatus` /
`CheckResult` / `exit_code`), a `facts.yaml` template, and a runnable CLI skeleton. `make quality`
and `make test` are green.

Phase B builds the engine between "fetch a page" and "emit a `CheckResult`", with no real site yet
(that is Phase C). Everything here is exercised by hermetic unit tests over small inline HTML — the
goal is to lock down the honest-extraction machinery before pointing it at a live site. Read
[`docs/Extraction.md`](../Extraction.md) before reviewing; the status taxonomy is the spec.

## Scope (modules to build)

1. **`webwatch/fetch.py`** — the single HTTP boundary.
   - `fetch(url, *, transport=None) -> FetchResult` wrapping `httpx`. Sets the configured
     `User-Agent`, timeout; retries `429`/`5xx` with backoff; enforces a per-domain politeness delay
     (injectable sleep + clock so tests don't wait).
   - Returns a small `FetchResult` (final URL, status, text, headers) on success.
   - Classifies failure honestly: network/HTTP error after retries → raise a typed `FetchError`
     (the caller maps it to `CheckStatus.FETCH_ERROR`). **`looks_blocked(...)` is evaluated on the
     body/headers of _all_ responses, including non-200s** — Cloudflare/Incapsula challenges
     commonly return `403`/`503`, so block detection must run before defaulting to `FetchError`
     (agy Gap C). A challenge/login/empty-JS-shell (any status) is surfaced as `BLOCKED`. The
     `transport` seam lets tests inject `httpx.MockTransport` and lets a future JS-rendering fetcher
     slot in.

2. **`webwatch/normalize.py`** — canonicalization used by every comparison.
   - `text(s)` (collapse whitespace, casefold-aware); `phone(s)`; `street(s)`; `postal_code`;
     `time_range` (to 24h `HH:MM`); `hours` (weekday → normalized windows).
   - Avoid the naive-normalization traps (agy Gap D):
     - **Street:** tokenize — strip punctuation, lowercase, normalize known suffix _tokens_
       (`st`→`street`, `ave`→`avenue`) only when they are whole tokens, so `"St. John St."` doesn't
       become `"Street. John Street"`. Compare token sequences.
     - **Phone:** normalize to digits and apply a default country code (US `+1`) so `555 123 4567`
       and `+1 555 123 4567` compare equal; compare on the canonical E.164 form.
     - **Hours:** the normalized schema must support windows that **cross midnight**
       (`18:00–02:00`) rather than assuming day-bound windows.
   - Pure functions, no I/O. Each gets table-driven tests including the cosmetic-difference cases
     from `docs/Extraction.md` plus the three trap cases above.

3. **`webwatch/facts.py`** — load + validate `facts.yaml`.
   - `load_facts(path) -> Facts` returning a typed structure (dataclasses) for organization details
     and a list of rules. Validates shape and fails loudly (`FactsError`) on malformed input.
   - Empty/`""` static values and `enabled: false` rules are represented so checks can map them to
     `SKIPPED` rather than asserting against blanks.

4. **`webwatch/extract/structured.py`** — `extract_jsonld(html) -> list[dict]` plus **type-filtering
   helpers** that encapsulate entity selection across the multiple JSON-LD blocks a page typically
   carries (header, breadcrumbs, search widgets): `extract_local_business(html) -> LocalBusiness | None`,
   `extract_events(html) -> list[Event]`, etc. (agy Gap F). Helpers return an explicit "absent"
   (typed `None`/empty), never an ambiguous `{}`, so downstream sources never inspect the wrong block.

5. **`webwatch/extract/anchors.py`** — semantic-anchor helpers over BeautifulSoup: find a value by
   nearby label text / microformat class / role. Each returns a `Found(value)` or `NotFound(reason)`
   — never a bare string/`None` — so callers can't mistake "missing" for "empty". No positional CSS.

6. **`webwatch/sources/base.py`** — the `Source` ABC and the `Observation` type.
   - `Observation` holds, per field, an `Observed[T]`: either a located value or a not-read reason.
     The reasons are `MISSING` (a tracked field the source expected but couldn't find →
     `STRUCTURE_CHANGED`), `UNPARSEABLE` (→ `PARSE_ERROR`), `BLOCKED` (→ `BLOCKED`), and
     **`NOT_SUPPORTED`** (a field this source legitimately never publishes — e.g. an events-only
     page has no address → `SKIPPED`, **not** `STRUCTURE_CHANGED`) (agy Gap A). The found-vs-not-found
     distinction is type-level, not convention.
   - A source declares the set of fields it _tracks_; any fact outside that set is `NOT_SUPPORTED`
     for it, so checks never raise a false structure alarm for data the page was never meant to have.
   - `Source.observe(html) -> Observation` (pure: HTML in, Observation out) and
     `Source.fetch(transport=None) -> Observation` (fetch once, then `observe`). Declares
     `url` and the anchors it depends on. No comparison logic lives here.

7. **`webwatch/checks/base.py`** + **`registry.py`** — assertions.
   - A check takes an `Observed[T]` field + the expected fact and returns a `CheckResult`, applying
     the mapping: located+matches→`OK`, located+differs→`MISMATCH`, `MISSING`→`STRUCTURE_CHANGED`,
     `UNPARSEABLE`→`PARSE_ERROR`, `BLOCKED`→`BLOCKED`, `NOT_SUPPORTED` or empty-expected→`SKIPPED`.
     Comparison goes through `normalize.py`.
   - **Corroboration rule, corrected (agy Gap B).** The earlier "disagreement → `MISMATCH` against
     visible" rule could itself cry wolf: if the _visible_ value matches the expected fact but the
     JSON-LD is stale, a human sees correct info, so a hard `MISMATCH` (exit 1, "published info is
     wrong") would be a false positive. Correct logic, driven by the **visible** value:
     - `visible != expected` → `MISMATCH` (regardless of JSON-LD).
     - `visible == expected` and `jsonld` disagrees → **`METADATA_DRIFT`** — visible info is correct
       but the structured metadata is stale (actionable: fix the JSON-LD; can mislead Google). This
       is a new status, routed to exit 2 (needs attention), **not** exit 1.
     - `visible == expected` and `jsonld` agrees/absent → `OK`.
   - **Taxonomy change:** introduce `CheckStatus.METADATA_DRIFT` in `webwatch/result.py` (exit 2,
     `is_checker_problem`) and document it in `docs/Extraction.md`. This refines the master plan's
     corroboration line, which conflated metadata drift with a world-state mismatch.
   - `registry.py` maps registered sources to their checks; the CLI iterates it. No sites registered
     yet — registry is exercised with a fake source in tests.

8. **`webwatch/report.py`** — `render_text(results)` and `render_json(results)`; a one-line summary
   and per-check detail. Pure formatting; the CLI prints it.

9. **`webwatch/state.py`** — `load_state(path)` / `save_state(...)`; tracks per-check last status
   and run counters. Provides `transitions(prev, current, ...)` returning which checks newly crossed
   into/out of a problem state (used by Phase E). Pure logic over a plain dict persisted as JSON.
   - **Partition by health, not exact status (agy Gap E).** `HEALTHY = {OK, SKIPPED}`; everything
     else (`MISMATCH`, `STRUCTURE_CHANGED`, `PARSE_ERROR`, `BLOCKED`, `FETCH_ERROR`,
     `METADATA_DRIFT`) is `UNHEALTHY`. The counter tracks **consecutive UNHEALTHY runs**, so a check
     that fails as `FETCH_ERROR` then `STRUCTURE_CHANGED` then `BLOCKED` still escalates instead of
     resetting on each status change. (Known limitation, documented in `state.py`: a strict
     every-other-run flap never reaches the consecutive threshold; a windowed failure-rate signal is
     deferred until a real source shows the need.)
   - **Hysteresis:** alert after `N` consecutive unhealthy runs (`ALERT_AFTER_FAILURES`); clear the
     alert only after `M` consecutive healthy runs (add `WEBWATCH_RECOVER_AFTER_SUCCESSES`,
     default 1). The alert payload still carries the _current_ status so a confirmed `MISMATCH`
     reads differently from a `BLOCKED`.

## Out of scope (later phases)

- Any real site scraper and committed fixtures → **Phase C** (`sources/theflip_museum.py`).
- Dynamic-rule evaluation engine wiring → **Phase D** (`rules.py`).
- SMTP sending and the cron entry → **Phase E** (`notify/email.py`).
- Wiring `cli.py check` to the registry happens at the end of Phase C once a real source exists; in
  Phase B the registry is covered by unit tests with a fake source.

## Testing

Hermetic, mirroring the package (`tests/test_fetch.py`, `test_normalize.py`, `test_facts.py`,
`test_extract_structured.py`, `test_extract_anchors.py`, `test_checks.py`, `test_report.py`,
`test_state.py`). Key cases:

- `fetch`: builds correct request (UA/timeout); retries `429`/`5xx` with an injected sleep spy then
  succeeds; gives up → `FetchError`; `looks_blocked` flags a Cloudflare/empty-shell body.
- `normalize`: table-driven equivalence of the cosmetic-difference pairs.
- `checks`: from one small inline HTML snippet, the mutation matrix — unchanged→`OK`,
  region removed→`STRUCTURE_CHANGED`, value corrupted→`PARSE_ERROR`, value changed→`MISMATCH`,
  challenge body→`BLOCKED`, stale-JSON-LD-vs-visible→`MISMATCH` on the visible value. This is the
  proof that the engine never turns "can't read" into a false `MISMATCH`.
- `state`: a problem must persist `N` consecutive _unhealthy_ runs before `transitions` reports it
  (anti-flap), the counter does **not** reset when the failure status changes between runs, and
  recovery is reported only after `M` consecutive healthy runs.
- **Test hygiene (agy):** the fixture/mutation helper re-parses fresh HTML (or `copy.deepcopy`s the
  soup) per test, so in-place `.decompose()` mutations don't bleed between tests.

## Verification

- `make quality` and `make test` green; coverage of the new modules visible via `make test-cov`.
- A throwaway end-to-end unit test: fake `Source` + inline HTML + a `facts.yaml` fragment →
  `CheckResult[]` → `report.render_text` → expected exit code, all without network.

## Review feedback incorporated (agy)

`agy` reviewed this plan via `make review-plan`; all six gaps and the test-hygiene note were folded
in above:

- **Gap A — untracked fields:** added the `NOT_SUPPORTED` `Observed` reason; a source declares the
  fields it tracks, and an untracked fact maps to `SKIPPED`, never a false `STRUCTURE_CHANGED`.
- **Gap B — corroboration false positive:** the comparison is driven by the _visible_ value;
  visible-correct-but-stale-JSON-LD becomes the new `METADATA_DRIFT` (exit 2), not a hard
  `MISMATCH`. Recorded as a taxonomy change to `result.py` / `Extraction.md`.
- **Gap C — block detection:** `looks_blocked` runs on all responses incl. `403`/`503` before
  falling back to `FetchError`.
- **Gap D — normalization traps:** token-based street normalization, default-country-code phone
  handling, and midnight-crossing hours windows.
- **Gap E — state drift/flap:** count consecutive _unhealthy_ runs (health partition, not exact
  status), with `N`-to-alert / `M`-to-recover hysteresis.
- **Gap F — JSON-LD ambiguity:** type-filtering helpers select the right entity among multiple
  JSON-LD blocks.
- **Test hygiene:** fresh-parse / deepcopy per mutation test to prevent soup bleed.

One deliberate divergence: `agy` floated `METADATA_DRIFT` as possibly "`STRUCTURE_CHANGED` with
warnings." We make it a distinct status instead — the project's doctrine is to name each condition
precisely, and drift (visible correct, metadata stale) is neither a structural break nor a
world-state mismatch.
