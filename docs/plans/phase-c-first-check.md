# Phase C — First real check (theflip.museum)

## Context

Phases A and B gave us the scaffold and the honest-extraction engine, all proven against inline HTML
with no network. Phase C points that engine at the first real site — The Flip's own website,
`theflip.museum` — and wires the `webwatch check` command end-to-end. This is where the abstractions
meet a real, messy page, and where `facts.yaml` gets real verified values for the first time.

We start with the museum's own site because it is the most controllable and the clearest source for
address, hours, and name. Read [`docs/Extraction.md`](../Extraction.md) and [`docs/Checks.md`](../Checks.md)
before reviewing.

## Approach

0. **Refactor `scripts/capture_fixture.py` to fetch through `webwatch.fetch.fetch` (agy Gap A).**
   Now that the fetch boundary exists, capture must share it so fixtures are taken under the same
   User-Agent, timeout, and redirect rules as production (otherwise the captured layout can differ
   from what a real run sees). If `fetch` reports the page `blocked`, the script warns rather than
   silently saving a challenge page.

1. **Capture a golden fixture.** Run `uv run python scripts/capture_fixture.py https://www.theflip.museum/`
   to save `tests/fixtures/theflip_museum_<date>.html`, then **inspect it** to decide anchors. We do
   not guess structure. Key questions answered from the real HTML:
   - Does it emit JSON-LD (`LocalBusiness`/`Museum`, `PostalAddress`, `openingHours`)? Use it as
     corroboration.
   - What stable visible anchors carry the address / hours / phone (labels, microformats, headings)?
   - Is it server-rendered? If the captured HTML is an empty JS shell, `looks_blocked` will flag it
     and we reconsider (a JS-rendering transport) before writing brittle anchors. (Expected to be
     server-rendered; confirm from the fixture.)

2. **Fill `facts.yaml` with real, verified values.** Replace the TODO placeholders with the museum's
   actual name, address, phone, and weekly hours — verified against the live site and any
   authoritative source. Values we cannot verify stay blank (→ `SKIPPED`). This is a human-judgment
   step; the fixture informs it but the canonical truth is deliberate, not scraped.

3. **Write the source** `webwatch/sources/theflip_museum.py`:
   - Subclass `Source`; set `name = "theflip_museum"`, `url`, and `tracks` (the fields we read:
     `name`, `address.street`, `address.city`, `address.region`, `address.postal_code`, `phone`,
     and per-day `hours.<weekday>`).
   - `observe(html)` extracts each field via the layered strategy (structured-data corroboration +
     visible anchors from `extract/`), returning `Observed.found` / `Observed.missing` /
     `Observed.unparseable` honestly, plus `structured` corroboration values.
   - **Flatten JSON-LD into flat `structured` keys (agy Gap B).** The registry looks up
     `observation.structured[field]` by the same flat name as the check (e.g. `"address.street"`),
     so the source maps the nested `PostalAddress`/`openingHours` JSON-LD into
     `{"address.street": ..., "phone": ..., "hours.saturday": ...}`. Nesting stays inside the source.
   - **Hours fields carry the visible value as-is.** Parsing raw hours text is handled by the
     normalizer (below), so `observe` doesn't need to pre-structure it — it just returns what it read
     (or `Observed.missing`/`unparseable`).
   - Use the shared `Observed.from_anchor(...)` helper (see below) to convert anchor results, rather
     than re-implementing the `Found`/`NotFound` → `Observed` mapping per source.
   - Register it in `sources/registry.py`.

4. **Write the checks** and register them in `checks/registry.py`: one `Check` per tracked field,
   each with the right normalizer (`normalize.street` for street, `normalize.phone` for phone,
   `normalize.day_hours` for each weekday, `normalize.text` for name/city), and `structured_field`
   where JSON-LD corroborates.

5. **Add the run orchestration** `webwatch/run.py`:
   - `run_checks(sources, facts, *, transport=None) -> list[CheckResult]`: for each source, fetch
     once; on `FetchError` emit `fetch_error_results` for that source's checks (one failure ≠ many);
     otherwise run each registered check against the Observation. Supports `--site`/`--fact` filters.
   - Keeps orchestration out of `cli.py` (which just parses args and prints).

6. **Wire the CLI** (`cli.py`):
   - `check`: load facts (`facts.load_facts`), run `run.run_checks`, load prior state, compute
     `state.apply_results`, save state, render via `report` (`--format text|json`), and exit with
     `result.exit_code`. `--site`/`--fact` filter; `--all` runs everything.
   - `list`: enumerate registered sources and their checks.
   - `facts --validate`: load and report on `facts.yaml`.
   - (Notification on transitions is wired in Phase E; for now `check` just reports + exits.)

### Small enabling changes (from the agy review)

- **`normalize.day_hours` also accepts a raw range string (agy Gap C).** Today it takes `"closed"`,
  an `{open, close}` dict, or a list of them — but a source reads _visible_ hours like
  `"10:00 AM - 5:00 PM"` (or a comma-separated `"9-12, 1-5"`). Extend `day_hours` to parse a raw
  range string (single or comma-separated) via `normalize.time_range`, so the facts-side dict and
  the observed visible text normalize to the **same** comparable frozenset. This keeps the source
  honest (it emits what it read) and centralizes hours parsing in one tested place.
- **Shared `Observed.from_anchor(anchor)` (agy Gap D).** Lift the `Found`/`NotFound` → `Observed`
  mapping (currently duplicated in tests) into `webwatch.sources.base` so every source — present and
  future — converts anchors the same way and stays honest (a `NotFound` becomes `Observed.missing`,
  never a guessed value).

## Testing

- `tests/test_theflip_museum.py`: against the committed golden fixture, assert each tracked field is
  read (`OK` when facts match), then the **mutation matrix** via in-memory BeautifulSoup edits
  (remove the address block → `STRUCTURE_CHANGED`; change hours text → `MISMATCH`; corrupt a value →
  `PARSE_ERROR`; swap in a challenge body → `BLOCKED`; stale JSON-LD vs visible → `METADATA_DRIFT`).
  Fresh-parse per test.
- **Hours edge cases explicitly (agy Risk B):** a day flipped to `"closed"` when facts expect it open
  (`MISMATCH`); a corrupted time window (`PARSE_ERROR`); a double-window day (lunch closure) to
  exercise the order-insensitive list comparison; and a cross-midnight window.
- `tests/test_run.py`: `run_checks` with a fake/registered source over `httpx.MockTransport` serving
  the fixture → expected results; a transport that errors → all that source's checks `FETCH_ERROR`.
- `tests/test_cli.py` (extend): `webwatch check` against a fixture-backed transport returns the right
  exit code and report; `list` shows the source.
- Keep a single `@pytest.mark.integration` smoke test that actually fetches the live site (excluded
  from `make test`).

## Verification

- `make quality` and `make test` green; coverage of the new modules visible.
- `webwatch check --site theflip_museum` against the committed fixture prints a report and exits 0
  when facts match; a mutated fixture demonstrates exit 1 (mismatch) vs exit 2 (checker condition).
- `webwatch list` shows `theflip_museum` and its checks; `webwatch facts --validate` passes.

## Risks / open questions

- **Real values:** filling `facts.yaml` requires knowing the museum's verified address/hours. If any
  are uncertain at implementation time, leave them blank (`SKIPPED`) rather than guess — a wrong
  canonical value would invert the whole tool (it would flag the _correct_ site as wrong).
- **Site shape unknown until captured:** anchor choices depend on the real HTML; the plan commits to
  the _strategy_, not specific selectors. If the site is JS-only or blocks us, that surfaces as
  `BLOCKED` and we adapt the fetch path before writing anchors.

## Review feedback incorporated (agy)

`agy` reviewed this plan via `make review-plan`. Folded in:

- **Gap A — capture via the real fetch boundary:** added step 0 (refactor `capture_fixture.py` to use
  `webwatch.fetch.fetch`) so fixtures and production share headers/timeouts/redirects.
- **Gap B — flat structured keys:** the source flattens nested JSON-LD into flat
  `Observation.structured` keys (`"address.street"`, …) matching the registry's lookup.
- **Gap C — hours normalization:** extend `normalize.day_hours` to also parse raw range strings, so
  visible hours text and facts dicts normalize to the same comparable.
- **Gap D — shared anchor→Observed helper:** add `Observed.from_anchor(...)` in `sources/base`.
- **Risk B — hours mutation tests:** explicit closed/corrupt/double-window/cross-midnight cases.

Answers to agy's open questions:

1. **Modify theflip.museum's live HTML to add `itemprop` microdata? — Not as part of this work
   (deliberate divergence).** webwatch must monitor the site _as it actually is_; making the tool
   depend on us first editing the target would defeat the point (and the museum site is a separate
   codebase). We prefer existing JSON-LD/visible anchors. Adding microdata to the museum site is a
   reasonable _optional_ follow-up to improve robustness, recorded as a suggestion — not a
   prerequisite, and not in this plan's scope.
2. **Flatten JSON-LD to flat keys? — Yes** (Gap B above).
3. **Shared anchor→Observed helper? — Yes** (Gap D above).
