# Adding a Site, Source, and Checks

This is the recipe for extending webwatch to a new place The Flip appears. Read [Extraction.md](Extraction.md) first — the honesty rules there are non-negotiable. For anything beyond a trivial addition, write a plan in [plans/](plans/README.md) and have it `agy`-reviewed before coding.

## Vocabulary

- **Source** — one web page we monitor. A `Source` fetches its page **once** and returns an `Observation`: the facts it could read, each tagged with how it went (a value, or a "couldn't read" reason).
- **Check** — an assertion that compares one field of an `Observation` to a fact/rule and returns a `CheckResult`.

Sources do the reading; checks do the judging. Keep them separate so one fetch feeds many checks and site quirks stay out of the comparison logic.

## Steps

1. **Capture a golden fixture.** Run `uv run python scripts/capture_fixture.py <url> <source>` to save the page under `tests/fixtures/<source>_<date>.html`. Inspect it; don't guess the structure.

2. **Write the source** in `webwatch/sources/<site>.py`:
   - Subclass the `Source` base (`webwatch/sources/base.py`). Declare the page URL and the anchors each field depends on.
   - Extract via the [layered strategy](Extraction.md#layered-extraction-stable-signals-first): structured data (corroboration) + semantic anchors (authoritative). Use the primitives in `webwatch/extract/`.
   - Return an `Observation` whose fields are either a located value or an explicit "not found". Never an empty string standing in for a real value.
   - Expose `SOURCE` and `CHECKS` from the module and add the pair to `_BUILTINS` in `webwatch/run.py`, which registers both registries.

3. **Write the checks** in `webwatch/checks/`:
   - Compare the observed field to the relevant `facts.yaml` value, **through `normalize.py`**.
   - Map outcomes to `CheckStatus` honestly: read+matches → `OK`; read+differs → `MISMATCH`; field "not found" → `STRUCTURE_CHANGED`; unparseable → `PARSE_ERROR`; blocked/challenge → `BLOCKED`. A blank expected fact → `SKIPPED`.
   - Declare them as `Check(...)` specs in the source module's `CHECKS` (see `webwatch/checks/registry.py`). Weekly hours use the shared `hours_checks()`, and day labels go through `normalize.expand_days`.

4. **Add the facts** to `facts.yaml` (or a rule) — see [Facts.md](Facts.md). Leave values empty / `enabled: false` until verified.

5. **Write tests** in `tests/test_<site>.py` against the golden fixture, proving every status by [in-memory mutation](Testing.md#prove-every-status-by-mutation). This is required, not optional.

6. **Verify end-to-end:** `webwatch check --site <site>` against the fixture, and `make quality && make test`.

## Third-party listings (maps, review sites)

A listing page can quietly turn into a page about a different business: listings get merged, a place-id gets mistyped, or a search result resolves to the wrong place. Asserting hours against someone else's page would produce a burst of false `MISMATCH`es. Guard the identity twice (see `webwatch/sources/apple_maps.py`):

- **In the source (pure).** The page has to identify itself as the listing we asked for, e.g. its embedded place-id equals the one in `url`. If it doesn't, every field is `missing` → `STRUCTURE_CHANGED`.
- **In the checks (`Check.requires`).** Check the listing's `name` against `facts.yaml`, and give every other check `requires="name"`. If `name` is not `OK`, the run loop reports each dependent check as `STRUCTURE_CHANGED` ("prerequisite … did not pass") instead of asserting it. A prerequisite excluded by `--fact` is still evaluated, just not reported.
  - **Exception:** a field that says the listing is closed or unavailable (e.g. Google's `business_status`) is _not_ gated on `name`. A listing that's been renamed _and_ marked closed must still raise the closure. The source-level self-identity check still protects it. See `webwatch/sources/google_maps.py`.

Listing sites often embed their own place data as JSON (Apple's `shell-props`). Treat it as `structured` corroboration, exactly like JSON-LD: the visible value decides, and a stale payload is `METADATA_DRIFT`. Parse it defensively. If it has an unexpected shape, the result is "no corroboration", never a crash.

## Link-validity sources (a 404 is the answer)

Normally an HTTP 404 means we're fetching the wrong URL, so `fetch()` raises and the run reports `FETCH_ERROR`. Apple Maps works this way, where an unknown place-id is our mistake. Some sources exist to answer "does this URL still exist?", such as the Square donation link (`webwatch/sources/square_donation.py`). For those sources, a 404 is the finding, and reporting it as "couldn't fetch" would send triage the wrong way. Such a source:

- sets `accept_statuses = frozenset({404, 410})`, so `fetch()` returns those responses instead of raising. Block detection still runs first, so a challenge served as a 404 is still `BLOCKED`, and 5xx/network errors still retry and end as `FETCH_ERROR`;
- overrides `observe_not_found(result)` to read an accepted status. Defining a source that sets `accept_statuses` without this override raises `TypeError`, so an accepted 404 can never fall through to `observe`. Every other response goes to the usual pure `observe(html)`.
- reports the "gone" value (e.g. `"not found (HTTP 404)"` → `MISMATCH`) only when the body is the site's own not-found page. A bare 404 with an unrecognized body (CDN or routing glitch) is `missing` → `STRUCTURE_CHANGED`.

Use this only when the URL's existence is the fact being checked. Test the 404 path with an in-memory response: `capture_fixture.py` deliberately won't save a non-2xx page as a golden fixture.

## API-backed sources

When a site only renders with JavaScript, use its official API if it has one (Google Maps → Places API). Override `request_headers()` to send the credential, and raise `FetchError` if it isn't configured. Capture a real response with `scripts/capture_fixture.py --source <name>`. See [Extraction.md](Extraction.md#blocked-and-js-rendered-pages) for how the status mapping carries over.

## Don'ts

- Don't anchor on positional CSS paths (`div:nth-child(3) > span`). Anchor on labels, microformats, roles, or structured data.
- Don't let a missing element become a silent `None` that flows into a comparison — that is how false alarms and silent misses are born.
- Don't fetch inside a check. Don't compare with raw `==`. Don't trust JSON-LD over visible text.
