# Plan — Apple Maps place-page source (name, website, phone, hours)

## Context

Someone reported that The Flip's **hours are wrong on Apple Maps**. Webwatch only watched
theflip.museum, so it could not catch this. This adds an Apple Maps source so a wrong listing shows up
as a `MISMATCH` and later drift triggers an alert. Apple Maps is the first third-party site. Google
Maps, Yelp and Tripadvisor are queued in `todo.md`, so the shared pieces (weekly-hours parsing, check
prerequisites) are built reusable now.

Monitoring doesn't fix the listing. The fix is made in **Apple Business Connect**. Webwatch then
confirms the fix went live and stays live.

Listing: `https://maps.apple.com/place?place-id=I807CC9ABBE1179A2`. It came from the Apple Maps share
link and was not guessed. A web search surfaced an unrelated "FLIP Museum" in Oregon, which is why the
identity gate below exists.

**Finding at fixture capture (2026-09-26):** this listing currently shows Sun 11 AM–6 PM,
Mon–Sat 10 AM–8 PM, +1 (312) 999-0153 and `https://www.theflip.museum/`. That all matches `facts.yaml`
and the live `/visit` page, so the reported error is not on this listing today. It may have been fixed
already, been holiday hours, or be on a duplicate listing. We build the source anyway as ongoing
monitoring. The golden fixture asserts all `OK`, and in-memory mutation proves `MISMATCH`.

## What an Apple Maps place page looks like (probed live, read-only)

- `maps.apple.com/place?place-id=…` is **server-rendered**, so static `httpx` works. By contrast,
  `/search?…` is a JS shell, and `/place?address=&name=` just echoes the query back. Only a real
  `place-id` URL means anything. An unknown place-id returns **HTTP 404**, which the fetch layer
  already maps to `FETCH_ERROR`.
- **Visible Details section.** An `h3.sc-platter-cell-title` titles each cell in `#axDetails`:
  **Hours**, **Website**, **Phone**, **Address**.
  - Hours appear twice. A folded summary shows _today only_. The unfolded section lists the full week
    as `div.sc-hours-row` rows, each holding a `.sc-hours-day` label ("Mon – Sat") and a
    `.sc-hours-range` time ("10:00 AM – 8:00 PM"), plus an `aria-label`.
  - A **closed day is an explicit row** whose range reads "Closed". This was confirmed on another
    Chicago listing that is closed on Tuesdays. Labels can wrap around the week ("Sun – Mon").
  - Phone: `bdo.sc-phone-number` "+1 (312) 999-0153". Website: an `<a href>` around the cell.
  - Name: `h1.sc-header-title` in `#axHeader`. Another copy in the shell header is `aria-hidden`, and a
    `visually-hidden` `h1` reads "Apple Maps".
- **Structured data.** There is no business JSON-LD. `<script id="shell-props"
type="application/json">` carries Apple's own place payload: an entity with `name`, `telephone` and
  `url`, and a `COMPONENT_TYPE_BUSINESS_HOURS` component with `weeklyHours` (day lists plus seconds
  since midnight) and `hoursType` ("NORMAL"). `weeklyHours` leaves closed days out. The payload
  embeds the page's own `placeId`.

## Approach

### 1. Shared weekly-hours helpers (refactor first; no behavior change)

- Move `expand_days` and its day tables from `webwatch/sources/theflip_museum_visit.py` into
  `webwatch/normalize.py` as `WEEKDAYS` / `expand_days`. This is pure day-label canonicalization that
  every listing site needs. While moving it, replace the existing `# type: ignore[index]` with proper
  narrowing.
- Move the per-day check factory into `webwatch/checks/registry.py` as
  `hours_checks(requires=None)`. Both sources use it.

### 2. Check prerequisites (`Check.requires`) — the identity gate

`Source.observe(html)` is pure and cannot see facts, so identity can't be decided inside the source.
Add an optional `requires: str | None` to `Check`. In `run.py`, checks run in registration order. If a
check's prerequisite did not come back `OK`, that check becomes `STRUCTURE_CHANGED` with the detail
"prerequisite check 'name' was <status>" and never runs its assertion. A wrong or reassigned place-id
therefore produces one `name` MISMATCH plus clearly gated results, instead of a burst of false hours
MISMATCHes. `STRUCTURE_CHANGED` is used rather than `SKIPPED` because we genuinely could not read this
place's data, and that must not look like a pass.

### 3. `webwatch/sources/apple_maps.py`: `AppleMaps(Source)`

- `name = "apple_maps"`, `url` hardcoded like the other sources, `provides_events = False`.
  `tracks = {"name", "url", "phone", hours.<day>…}`.
- **Self-identity (pure).** The `placeId` the page embeds must equal the `place-id` in `self.url`. If it
  doesn't (redirect or merge), every field is `missing` with a note naming both IDs.
- **Name.** The visible value is the `#axHeader h1.sc-header-title` that is not `aria-hidden`. The
  shell-props entity name is structured corroboration.
- **Website.** The visible value is the `href` of the link in the cell titled "Website", corroborated
  by the entity `url`. It is compared through a new `normalize.url`, which lowercases the scheme and
  host, drops a trailing `/` and drops any fragment.
- **Phone.** The visible value is the `.sc-phone-number` text in the cell titled "Phone", corroborated
  by the entity `telephone`. It is compared through the existing `normalize.phone`.
- **Hours.**
  - **Visible, authoritative.** Among the `section`s whose `h3` title is exactly "Hours", pick the one
    that contains `.sc-hours-row` rows. That skips the today-only summary. For each row, expand
    `.sc-hours-day` with `normalize.expand_days` and take the `.sc-hours-range` text.
  - Every day starts `missing` and is overwritten only by a row. With explicit Closed rows, a missing
    day really does mean the block is incomplete.
  - If a row's label doesn't expand, it is ignored, and the days it would have covered stay missing.
  - **Structured corroboration** from `weeklyHours`, rendered as `"HH:MM - HH:MM"` per day. When the
    component is present, a day absent from it is `"closed"`. This feeds the existing
    `structured_field` path, so a stale payload with correct visible hours is `METADATA_DRIFT`, never
    `MISMATCH`.
  - If `hoursType` is present and not `"NORMAL"`, the hours fields are `missing` with a note, so
    temporary or holiday hours can't raise a false MISMATCH.
  - `aria-label` is **not** used as a second strategy. It is the same template on the same node, so it
    adds no real independence and adds a comma-split failure mode. The shell-props payload is the
    independent source.
  - Hours checks `require` the `name` check.
- **Address** is out of scope. `normalize.street` doesn't handle Suite/Unit, and it only expands a
  street type that is the last token. Both are false-MISMATCH hazards, to fix in a follow-up.
- Register in `webwatch/run.py` `_BUILTINS`.

## Testing (fixture-based, no live HTTP)

- `tests/test_apple_maps.py`:
  - golden fixture → every check `OK`
  - hours rewritten (e.g. `12:00 PM – 5:00 PM`) → `MISMATCH`
  - a "Closed" row → `MISMATCH`
  - "ten-ish" → `PARSE_ERROR`
  - hours section removed → `STRUCTURE_CHANGED`
  - a day's row dropped → that day `STRUCTURE_CHANGED`
  - shell-props hours changed while visible hours are correct → `METADATA_DRIFT`
  - `hoursType` changed → `STRUCTURE_CHANGED`
  - embedded placeId changed → all `STRUCTURE_CHANGED`
  - phone changed → `MISMATCH`; phone cell removed → `STRUCTURE_CHANGED`
  - website changed → `MISMATCH`
  - a wrap-around "Sun – Mon" label parses
  - BLOCKED via `source.fetch(transport=…)` serving a challenge page
- `tests/test_run.py`:
  - the router serves the Apple fixture for `maps.apple.com`
  - a renamed place → `name` MISMATCH and hours gated `STRUCTURE_CHANGED`, not MISMATCH
- `tests/test_normalize.py`: `normalize.url`, plus the moved `expand_days` tests.

## Verification

1. `make test-module M=tests/test_apple_maps.py`, then `make quality && make test`.
2. `uv run webwatch list` shows `apple_maps` and its checks.
3. `uv run webwatch check --site apple_maps` against the live site reports all `OK`. `check` only
   prints results, so no email is involved.

## Follow-ups (not in this change)

- An address check for listing sites, once `normalize.street` handles units and street types that
  aren't the last token.
- When Google/Yelp are added, move listing URLs into a `listings:` section of `facts.yaml`. A
  listing's URL is a fact that changes when listings are merged.

## Review feedback incorporated (agy)

`make review-plan` first produced no output. agy's headless mode auto-denied the shell commands it
tried to run. `ls`/`cat`/`grep`/`rg`/`find`/`head`/`tail`/`wc` were added to agy's
`permissions.allow`. It still tried `python3`, which was deliberately left denied, so the review ran
with the relevant fixture markup inlined in the prompt. Findings:

- **#1 (blocker) identity guard vs. pure `observe`:** accepted. Replaced with `Check.requires`
  prerequisites (§2) plus a pure self-identity check on the embedded placeId (§3).
- **#2 (critical) strategies compared raw:** moot. The aria-label strategy was dropped. Corroboration
  goes through the normalizer in `check_field`.
- **#3 (high) "h3 with row descendants" is impossible:** accepted. The anchor is now the `section`
  titled "Hours" that contains rows.
- **#4 (high) aria-label is false independence and fragile:** accepted. It was replaced by the
  shell-props `weeklyHours` payload.
- **#5 (high) closed vs. omitted days:** resolved empirically. Apple renders explicit "Closed" rows
  (probed on a listing closed Tuesdays), and structured `weeklyHours` leaves closed days out.
- **#6 (medium) website:** accepted, with a small `normalize.url`.
- **#7 (medium) name selector ambiguity:** accepted. It reads `#axHeader h1.sc-header-title` that is
  not `aria-hidden`.
- **#8 (medium) `tel:` parsing:** avoided. The visible `.sc-phone-number` text is the value and the
  payload's `telephone` corroborates it. The `href` isn't parsed.
- **#9 (medium) no hours MISMATCH test; BLOCKED must go through `fetch`:** accepted.
- **#10 (low) verification wording:** accepted.

Open questions: dependencies are modeled as `Check.requires`. Closed days are explicit rows.
Shell-props is used, as corroboration.

## Implementation notes (pre-PR review)

The pre-PR reviewers (documentation, antipattern, clean-code, code-smell) led to these refinements:

- `PrerequisiteGate` lives beside `Check` in `webwatch/checks/registry.py`, not in `run.py`. It caches full results, so each check runs at most once. `register()` validates `requires` up front, and an unknown or circular prerequisite raises `ValueError` instead of turning into a misleading `STRUCTURE_CHANGED` at run time.
- `normalize.url` drops `utm_*` campaign parameters, so a listing that tags its outbound link can't raise a false `MISMATCH`. Any other query difference still counts.
- An empty `weeklyHours` list means "no corroboration", not "closed every day".
- The source-level place-id guard is documented as a coarse filter. The `name` prerequisite is the decisive identity check.
- Credential-like values were redacted from the committed fixture: Apple's origin-restricted MapKit client JWTs (flagged by detect-secrets), the `emailWidgetServiceKey`, and the snapshot-URL signatures (flagged in CodeRabbit review). Extraction doesn't use any of them.
