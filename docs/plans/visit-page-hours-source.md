# Plan — "Plan Your Visit" source (theflip.museum/visit hours)

## Context

The homepage source (Phase C) checks name/address/email but the homepage does not publish opening
hours, so `facts.yaml`'s `hours` are currently unchecked by any source. The museum's hours live on
`https://www.theflip.museum/visit`. This adds a second source for that page so the hours we recorded
are actually verified, and drift in published hours gets flagged.

This follows the established source pattern (Phase C, `docs/Checks.md`), but the hours extraction is
genuinely new and a little tricky, which is why it gets its own reviewed plan.

## What the captured `/visit` fixture shows

- **No `openingHours` JSON-LD** — only an `Organization` node (no hours). So hours must come from the
  **visible** page.
- The hours sit in a card: an `<h3>Hours</h3>` heading, then rows, each a container with two
  `<span>`s — a day label and a time value:

  ```text
  Monday - Saturday   10a - 8p
  Sunday              11a -6p
  Private Tours       By appointment starting in July
  ```

- Two parsing wrinkles: **grouped day ranges** ("Monday - Saturday" covers six days) and a **compact
  time format** (`10a`, `8p` — no colon, no `m`). `Private Tours` is not a weekday.

## Approach

1. **Commit the captured fixture** `tests/fixtures/theflip_museum_visit_2026-06-23.html` (already
   captured via `capture_fixture.py`).

2. **Extend `normalize.time_to_minutes` to accept a single-letter meridiem** (`10a`, `8p`) in
   addition to `am`/`pm`/`a.m.`. **Critical (agy #1):** the current PM offset is
   `12 if meridiem == "pm"` — with a single-letter `"p"` that comparison is false and `8p` would
   wrongly become 08:00, producing a _false_ `MISMATCH`. Fix by reducing the meridiem to its first
   letter and testing `== "p"` (so `p`/`pm`/`p.m.` all add 12). Add tests; confirm existing forms
   still parse. This is the only `normalize` change; day ranges are a source concern.

3. **New source** `webwatch/sources/theflip_museum_visit.py`:
   - `name = "theflip_museum_visit"`, `url = "https://www.theflip.museum/visit"`.
   - `tracks` = the seven `hours.<weekday>` fields.
   - `observe(html)`: anchor on the `Hours` heading (semantic label, not the brittle Tailwind
     classes); from its card, read each row's (day-label, time-value) span pair into a
     `{weekday: time_text}` map, **expanding day ranges** ("Monday - Saturday" -> mon..sat) and
     ignoring non-weekday labels ("Private Tours"). **Initialize all seven weekdays to
     `Observed.missing` and overwrite only those parsed (agy #6)** — a day omitted from the card
     stays `STRUCTURE_CHANGED`, never a `KeyError` or silent `None`. If the Hours card/heading is
     absent, all seven are `Observed.missing`. The time text stays raw — the check's
     `normalize.day_hours` parses it (so `"10a - 8p"` and facts' `"10:00 - 20:00"` compare equal).
   - **Skip non-data rows (agy #2):** the card interleaves `<div class="section-divider"></div>`
     between rows; iterate only rows that contain a (label, value) pair — collect each row's spans
     and skip any row without at least two, rather than unpacking blindly (which would crash on the
     divider).
   - **Day-range parsing is robust (agy #4, #5):** a tested helper that lowercases, maps full names
     **and 3-letter abbreviations** (`mon`/`monday`), splits a range on the shared dash/`to`
     separator regex, supports **wrap-around** ranges (`"Saturday - Tuesday"` -> sat,sun,mon,tue via
     `days[s:]+days[:e+1]`), maps a bare day to itself, and drops anything it can't recognize (so a
     genuinely unreadable label degrades to `STRUCTURE_CHANGED` for the affected days, not a guess).

4. **Checks**: one `Check("hours.<weekday>", ..., normalize.day_hours)` per weekday. A weekday absent
   from `facts.yaml` (blank) -> `SKIPPED`. **Avoid the late-binding closure trap (agy #3):** if the
   seven checks are built in a loop, capture the weekday with a default arg
   (`lambda f, d=day: f.organization.hours.get(d)`), or list them statically — otherwise every check
   would read Sunday's expected hours.

5. **Register** the source + checks as a built-in in `run.py`'s `register_builtins()`.

## Testing (`tests/test_theflip_museum_visit.py`, fixture-backed, fresh-parse per test)

- All seven `hours.*` checks are `OK` against the committed fixture with the real facts
  (Mon-Sat 10:00-20:00, Sun 11:00-18:00).
- **Mutation matrix:** remove the Hours card/heading -> all hours `STRUCTURE_CHANGED`; change a day's
  visible time to a different valid range -> `MISMATCH`; corrupt a time to something unparseable
  (e.g. "ten-ish") -> `PARSE_ERROR`; set a day to "Closed" when facts expect it open -> `MISMATCH`.
- **Each weekday maps to its own hours, not Sunday's** (guards the late-binding fix, agy #3): with
  facts where Sat and Sun differ, the Saturday check reads Saturday's expected value.
- **Day-range expansion unit tests:** "Monday - Saturday" -> six days; "Sunday" -> one; "Private
  Tours" -> none; abbreviations ("Mon - Sat") and "to" separators resolve; a wrap-around
  ("Saturday - Tuesday") -> sat,sun,mon,tue; an unrecognized label is dropped, not guessed.
- **`section-divider` rows don't crash** the parser (agy #2): a card with divider siblings still
  yields the seven days.
- **A day omitted from the card** -> that day `STRUCTURE_CHANGED`, others fine (agy #6).
- **`normalize.time_to_minutes`** single-letter meridiem: `10a`->600, **`8p`->1200** (not 480),
  and existing `10am`/`5 PM`/`09:00` still pass.

## Verification

- `make quality` and `make test` green.
- `webwatch check --site theflip_museum_visit` exits 0 against the fixture; mutating a time gives
  exit 1, removing the card gives exit 2.
- `webwatch list` now shows `theflip_museum_visit` and its seven hours checks.

## Notes / decisions

- **Hours are read from the visible card, not JSON-LD** (the page has no `openingHours`), which is
  exactly the doctrine's "visible is authoritative". No corroboration source here, so no
  `METADATA_DRIFT` path for this source.
- **Scope:** this source tracks hours only. The `/visit` page also shows the address, but that is
  already checked on the homepage; re-checking it here is deferred (cheap to add later for
  cross-page corroboration).

## Review feedback incorporated (agy)

`agy` reviewed this plan; all six findings folded in above:

- **#1 (critical) — meridiem PM bug:** `time_to_minutes` reduces the meridiem to its first letter and
  tests `== "p"`, so `8p` -> 20:00 (not 08:00). This was a latent bug in the existing code that the
  single-letter format would have exposed as a false `MISMATCH`.
- **#2 — `section-divider` crash:** the row loop skips any row without a (label, value) span pair.
- **#3 — late-binding closure:** per-weekday checks capture the day with a default arg.
- **#4 — day labels:** the parser accepts full names and 3-letter abbreviations and the shared
  dash/`to` separator, reducing false `STRUCTURE_CHANGED` on minor label changes.
- **#5 — wrap-around ranges:** handled (`days[s:] + days[:e+1]`).
- **#6 — missing day:** all seven weekdays initialized to `Observed.missing`, overwritten only when
  parsed.

Answers to agy's open questions:

1. **Fix meridiem in `normalize` (vs preprocess in the source)? — Yes**, fix it in `normalize`; the
   bug lives there and every source benefits.
2. **Support day abbreviations / separator variants? — Yes** (#4), to avoid false structure alarms on
   cosmetic label changes.
3. **Recommend adding `openingHoursSpecification` JSON-LD to the museum site? — Optional follow-up,
   not a requirement** (same stance as the Phase C microdata question). webwatch reads the site as it
   is. The source is structured so that if JSON-LD hours appear later, they can be wired in as
   corroboration (enabling `METADATA_DRIFT`) without reworking the visible-text path.
