# Adding a Site, Source, and Checks

This is the recipe for extending webwatch to a new place The Flip appears. Read [Extraction.md](Extraction.md) first — the honesty rules there are non-negotiable. For anything beyond a trivial addition, write a plan in [plans/](plans/README.md) and have it `agy`-reviewed before coding.

## Vocabulary

- **Source** — one web page we monitor. A `Source` fetches its page **once** and returns an `Observation`: the facts it could read, each tagged with how it went (a value, or a "couldn't read" reason).
- **Check** — an assertion that compares one field of an `Observation` to a fact/rule and returns a `CheckResult`.

Sources do the reading; checks do the judging. Keep them separate so one fetch feeds many checks and site quirks stay out of the comparison logic.

## Steps

1. **Capture a golden fixture.** Run `uv run python scripts/capture_fixture.py <url>` to save the page under `tests/fixtures/<source>_<date>.html`. Inspect it; don't guess the structure.

2. **Write the source** in `webwatch/sources/<site>.py`:
   - Subclass the `Source` base (`webwatch/sources/base.py`). Declare the page URL and the anchors each field depends on.
   - Extract via the [layered strategy](Extraction.md#layered-extraction-stable-signals-first): structured data (corroboration) + semantic anchors (authoritative). Use the primitives in `webwatch/extract/`.
   - Return an `Observation` whose fields are either a located value or an explicit "not found". Never an empty string standing in for a real value.
   - Register it in `webwatch/sources/registry.py`.

3. **Write the checks** in `webwatch/checks/`:
   - Compare the observed field to the relevant `facts.yaml` value, **through `normalize.py`**.
   - Map outcomes to `CheckStatus` honestly: read+matches → `OK`; read+differs → `MISMATCH`; field "not found" → `STRUCTURE_CHANGED`; unparseable → `PARSE_ERROR`; blocked/challenge → `BLOCKED`. A blank expected fact → `SKIPPED`.
   - Register the `(source, fact)` mapping in `webwatch/checks/registry.py`.

4. **Add the facts** to `facts.yaml` (or a rule) — see [Facts.md](Facts.md). Leave values empty / `enabled: false` until verified.

5. **Write tests** in `tests/test_<site>.py` against the golden fixture, proving every status by [in-memory mutation](Testing.md#prove-every-status-by-mutation). This is required, not optional.

6. **Verify end-to-end:** `webwatch check --site <site>` against the fixture, and `make quality && make test`.

## Don'ts

- Don't anchor on positional CSS paths (`div:nth-child(3) > span`). Anchor on labels, microformats, roles, or structured data.
- Don't let a missing element become a silent `None` that flows into a comparison — that is how false alarms and silent misses are born.
- Don't fetch inside a check. Don't compare with raw `==`. Don't trust JSON-LD over visible text.
