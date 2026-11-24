# Plan — Holiday hours check (Google / Apple Maps)

> **Status: draft, not yet reviewed or implemented.** This plan covers the follow-up to
> [website-holiday-hours.md](website-holiday-hours.md), which shipped the website checks first.
> It also needs the Apple findings from 2026-11-24: Apple's `SPECIAL` business-hours value, and the
> fact that the current regular-hours parser happens to work despite reading the special-week rows.

## Context

The museum keeps special hours on five holidays:

| Holiday        | Date                     | Hours         |
| -------------- | ------------------------ | ------------- |
| Thanksgiving   | 4th Thursday of November | closed        |
| Christmas Eve  | Dec 24                   | 10:00 - 15:00 |
| Christmas      | Dec 25                   | closed        |
| New Year's Eve | Dec 31                   | 10:00 - 15:00 |
| New Year's Day | Jan 1                    | closed        |

Visitors check maps listings for hours on these days, so a listing that shows the museum open on
Thanksgiving sends people to a locked door. webwatch only checks _regular_ weekly hours today, and
the Google source reads `regularOpeningHours`, which deliberately excludes holidays.

### What the sources actually publish (inspected live on 2026-11-24, two days before Thanksgiving)

- **theflip.museum `/visit` and homepage:** no holiday hours anywhere. Nothing to read.
- **Apple Maps:** `hoursType: "NORMAL"`, no special-hours data in the visible page or the
  `shell-props` payload. We have no sample of what Apple's payload looks like when special hours are
  set, so we can't model it yet.
- **Google Places API:** `currentOpeningHours` gives the hours for the **next seven days** (today
  included) with each period's `open`/`close` carrying a calendar `date`, plus `specialDays`
  listing dates in that window that have exceptional hours. **Right now it shows Thursday
  2026-11-26 (Thanksgiving) open 10:00–20:00 and has no `specialDays`** — the listing is wrong today,
  which is a live demonstration of the value of this check.

So Google is the only source we can check honestly. The Places API cannot see past seven days.
That limit sets how much warning we can give (see "Lead time" below).

## Approach

### 1. Facts: `organization.holiday_hours`

```yaml
organization:
  holiday_hours:
    thanksgiving: closed
    christmas_eve: '10:00 - 15:00'
    christmas: closed
    new_years_eve: '10:00 - 15:00'
    new_years_day: closed
```

- Keys come from a **fixed vocabulary** of named holidays (below). An unknown key raises
  `FactsError`, so a typo like `christmass` fails loudly at load instead of silently never checking.
- Values use the same grammar as weekly hours (`normalize.day_hours`), so `closed`, range strings,
  `{open, close}` maps, and lists all work. Values are validated at load by parsing them with
  `normalize.day_hours`. A malformed value raises `FactsError`, so it can't later appear as a
  per-run `PARSE_ERROR` that looks like Google's fault.
- A blank value (`""`) means "not verified" and reports `SKIPPED`, as with every other fact.
- **Why a static fact, not a `rules:` entry:** rules are evaluated against a source's _events list_.
  Holiday hours are an expected value for a field, compared through `normalize.day_hours` exactly
  like `hours.<day>`. Their date depends on the year, but they are still facts. `Facts.md` mentions
  seasonal hours as a possible future rule type; this plan notes in `Facts.md` why holiday hours went
  under `organization` instead.

### 2. `webwatch/holidays.py` — named holidays → dates (pure)

```python
HOLIDAYS: dict[str, Callable[[int], dt.date]] = {
    "thanksgiving": lambda year: nth_weekday(year, 11, THURSDAY, 4),
    "christmas_eve": lambda year: dt.date(year, 12, 24),
    "christmas": lambda year: dt.date(year, 12, 25),
    "new_years_eve": lambda year: dt.date(year, 12, 31),
    "new_years_day": lambda year: dt.date(year, 1, 1),
}

def next_occurrence(holiday: str, today: dt.date) -> dt.date  # on or after today
```

`next_occurrence` tries `today.year` then `today.year + 1`, so New Year's Day seen from Dec 26 is the
coming Jan 1. A small vocabulary, not a date DSL: if the museum adds a holiday, adding one line here
is cheaper and clearer than a general recurrence grammar. Adding a key requires a test for its date.

### 3. Google source: observe the dated week (pure)

- Add `currentOpeningHours` to `_FIELD_MASK`.
- New `Observation.dated_hours: Observed[DatedHours]`, defaulting to `not_supported`, beside
  `events`. `DatedHours` is a small frozen dataclass:
  - `days: dict[dt.date, str]` holds the dates that have periods, as `"HH:MM - HH:MM"` text (several
    windows comma-joined, overnight periods credited to their **open** date, as in the existing
    weekly parser).
  - `special_days: frozenset[dt.date]` holds the dates Google flags as exceptional.

  The source stays **pure**: it reads only dates the response states and does not consult a clock.

- Reuse `_point` and the period validation from the weekly parser. Factor the shared
  period → window logic out rather than duplicating it.
- Honesty mapping (in the source):
  - `currentOpeningHours` absent → `dated_hours` **missing** (`STRUCTURE_CHANGED`). We can't tell
    "no data" from a field-mask or schema change.
  - Present but unmodeled (a point without a `date`, a period spanning more than a day, a
    malformed date, `truncated`) → **unparseable** (`PARSE_ERROR`).
  - Always-open shape → unparseable. The museum is not 24h, and guessing here is worse than
    reporting.
  - The existing place-`id` identity check also applies: wrong place → `missing`.

### 4. The check: `check_holiday_hours(observation, facts, *, now, site)` (clock-injected)

This follows the `expired_events` precedent: a clock-dependent check that lives outside the
`Check` registry (whose `run(observation, facts)` has no clock), wired in `run.py` for sources that
declare `provides_dated_hours = True`. It produces **one result per configured holiday**, named
`holiday_hours.<holiday>`, so Christmas Eve and Christmas in the same window are judged and alerted
independently.

For each holiday, with `today = now.date()` in `config.TIMEZONE` (America/Chicago, which is also
the place's timezone, so our "today" and Google's agree):

1. Blank expected → `SKIPPED`.
2. `date = next_occurrence(holiday, today)`. If `date > today + 5` → `SKIPPED`, with summary
   `"next on 2026-12-24; Google publishes hours only 7 days ahead"`. **Why +5 and not +6:** this
   leaves a one-day margin at the far edge of Google's seven-day window. Near midnight, or if
   Google's window is computed slightly differently, the last day may not be covered yet. An
   uncovered day has no period, and reading "no period" as "closed" would be a false `OK` for a
   closed holiday, or a false `MISMATCH` for an open one.
3. `dated_hours` not found → `STRUCTURE_CHANGED` / `PARSE_ERROR` per its reason (via the existing
   `Observed` → status mapping).
4. **Window sanity:** if no period date lies within `[today - 1, today + 7]`, the response doesn't
   describe this week → `STRUCTURE_CHANGED`. This guards against a stale or cached response, or a
   timezone mix-up, being read as "every day closed".
5. Observed value = `days[date]` if present, else `"closed"`. The date is inside the covered window
   and has no period, which is how Google represents a closed day.
6. Compare through `check_field`/`normalize.day_hours` → `OK` / `MISMATCH`.
   - On `MISMATCH`, if `date not in special_days`, the summary says so:
     `"Google shows regular hours; no special hours set for Thanksgiving (2026-11-26)"`. This tells
     the human the fix is "add special hours in Google Business Profile", not "Google's data is
     corrupt".

Per-holiday `MISMATCH` comes only from a value actually read for a date inside the covered window.
Everything else is `SKIPPED` (out of window or unverified) or a checker condition. No guessed values.

### 5. Wiring, listing, reporting

- `run.py`: for `provides_dated_hours` sources, run `check_holiday_hours` and honor
  `--fact holiday_hours.<name>`. A `FetchError` yields `FETCH_ERROR` for each holiday name, like
  `expired_events`. **Gate on `name`:** if the Google source's `name` check isn't `OK`, holiday
  results are `STRUCTURE_CHANGED` ("prerequisite 'name' did not pass"), matching the other
  hours checks. This reuses the gate's evaluated `name` result rather than re-implementing it.
- `webwatch list` shows the holiday checks for `google_maps`.
- `report.py`: the five `holiday_hours.*` checks share one digest row, "holiday hours", showing the
  worst, as the seven `hours.*` share one.

### 6. Docs

- `Facts.md`: the `holiday_hours` schema, the vocabulary, and why it's a fact and not a rule.
- `Checks.md` / `google_maps.py` docstring: `currentOpeningHours`, the seven-day limit and margin, and
  the `specialDays` hint.
- `Operations.md`: note that holiday checks are `SKIPPED` most of the year and active in the five or
  six days before each holiday.

## Lead time — the honest limitation

Google's public API only shows seven days ahead. With the window margin and
`ALERT_AFTER_FAILURES = 2` on a daily cron, the **first alert lands about 4–5 days before** a
holiday. That is enough to fix a listing, but not much. A listing fixed late still produces one
alert, which clears on recovery.

Options for more warning, **not** in this plan:

- **Google Business Profile API** (owner OAuth) exposes `specialHours` for any future date. This
  gives real lead time, but needs OAuth, a verified owner account, and API-access approval. It is a
  separate source and its own plan.
- **Apple Maps:** once special hours are set in Apple Business Connect, capture a fixture and model
  Apple's payload. We'd add an Apple holiday check then, from a real sample, not a guess.

## Adjacent risk (flagged, not changed here)

`apple_maps.py` reports **every** regular-hours check `STRUCTURE_CHANGED` while Apple's `hoursType`
isn't `NORMAL`. If Apple flips `hoursType` when holiday hours are set, the Apple hours checks will
alert during holiday weeks. We don't know Apple's behavior yet. The fixture captured for the Apple
follow-up will tell us. Until then this is a known possible false alarm, not a silent miss.

## Testing

Fixture: capture `google_maps` now with the new field mask
(`scripts/capture_fixture.py --source google_maps`). Thanksgiving falls in today's window, so the
fixture is a real example of the current, wrong-for-Thanksgiving state. Every other case comes from
**in-memory mutation** of that fixture, per `Testing.md`. The clock is pinned in every test.

- **`holidays.py`:** Thanksgiving dates for several years, including 2026-11-26 and a year when
  November 1 is a Thursday (2029-11-22). Fixed dates. `next_occurrence` across the year boundary
  (Dec 26 → next Jan 1) and on the holiday itself (today → today).
- **`facts.py`:** unknown holiday key → `FactsError`; unparseable hours → `FactsError`; blank
  allowed; section absent → no holiday checks; not a mapping → `FactsError`.
- **Source (pure):** fixture → `dated_hours` has seven-ish dated entries with the right text;
  `currentOpeningHours` removed → missing; a period's `date` removed → unparseable; overnight
  period credited to the open date; a closed date simply absent from `days`; `specialDays` parsed.
- **Check, against the fixture, now = 2026-11-24 Chicago:**
  - Thanksgiving expected `closed`, Google shows 10–20 → **`MISMATCH`**, summary mentions no
    special hours set.
  - Mutate: remove the Nov 26 period and add it to `specialDays` → **`OK`**.
  - Mutate the Nov 26 period to 10:00–15:00 with expected `10:00 - 15:00` → **`OK`**; to 10–16 →
    **`MISMATCH`**.
  - Christmas/NYE/NYD/Christmas Eve → **`SKIPPED`** (out of window), summary names the date.
  - Holiday exactly at `today + 5` → judged; at `today + 6` → `SKIPPED` (margin).
  - All periods shifted a month back (stale response) → **`STRUCTURE_CHANGED`**.
  - `dated_hours` missing / unparseable → `STRUCTURE_CHANGED` / `PARSE_ERROR`.
  - Blank expected → `SKIPPED`.
- **Run loop:** wrong place `name` → holiday results `STRUCTURE_CHANGED` (gated); fetch error →
  `FETCH_ERROR` per holiday; `--fact holiday_hours.thanksgiving` runs only that one; a source
  without `provides_dated_hours` gets no holiday results.
- **Report:** holiday checks collapse to one "holiday hours" digest row.

## Verification

- `make quality` and `make test` green.
- `webwatch check --site google_maps` live (manual, not in the suite) shows
  `holiday_hours.thanksgiving` `MISMATCH` today and the other four `SKIPPED` with their dates.
- `webwatch list` shows the five holiday checks under `google_maps`.
