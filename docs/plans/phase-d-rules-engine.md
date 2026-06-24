# Phase D — Dynamic rules engine (recurring events)

## Context

`facts.yaml` carries a `weekly-repair-day` rule (`recurring_event`, Saturday, 10:00-16:00) that no
code evaluates yet. This phase adds the rules engine and checks that rule against the museum's
published events on the `/visit` page.

**Decisions confirmed with the user:** the `/visit` events are **real production data**, and the rule
should verify **presence + weekday + time** and **flag discrepancies**. This matters because the page
_currently_ shows the discrepancy webwatch exists to catch: the "Saturday Repair Day" event is dated
**Friday Jun 26** and every event shows an identical placeholder-looking **3:22 PM**. So against the
committed fixture, the repair-day rule will legitimately report a `MISMATCH` — that is the desired
behavior, not a test failure to paper over.

## What the `/visit` events look like (from the fixture)

No JSON-LD events. Each event is a card:

```html
<div class="... card ...">
  <div>...<span>Jun</span><span>26</span></div>
  <!-- date badge: month, day -->
  <div>
    <h4>Saturday Repair Day</h4>
    <!-- title -->
    <p>
      Friday<!-- -->
      ·
      <!-- -->3:22 PM<!-- -->
      · 108 N. State St., Suite 015
    </p>
    <!-- weekday · time · location -->
    <p>Learn pinball machine repair with our volunteers.</p>
    <!-- description -->
    <span>Recurring</span>
    <!-- recurring tag (optional) -->
  </div>
</div>
```

The stated weekday matches the date; the **time is unreliable** (all three events read 3:22 PM).

## Approach

1. **Event model + extraction** — a small `Event` (`title`, `weekday`, `time`, `recurring`, `month`,
   `day`, `description`) and an extractor that reads the event cards under the "Upcoming Events"
   heading. The meta line splits on the middot into weekday / time / location (the middot is built
   via `chr(0x00B7)` to avoid an ambiguous-unicode lint, like the dash class in `normalize`). Robust
   to missing pieces: an absent weekday/time becomes `""`, not a crash. Lives in `webwatch/events.py`
   (reusable; the homepage has the same cards).
   - **Self-review fix — don't grab the Hours card.** `div.card` also matches the hours card and
     others; an event card is discriminated by containing an `<h4>` title (the hours card uses
     `<h3>`). The extractor anchors near the "Upcoming Events" heading and treats an event card as a
     `.card` with an `<h4>`. If that yields nothing, events are reported missing (not silently empty).

2. **Observation carries events** — add `events: Observed[list[Event]]` to `Observation`. The `/visit`
   source populates it: `Observed.found([...])` when the events section is located (even if empty),
   `Observed.missing(...)` when the section/heading is gone. This keeps the honest found-vs-missing
   distinction for the whole events list.

3. **`webwatch/rules.py` — evaluate a rule against events** →
   `evaluate(rule, observed_events) -> CheckResult` (named by `rule.id`):
   - Events couldn't be read (`Observed.missing`) → `STRUCTURE_CHANGED` (we can't judge the rule).
   - `rule.enabled is False` → `SKIPPED`.
   - Find events matching the rule's keyword (a new `match:` field on the rule, e.g. `repair`,
     checked against title + description). **No match → `MISMATCH`** ("expected recurring event not
     found in the upcoming schedule") — per the user's flag-issues intent.
   - A match found (prefer one tagged `Recurring`): check **weekday** (`rule.weekday`) and **start
     time** (`rule.start`). Compare weekday via `normalize.text`; compare the event's listed time to
     `rule.start` via `normalize.time_to_minutes`. Any disagreement → `MISMATCH` with a precise
     detail ("weekday Friday, expected Saturday; time 15:22, expected 10:00"). All agree → `OK`. An
     event whose time text won't parse → `PARSE_ERROR`.
   - **Self-review fix — don't false-OK on a missing sub-field.** If the matched event's weekday or
     time text is empty (the card didn't show it), that aspect is unreadable → `STRUCTURE_CHANGED`,
     never a silent pass. Match by title first, description only as a fallback, to avoid loose
     keyword matches evaluating the wrong event.
   - **Time semantics (flag for review):** the rule's `start`/`end` describe the event window; the
     card shows a single time. We compare the card's time to `rule.start` (the start of the window),
     so a wrong/placeholder time is flagged. (3:22 PM happens to fall _inside_ 10:00-16:00, so a
     "within window" check would miss it — comparing to `start` is what surfaces the problem.)

4. **`match` field on the rule** — add `match: repair` to `weekly-repair-day` in `facts.yaml` so the
   engine knows which event(s) correspond. Document it in `docs/Facts.md`.

5. **Wire into the run** — `run_checks` evaluates the facts' enabled `recurring_event` rules against
   the events observed from the source that provides them (the `/visit` source). Rule results join
   the field results in the report; `--fact <rule.id>` can target one rule. A source advertises that
   it supplies events (e.g. a `provides_events = True` flag) so the wiring isn't hardcoded to one
   class.
   - **Self-review note — this flips the default run to "problem found."** Against the current
     fixture the repair-day rule is a real `MISMATCH`, so `webwatch check` will exit 1 by default and
     the "all OK" run tests must be updated: field checks stay OK, the rule is the expected MISMATCH.
     That is correct behavior (the site genuinely mis-lists the event), documented in the tests.

## Testing (`tests/test_rules.py`, `tests/test_events.py`, fixture-backed)

- **Event extraction** against the `/visit` fixture: three events with the right titles, weekdays,
  the (unreliable) time, and the `Recurring` tag on the repair day.
- **Rule evaluation, golden fixture:** the repair-day rule → `MISMATCH`, and the detail names both
  the weekday (Friday vs Saturday) and the time (15:22 vs 10:00). A comment documents that this
  reflects a real issue on the live site.
- **Positive path (synthetic events):** a "Saturday Repair Day" event dated Saturday with time
  "10:00 AM" → `OK`.
- **Missing event:** events present but none matching `repair` → `MISMATCH` ("not found").
- **Missing events section:** no "Upcoming Events" heading → `STRUCTURE_CHANGED`.
- **Disabled rule → `SKIPPED`; unparseable event time → `PARSE_ERROR`.**
- **Run wiring:** `run_checks` over the routing transport now includes a `weekly-repair-day` result
  alongside the field checks; exit code reflects the `MISMATCH` (exit 1).

## Verification

- `make quality` and `make test` green.
- `webwatch check --site theflip_museum_visit` reports the hours (OK) and the repair-day rule
  (`MISMATCH`, with the Friday/Saturday + time detail), exit 1 — demonstrating webwatch surfacing a
  real published-schedule discrepancy.
- `webwatch list` shows the rule check under the visit source.

## Notes / scope

- **No clock needed yet:** we judge the rule against the event's _stated_ weekday/time, not "now", so
  no `freezegun`/injected-clock machinery this phase. If we later check "does the next occurrence
  fall on the right date", a clock comes in then.
- Events extraction is written reusably so the homepage (same cards) can be checked later.

## Review feedback incorporated

Implemented with a self-review first (agy was down with HTTP 429 at the time): hours-card collision
(event cards discriminated by `<h4>`), missing sub-field → `STRUCTURE_CHANGED` not a silent pass, the
run-impact on the all-OK tests, and the `chr(0x00B7)` middot.

A later **`agy` review** (once the service recovered) found four more issues, all folded in:

- **P1 — empty schedule vs missing section:** a present-but-empty Upcoming Events section returned
  `None` (→ false `STRUCTURE_CHANGED`). `extract_events` now returns `None` only when the _heading_ is
  absent and `[]` when the heading is present with no cards, so a genuinely missing recurring event is
  a `MISMATCH`, not a false structural alarm.
- **P2 — matching:** keyword matching is now **whole-word** (`\bkeyword\b`), avoiding collisions like
  `"art"` in `"Party"`; and the engine evaluates **every** matching event, returning `OK` if any
  satisfies the rule (a wrong "Repair Prep" no longer fails a correct "Repair Day" listed later).
- **P3F2 — positional meta parsing:** the weekday and time are now identified by **content** (a part
  that names a weekday; a part that parses as a time), so a card that omits the time doesn't put the
  location into `event.time` and trigger a spurious `PARSE_ERROR`.

Two findings were considered and deliberately **not** changed:

- **P3F1 (cross-check the date badge's weekday against the stated weekday):** a real blind spot, but
  the [expired-events check](expired-events-check.md) already computes the date and treats a
  weekday/date inconsistency as indeterminate. Adding a second cross-check in the rule is a worthwhile
  follow-up, not done here to avoid overlap.
- **P4 (rule has an end but the event lists only a start → silently OK):** start-only event listings
  are common and legitimate, so hard-flagging a missing end would be a false-positive risk that cuts
  against the project's core value. We verify what the page shows; a missing end is not treated as a
  discrepancy. Recorded as a deliberate divergence.
