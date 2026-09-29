# Plan — Google Maps listing via the Places API (name, website, phone, hours, business status)

## Context

After Apple Maps (`docs/plans/apple-maps-source.md`), Google Maps is next on `todo.md`. It's the
listing most visitors see. Unlike Apple, Google Maps **cannot be read as a page**. A static fetch of a
place URL returns ~190 KB of JavaScript with no name, phone or hours, and scraping Maps also
violates Google's terms. The honest, stable route is Google's **official Places API (New) — Place
Details**. The owner chose this route and is creating a Google Cloud project and API key.

This is the first source that reads an **API rather than a page**, and the first that needs a
**secret**. Those two things drive most of this plan.

## The API (from Google's docs, verified 2026-09-28)

- `GET https://places.googleapis.com/v1/places/{PLACE_ID}`. The key goes in the `X-Goog-Api-Key`
  header and the field list in `X-Goog-FieldMask`. The mask is mandatory: omitting it is an error.
- Fields we request, with the SKU each one triggers:
  - `id`: Essentials IDs Only
  - `displayName`, `businessStatus`: Pro
  - `nationalPhoneNumber`, `websiteUri`, `regularOpeningHours`: Enterprise
- A request bills at its highest SKU, Enterprise. One call a day is ~30 a month, well inside the free
  monthly usage Google has granted per Core Services SKU since March 2025.
- `regularOpeningHours.periods[]`: each has `open` and optional `close` Points with `day` (0 =
  Sunday … 6), `hour`, and `minute`. A day with no period is closed. "Always open" is a single `open`
  at day 0 00:00 with no `close`. `regularOpeningHours` excludes `specialDays` (holiday exceptions),
  so holidays can't cause a false MISMATCH. Apple needed an explicit guard for that.
- `businessStatus`: `OPERATIONAL | CLOSED_TEMPORARILY | CLOSED_PERMANENTLY | FUTURE_OPENING |
BUSINESS_STATUS_UNSPECIFIED`.
- Fields with no data are left out of the response.

## Approach

### 1. Secret and config

- `webwatch/config.py`: `GOOGLE_PLACES_API_KEY: str = config("WEBWATCH_GOOGLE_PLACES_API_KEY", default="")`.
  Add it to `.env.example`, commented with setup steps.
- The key only ever travels in a request **header**, never the URL. So it can't leak into
  `FetchError` messages, logs or reports. A test asserts the key doesn't appear in the text of a
  `FETCH_ERROR` result.
- **Key not set →** `GoogleMaps.fetch` raises `FetchError("WEBWATCH_GOOGLE_PLACES_API_KEY is not
set")` before any request. The run loop already maps that to one `FETCH_ERROR` per check: exit 2,
  and _unhealthy_ in `state.py`, so a broken deployment alerts. `SKIPPED` would count as healthy and
  quietly clear an active alert (agy #2). The other sources are unaffected.

### 2. Fetch boundary: request headers

- `fetch(url, *, headers=None, …)` merges extra headers over the User-Agent. This is the only change
  to `fetch.py`, and all HTTP still goes through it.
- `Source` gets `request_headers() -> dict[str, str]`, default `{}`, which `Source.fetch` passes on.
  This is the "transport seam for an official API" that `docs/Extraction.md` anticipated.
- `looks_blocked` runs unchanged. A JSON body has no challenge markers or JS mount node.
- HTTP errors keep their existing meaning:
  - 403 (bad or unauthorized key, API disabled) and 400 → `FetchError` → `FETCH_ERROR`. `fetch.py`
    currently drops the response body. For a **non-HTML** error response it now appends a short
    snippet of the body (whitespace-collapsed, ≤200 characters) to the `FetchError` message, so
    Google's `PERMISSION_DENIED` / "API key not valid" reason is visible. HTML error pages stay as
    they are. The key is never in a URL or a response body.
  - 429 and 5xx retry, as today.
  - 404 (the place-id no longer exists) → `FETCH_ERROR`. Google's docs say place IDs can be retired,
    and the note tells the operator to refresh the ID.

### 3. `webwatch/sources/google_maps.py`: `GoogleMaps(Source)`

- `url = "https://places.googleapis.com/v1/places/<PLACE_ID>"`. The owner finds the place ID with
  Google's Place ID Finder, and it's hardcoded like the other sources.
- `request_headers()` returns the key and the field mask
  `id,displayName,businessStatus,nationalPhoneNumber,websiteUri,regularOpeningHours`.
- `observe(text)`:
  - The body isn't a JSON object → every field `unparseable` → `PARSE_ERROR`.
  - **Self-identity:** the response `id` must equal the requested place ID. Otherwise every field is
    `missing`.
  - Fields:
    - `name` ← `displayName.text`
    - `url` ← `websiteUri`, compared with `normalize.url`
    - `phone` ← `nationalPhoneNumber`, compared with `normalize.phone`
    - `business_status` ← `businessStatus`
    - `hours.<day>` ← `regularOpeningHours.periods`, rendered as `"HH:MM - HH:MM"` windows
      (comma-joined) under the **opening** day, `"closed"` for days with no period. Google numbers
      days **0 = Sunday**, so an explicit `_GOOGLE_DAYS` table maps them; we never index
      `normalize.WEEKDAYS` with Google's number. Points are read with `.get(k, 0)` for `day`, `hour`
      and `minute`, because proto3 JSON leaves out zero values (Sunday, 10:00), and each must be an int.
  - There is no visible/structured split. The API _is_ Google's canonical data, so values are the
    observation and there is no `METADATA_DRIFT` path. This is recorded in the module docstring and in
    `docs/Extraction.md`.
- **Absent fields.** A missing `nationalPhoneNumber`, `websiteUri`, `displayName`, `businessStatus`
  or `regularOpeningHours` → `missing("<field> omitted from Places API response")` →
  `STRUCTURE_CHANGED`. We can't tell "not listed" apart from a field-mask or schema change, and
  `MISMATCH` must only come from a value we actually read (agy #1). A listing that loses its hours
  still alerts, as a checker problem with a clear note.
- **Hours shapes:**
  - Always open (a single `open` at day 0 00:00 with no `close`) → `"00:00 - 00:00"` for all seven
    days. That normalizes to a full-day window, so it compares honestly: The Flip's hours would
    `MISMATCH`, never become six false "closed" days.
  - **Overnight** (`close` on the next day) → `"17:00 - 02:00"`, which `normalize.time_range` already
    handles.
  - Anything else → every hours field `unparseable` → `PARSE_ERROR`, never a guessed partial week. That
    covers a `close` more than one day later, a missing `close` outside the always-open shape,
    `truncated` points, and a non-int day, hour or minute.
- Checks:
  - `name`, compared with `normalize.text`
  - `business_status` vs a **new fact** `organization.business_status: 'operational'` in
    `facts.yaml` (model it in `facts.py`, document it in `docs/Facts.md`; blank → `SKIPPED` as usual),
    compared with `normalize.text`. A listing marked closed is the worst thing Google could show, and
    if the museum ever closes temporarily, the fact is edited, not the code (agy #4A).
    **Not** gated on `name`: a renamed listing that is _also_ marked closed must still raise the
    closure. The `id` self-identity check already guards against a wrong place (agy #4B).
  - `url`, `phone`, `hours_checks()`, all with `requires="name"`, reusing Apple's `Check.requires` gate.

### 4. Fixture capture

`scripts/capture_fixture.py` gains a `--source NAME` mode next to the existing positional
`<url> [name]` mode. It looks the source up via `run.register_builtins()` and fetches with its `url`
and `request_headers()`, so the key comes from `.env`. The file extension follows the response's
content type: `.json` for JSON, `.html` otherwise. The key is never in the response. Until the owner's key exists, tests run against a fixture built from the
documented schema, and **the PR stays a draft until a real captured response replaces it**.

## Testing (no network, no key)

- `tests/test_google_maps.py`:
  - golden → all `OK`
  - mutations of the parsed JSON:
    - hours changed → `MISMATCH`
    - a day's period removed → that day `MISMATCH` (closed ≠ open)
    - `regularOpeningHours` removed → hours `STRUCTURE_CHANGED`
    - phone or website removed → `STRUCTURE_CHANGED`
    - Sunday period with `day`/`minute` omitted (proto3 zero) → still `OK`
    - overnight close → read as `"HH:MM - 02:00"` → `MISMATCH`, not `PARSE_ERROR`
    - always-open → all seven days `MISMATCH`, none "closed"
    - phone or website changed → `MISMATCH`
    - `businessStatus: CLOSED_PERMANENTLY` → `MISMATCH`, even when `name` also mismatches
    - a close more than a day later → all hours `PARSE_ERROR`
    - `id` mismatch → all `STRUCTURE_CHANGED`
    - a name for a different business → the rest gated (in `test_run`)
    - non-JSON body → `PARSE_ERROR`
- The key is unset → all `FETCH_ERROR`, and no HTTP request is made (a transport that fails the test
  if it's called).
- Headers: the mock transport asserts `X-Goog-Api-Key` and `X-Goog-FieldMask` are sent and that the
  URL has no `key=`.
- 403 → `FETCH_ERROR` whose detail includes Google's error reason and doesn't contain the key.
- `tests/test_fetch.py`:
  - extra headers merge with the User-Agent
  - a JSON error body is summarized in `FetchError`
  - an HTML error body is not

## Verification

1. `make quality && make test`.
2. Once the key is set locally: capture the fixture, then run `uv run webwatch check --site
google_maps` against the live API.
3. Deploy: add `WEBWATCH_GOOGLE_PLACES_API_KEY` to `.env` on alfred (owner, by hand), then pull.

## Owner setup (Google Cloud)

1. Create or choose a Cloud project, enable billing, and enable **Places API (New)**.
2. Create an API key. Restrict it by API to **Places API (New)** only.
3. Put it in `.env` as `WEBWATCH_GOOGLE_PLACES_API_KEY=…`, locally and on alfred. Never paste it
   into chat or commit it.
4. Find the place ID with Google's Place ID Finder.

## Out of scope / follow-ups

- Address (same `normalize.street` Suite/Unit gap as Apple).
- Overnight hours modeling.
- `specialDays` holiday-hours checks.
- A `listings:` section in `facts.yaml` for place IDs.

## Review feedback incorporated (agy)

agy reviewed the first draft ("requires major revision"). Every finding was accepted:

- **#1 Absent field as `MISMATCH`:** reversed. Absent → `STRUCTURE_CHANGED`, with no sentinels.
- **#2 Unset key as `SKIPPED`:** reversed. `SKIPPED` counts as healthy in `state.py` and would clear
  alerts, so the key being unset → `FETCH_ERROR`.
- **#3A Always-open:** all seven days get a full-day window. Before, one `PARSE_ERROR` plus six false
  "closed" days.
- **#3B Overnight:** modeled. Before, it was a `PARSE_ERROR`, which hid a real discrepancy.
- **#3C Day numbering (Google 0 = Sunday):** an explicit mapping table.
- **#3D Proto3 zero omission:** `.get(k, 0)` for day, hour and minute.
- **#4A `business_status` hardcoded:** it's now a fact in `facts.yaml`.
- **#4B `business_status` gated on name:** no longer gated, so a closure is never hidden. The
  place-`id` self-identity check still applies.
- **#4C `FetchError` drops the body:** a non-HTML error body is now summarized.
- **#4D Capture script:** a `--source` mode, with the extension taken from the content type.

## Implementation notes (after capturing the real response)

The real response (`tests/fixtures/google_maps_2026-09-28.json`, captured 2026-09-28) replaced the
schema-based stand-in. It matched our model: Sunday is day 0, and every point has explicit zeros.
Hours, phone and business status agree with `facts.yaml`. It also exposed two false alarms, which
the owner decided as follows:

- **Name.** Google lists the museum as "The Flip: Chicago's Playable Pinball Museum". The owner
  confirmed that's intended. `facts.yaml` gained `organization.listing_names`, and listing name
  checks (Apple and Google) pass on `name` or any listed alternative, matched exactly after
  normalization (`checks.base.AnyOf`). Without this, the name gate would have hidden every other
  Google check.
- **Website.** Google links to `https://theflip.museum/`, which 301s to `https://www.theflip.museum/`.
  `normalize.url` now ignores a leading `www.`, since the bare domain and its `www.` form serve the
  same site. Any other difference in scheme, domain, path or query still mismatches.
