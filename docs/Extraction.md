# Extraction Doctrine

This is the most important document in the project. Read it before writing any code that reads a web page. Webwatch's value rests entirely on extracting honestly: reporting _that we could not read a page_ instead of guessing, and only ever claiming the world is wrong when we genuinely read a wrong value.

## The problem

Naive scrapers conflate three outcomes:

1. The value is present and correct.
2. The value is present but wrong.
3. The value could not be read at all (page redesigned, blocked, JS-only, malformed).

A scraper that treats (3) like (1) **silently passes** — a false negative (we miss that the address actually changed). A scraper that treats (3) like (2) **cries wolf** — a false positive (it screams "the address is wrong!" when really the page was restructured and the old selector now returns empty). Both train operators to ignore the tool. Avoiding both is the entire job.

## `CheckStatus`: the eight outcomes

Defined in [`webwatch/result.py`](../webwatch/result.py). Every check returns exactly one:

| Status              | Meaning                                                           | Routes to        |
| ------------------- | ----------------------------------------------------------------- | ---------------- |
| `OK`                | Value read with confidence; matches the fact (after normalize)    | exit 0           |
| `MISMATCH`          | Value read with confidence; **differs** from the fact             | exit 1 (data)    |
| `STRUCTURE_CHANGED` | Region could not be located, or strategies disagreed              | exit 2 (checker) |
| `PARSE_ERROR`       | Region located, but value un-modelable into the canonical type    | exit 2 (checker) |
| `BLOCKED`           | CAPTCHA / challenge / login wall / bot block / empty JS shell     | exit 2 (checker) |
| `FETCH_ERROR`       | Could not fetch the page (network/HTTP, after retries)            | exit 2 (checker) |
| `METADATA_DRIFT`    | Visible value is correct, but structured metadata (JSON-LD) stale | exit 2 (checker) |
| `SKIPPED`           | Disabled, not applicable, or a field the source never publishes   | exit 0           |

**`MISMATCH` is the only status that asserts the world is wrong.** Produce it only when a value was genuinely located and read. If you are tempted to return `MISMATCH` because an element was missing or empty, you want `STRUCTURE_CHANGED`.

## The cardinal rule

> An extractor must always distinguish **"I found the region and the value is X"** from **"I couldn't find the region at all."**

Concretely, an extraction primitive returns either a located value or an explicit "not found" — never an empty string or `None` that a caller might mistake for a real value. A missing region becomes `STRUCTURE_CHANGED`; it never flows into a comparison.

## Layered extraction (stable signals first)

Prefer the most stable signals, but **structured data corroborates — it does not decide**:

1. **Structured data** — JSON-LD / schema.org (`LocalBusiness`, `PostalAddress`, `openingHours`, `Event`) via `extruct`, in [`webwatch/extract/structured.py`](../webwatch/extract/structured.py). Machine-intended and stable, **but** frequently plugin- or SEO-managed and left stale while admins edit only the visible page. So it is never trusted alone.
2. **Semantic anchors** — locate visible values by label text ("Hours", "Address"), microformats (h-card / h-event), or stable roles, in [`webwatch/extract/anchors.py`](../webwatch/extract/anchors.py). **Not** `nth-child` or long CSS paths — those break on any redesign and are exactly the brittleness we are avoiding.
3. **Mandatory corroboration** — when a fact appears in both structured data and visible text, the comparison is driven by the **visible** value (it is what humans see):
   - `visible != expected` → `MISMATCH` (regardless of JSON-LD).
   - `visible == expected` but JSON-LD disagrees → `METADATA_DRIFT` — the visible info is correct, so this is **not** a `MISMATCH`; the stale metadata is still worth fixing (it can mislead search engines).
   - `visible == expected` and JSON-LD agrees or is absent → `OK`.

   This closes the "silent drift" blind spot without crying wolf when only the metadata is stale.

4. **Declared anchors** — each source declares the anchors it depends on. If they vanish, the source returns `STRUCTURE_CHANGED` for the affected fields rather than guessing.

## Normalization before comparison

Compare through [`webwatch/normalize.py`](../webwatch/normalize.py), never with raw `==`. Cosmetic differences — whitespace, `Street` vs `St`, `(555) 123-4567` vs `+15551234567`, `9 AM–5 PM` vs `09:00–17:00`, timezone rendering — are not mismatches. Normalize **both** the expected fact and the observed value, then compare. A raw string comparison in a check is a code smell.

## Blocked and JS-rendered pages

`fetch.py` retrieves static HTML via `httpx`. Some pages return a 200 that is actually a Cloudflare challenge, a login wall, or an empty React/Vue shell that only populates after client-side hydration. Detect these and return `BLOCKED` — an access problem distinct from a layout change, so triage isn't sent chasing phantom selector bugs. `fetch.py` keeps a transport seam so a JS-rendering fetcher (e.g. Playwright) or an official API can be plugged in per-source later. The Flip's own site is server-rendered; we cross that bridge when a JS-only site is added.

## Breakage detection

The point of committing a golden HTML fixture per source (see [Testing.md](Testing.md)) is that when a site changes, we re-capture the fixture and the extractor's tests immediately show what broke — surfacing `STRUCTURE_CHANGED` as a failing test in CI rather than a false alarm in production. Re-capturing a fixture is how we _notice_ a site changed; the status taxonomy is how we _report_ it without lying.

## Checklist when adding or changing an extractor

- [ ] Does it return an explicit "not found" rather than an empty value?
- [ ] Are anchors semantic/stable, not positional CSS paths?
- [ ] Is structured data corroborated against visible text, with visible text winning?
- [ ] Does a missing region yield `STRUCTURE_CHANGED` (not `MISMATCH`, not a guess)?
- [ ] Does an unparseable value yield `PARSE_ERROR`?
- [ ] Do comparisons go through `normalize.py`?
- [ ] Are there mutation tests proving each negative status from the golden fixture?
