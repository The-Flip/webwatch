# Plan — Website holiday hours: posted in time, removed afterwards

## Context

The museum's holiday hours are: closed on Thanksgiving, Christmas, and New Year's Day; open 10:00–15:00 on Christmas Eve and New Year's Eve. The website now publishes them in two places:

- **`/visit`, visible.** A "Holiday Hours" `<h4>` sits _inside_ the existing Hours card. Its rows use the same two-span layout as the regular hours ("Thanksgiving / Closed", "Christmas Eve / 10a - 3p", "Christmas Day", "New Year's Eve", "New Year's Day"). The rows carry **no dates**.
- **Homepage JSON-LD.** The `Museum` node has `specialOpeningHoursSpecification`: one entry per holiday with exact `validFrom`/`validThrough` dates (2026-11-26 … 2027-01-01). A closed day is encoded as `opens: "00:00", closes: "00:00"`, which is schema.org's convention for closed.

The user wants checks that the holiday hours are **present** ahead of each holiday and **gone** after it.

Their policy: each holiday must be posted at least 30 days ahead, and posting up to 60 days ahead is allowed.

Scope: **website only in this PR.** Google and Apple Maps holiday checks follow in a separate PR, using the drafted `docs/plans/holiday-hours-check.md` (which already records the Apple and Google findings).

**Latent issue found:** the `/visit` regular-hours parser (`_row_pairs` in `webwatch/sources/theflip_museum_visit.py`) now also reads the holiday rows. It is correct today only because `expand_days("Christmas Day")` happens to return `[]`. Fix: read regular rows only from the part of the card above the holiday heading.

## Policy (per holiday, today in America/Chicago)

`next` is the next occurrence of the holiday on or after today; `prev` is the last occurrence before today.

| Phase    | When                     | Listed, hours right                                              | Listed, hours wrong | Not listed                         |
| -------- | ------------------------ | ---------------------------------------------------------------- | ------------------- | ---------------------------------- |
| REQUIRED | `next - today` ≤ 30 days | OK                                                               | MISMATCH            | MISMATCH ("not posted; in N days") |
| OPTIONAL | more than 30 days        | OK, unless no configured holiday is within 60 days ("too early") | MISMATCH            | OK                                 |

A listed row whose **previous** occurrence is nearer than its next is **stale**. A stale row is always MISMATCH ("remove it"). See "Review feedback incorporated" #1–#3. That section supersedes the original strict ALLOWED/FORBIDDEN rows.

Additional rules:

- **Dated listings (JSON-LD).** An entry covering `prev` (any date before today) is stale, so the result is MISMATCH. An entry covering `next` is judged by the table.
- **Unaccounted-for rows or entries** (labels or dates we can't attribute to a configured holiday) cannot be ruled out as a renamed holiday. So wherever the verdict depends on _absence_ (REQUIRED + not listed, FORBIDDEN + not listed), the result is STRUCTURE_CHANGED instead of OK or MISMATCH. "Holiday absent" is asserted only when every holiday-section row is accounted for.
- **Page anchors missing.** If the Hours card (on `/visit`) or the `Museum` node (on the homepage) is missing, the result is STRUCTURE_CHANGED. A missing "Holiday Hours" heading, or a missing `specialOpeningHoursSpecification` key, is **legitimately "none listed"**, since off-season the section will be removed.
- A blank expected value in `facts.yaml` gives SKIPPED.

The windows are named constants in `webwatch/holiday_hours.py`: `REQUIRED_WITHIN_DAYS = 30` and `SEASON_WITHIN_DAYS = 60`.

## Design

### 1. Facts (`facts.yaml`, `webwatch/facts.py`)

```yaml
holiday_hours:
  thanksgiving: closed
  christmas_eve: '10:00 - 15:00'
  christmas: closed
  new_years_eve: '10:00 - 15:00'
  new_years_day: closed
```

Add `Organization.holiday_hours`. Loading raises `FactsError` for:

- an unknown key,
- a section that isn't a mapping,
- a value that `normalize.day_hours` can't parse.

A blank value is allowed.

### 2. `webwatch/holidays.py` (new, pure)

- `HOLIDAYS` maps each name to a `date_for(year)` function plus its label aliases.
  - Thanksgiving is the 4th Thursday of November.
  - Aliases are matched with `normalize.text` after folding curly apostrophes, e.g. "Christmas"/"Christmas Day" and "New Year's Day"/"New Years Day".
- `next_occurrence(name, today)` and `previous_occurrence(name, today)`.
- `holiday_for_label(label) -> str | None`.

### 3. Observation type (`webwatch/sources/base.py`)

- A `ListedHours` dataclass with fields:
  - `hours: str` (raw text),
  - `holiday: str | None` (resolved from a visible label),
  - `start` / `end: date | None` (JSON-LD).
- A `HolidayListing` dataclass with `items: tuple[ListedHours, ...]` and `unattributed: tuple[str, ...]`.
- `Observation.holiday_hours: Observed[Any]`, defaulting to `not_supported` (mirroring `events`).
- A `Source.provides_holiday_hours` flag.

Sources stay **pure**. JSON-LD entries are attributed to holidays by date in the check, because that needs the clock.

### 4. `/visit` source (`webwatch/sources/theflip_museum_visit.py`)

- Split the Hours card at the first heading inside it whose text, normalized, contains "holiday". Do not anchor on the Tailwind classes.
- **Regular `hours.*`** come from rows _above_ the split. With no split, every row is regular, as before.
- **Holiday rows** come from below the split, using the existing `_row_pairs`. Each label goes through `holiday_for_label`. A label it doesn't recognize goes into `unattributed`.
- Card missing: `holiday_hours` is missing (STRUCTURE_CHANGED). Card present with no holiday heading: an empty listing.

### 5. Homepage source (`webwatch/sources/theflip_museum.py`)

- Read `specialOpeningHoursSpecification` (a dict or a list) from the `Museum` node, which is already found via `structured.find_by_type`.
- Each entry yields `ListedHours(start=validFrom, end=validThrough or validFrom, hours=...)`.
  - `opens == closes == "00:00"` → `"closed"`.
  - Otherwise `"opens - closes"`.
- An entry with a malformed date, a missing `opens`, or a non-dict shape goes to `unattributed`. The entry is not guessed.
- Museum node missing: `holiday_hours` is missing.

### 6. The check (`webwatch/holiday_hours.py`): `check_holiday_hours(listing, facts, *, now, site)`

- Clock-injected, following the `expired_events` pattern in `webwatch/expiry.py`.
- Returns one `holiday_hours.<name>` result per configured holiday. It applies the policy table above and compares hours with `check_field(..., normalize.day_hours)` from `webwatch/checks/base.py`.
- For dated listings it also returns `holiday_hours.expired`. That result is MISMATCH when an entry ends before today and matches no configured holiday; otherwise OK.
- Future entries on dates that are not holidays (for example one-off closures) are not flagged. This is documented.
- Summaries name the concrete date. Examples: "Thanksgiving (2026-11-26) has passed; remove it", "Christmas Eve (2026-12-24) is in 30 days; not posted".

### 7. Wiring

- **`webwatch/run.py`**: for sources with `provides_holiday_hours`, run the holiday check next to the expiry check.
  - Honor `--fact holiday_hours.<name>`.
  - A fetch error gives FETCH_ERROR for each name.
  - Wrap each call in `_crashed`.
- **`webwatch/cli.py` `list_checks`**: list the holiday checks.
- **`webwatch/report.py` `_row`**: collapse `holiday_hours.*` into one "holiday hours" digest row.

### 8. Docs

- **`Facts.md`**: the schema, the holiday vocabulary, and the policy table.
- **`Checks.md`**: the dated-listing and absence-honesty rules.
- **`Operations.md`**: when you need to post or remove rows.
- **Source docstrings.**
- **`todo.md`**.
- Run `make agent-docs` if needed.

## Steps

1. Capture fixtures with `scripts/capture_fixture.py` for `https://www.theflip.museum/visit` and for the homepage (`theflip_museum`). Both currently include holiday hours. Create a branch (`/branch`).
2. Write `docs/plans/website-holiday-hours.md`. Run `make review-plan PLAN=docs/plans/website-holiday-hours.md` and record the agy feedback.
3. Implement test-first, in this order: holidays → facts → visit regular-hours split (regression test first) → listing extraction for both sources → check → run/cli/report → docs.
4. Run `make quality && make test`, then `/pre-pr-check`.

## Tests (clock pinned; negative cases by in-memory mutation of the 2026-11-24 fixtures)

- **holidays**
  - Thanksgiving dates for 2026, 2029, and other years.
  - Fixed dates.
  - next/previous occurrence across the year boundary and on the holiday itself.
  - Label aliases, including curly apostrophes.
- **facts**: an unknown key, bad hours, or a non-mapping raises `FactsError`; blank is allowed.
- **visit regular hours (regression)**: the new fixture gives seven correct `hours.*` values. A holiday row labeled with a weekday-like word below the heading does not leak into regular hours.
- **Today's fixtures, now = 2026-11-24**: all five holidays are OK on both sources, and `expired` is OK.
- **Policy, by moving `now`**
  - 2026-11-27: the Thanksgiving row is still present, so MISMATCH ("has passed"). With the row removed, OK.
  - On the homepage, the 2026-11-26 entry is stale, so MISMATCH.
  - 2026-12-01 with the Christmas Eve row removed (23 days away): MISMATCH, not posted.
  - 2026-10-20 with Thanksgiving removed (37 days away): OK.
  - 2026-10-20 with Thanksgiving listed but the wrong hours: MISMATCH.
  - 2026-09-01 with Thanksgiving listed (86 days away): MISMATCH, too early or stale.
  - Boundary days 30/31 and 60/61.
  - Holiday day itself is REQUIRED; the day after is FORBIDDEN.
- **Honesty**
  - Hours card removed: STRUCTURE_CHANGED.
  - Holiday heading removed: none listed, so OK off-season and MISMATCH when REQUIRED.
  - An unrecognized row label ("Xmas") with that holiday required: STRUCTURE_CHANGED.
  - Hours "ten-ish": PARSE_ERROR.
  - Museum node removed: STRUCTURE_CHANGED.
  - A malformed `validFrom`: unattributed, handled as above.
  - `00:00/00:00` reads as closed, not as open 24 hours.
  - An expired non-holiday entry: `expired` MISMATCH.
  - A blank fact: SKIPPED.
- **run/report/cli**
  - `--fact` filter.
  - FETCH_ERROR fan-out.
  - A source without holiday support yields no holiday results.
  - One digest row.
  - The checks appear in `list`.

## Verification

- `make quality && make test` pass.
- Live, run manually: `uv run webwatch check --site theflip_museum_visit` and `--site theflip_museum`. Today every `holiday_hours.*` check should be OK.
- Re-run with a pinned date of 2026-11-27 to preview the reminder to remove Thanksgiving. The CLI may lack a `--now`; if so, use a test or a REPL call to `run_checks(now=...)`.
- `uv run webwatch list` shows the new checks.

## Review feedback incorporated

`agy` is not installed on the development machine (`make review-plan` failed with `agy: not found`). The plan was instead reviewed by an independent Claude reviewer agent. It was given the plan, the docs, and the fixtures, but not the author's reasoning. Its findings, and what changed in response:

1. **"Too early" would fire every season.** If the five rows are posted as one block when Thanksgiving is due (30 days out), New Year's Day is about 66 days away. A strict 60-day limit then flags NYE/NYD as too early for about a week each year.
   - **Changed, with the user's agreement: early posting is judged season-aware.** A listed holiday is "too early" only when _no_ configured holiday is within 60 days.
2. **Undated rows can't tell "too early" from "stale".**
   - **Changed:** a listed row is classified by whichever occurrence is nearer. If its previous date is nearer than its next, it is **stale**, and a stale row is always a MISMATCH ("remove it"). Otherwise it is **upcoming** and judged by the season rule.
3. **One unrecognized row would turn all five checks STRUCTURE_CHANGED all year.**
   - **Changed:** unrecognized rows are reported in one aggregate result, `holiday_hours.unrecognized`, which is STRUCTURE_CHANGED and names the labels.
   - They block only a REQUIRED-phase "not posted" verdict, since that row might be the holiday under a new name.
   - Off-season absence verdicts stay OK. A renamed stale row still surfaces through the aggregate result.
4. **Dated JSON-LD entries are attributed by date.**
   - A well-formed entry on a non-holiday date never blocks a verdict. If it has ended, it is reported by `holiday_hours.expired`.
   - Only a _malformed_ entry (a bad date, a reversed range, or a range longer than 31 days) is unrecognized.
   - An entry with a valid date but unreadable `opens`/`closes` is attributed to its holiday and gives PARSE_ERROR.
5. **A missing heading is not proof of "none listed".**
   - **Changed:** if the Hours card has no holiday heading, the whole page is scanned for any heading containing "holiday", and for any two-span row whose label is a holiday alias.
   - Any hit means the section moved, so the result is STRUCTURE_CHANGED instead of an empty listing.
6. **The homepage JSON-LD contradicts the source's visible-text rule.**
   - **Documented as an explicit exception.** `specialOpeningHoursSpecification` is the feed search engines and map apps ingest, so it is a published claim in its own right and is judged independently against `facts.yaml`.
   - The `/visit` rows are the visible counterpart. The two sources are checked separately, not as drift.
7. **"00:00/00:00" means closed; seconds are allowed.**
   - The source maps `opens == closes == "00:00"` to `"closed"` before any hours text is built. A plain `time_range` call would read it as open 24 hours.
   - `HH:MM:SS` is trimmed to `HH:MM`.
8. **Duplicates and conflicts.** Every listed item for a holiday is judged, never only the first.
   - Any PARSE_ERROR gives PARSE_ERROR.
   - Otherwise, any differing item gives MISMATCH.
   - A JSON-LD range covering several holidays is attributed to each of them, unless a narrower entry covers that holiday (pre-PR review).
9. **How the split is done.** It uses document order within the card. The regression test puts a row that _does_ expand to a weekday ("Monday") below the heading.
10. **A holiday left out of `facts.yaml` was silently unchecked.**
    - **Changed:** every holiday in the vocabulary always reports. One that is unconfigured or blank is SKIPPED.
11. **Smaller points:**
    - `--fact` works on each `holiday_hours.*` name.
    - The FETCH_ERROR fan-out includes `expired` only for the dated (homepage) source.
    - **`webwatch check --today YYYY-MM-DD`** was added, to preview a date's verdicts.
    - The stale "Private Tours" mention in the visit docstring was refreshed.

Anti-flap answer: `ALERT_AFTER_FAILURES` defaults to 2 on a daily cron. A row left up after a holiday therefore alerts on the second morning after it. That is acceptable for a "please tidy up" signal.

## Pre-PR review feedback incorporated

The `/pre-pr-check` reviewers (documentation, antipattern, clean-code, code-smell) found:

1. **A "Holiday Hours" heading with no readable rows read as "none posted".** Now `missing` (STRUCTURE_CHANGED).
2. **A blank hours cell compared as a MISMATCH.** Now `unparseable` (PARSE_ERROR).
3. **Any heading containing "holiday" counted as the section.** An events heading such as "Holiday Pinball Party" would have made every off-season run STRUCTURE_CHANGED. The heading must now contain "holiday hours".
4. **A wide JSON-LD range was judged against every holiday it covered.** Only the narrowest entry covering a holiday is judged now.
5. **A range still in effect was reported stale.** (Dec 24–25 read on Dec 25.) Dated staleness now uses the entry's end date.
6. **Stale entries for a holiday left blank in `facts.yaml` were never flagged.** They now fall to `holiday_hours.expired`.
7. **`validFrom` as a DateTime was unrecognized.** Both forms are read now.
8. Smaller cleanups: a single source for check names, `calendar.THURSDAY`, and index-based (not `id()`) tracking in `expired`.

Deferred: splitting `_judge` into per-phase helpers, and replacing the `provides_holiday_hours`/`holiday_hours_dated` flag pair with a capability object. The second is worth doing when the maps sources arrive in the follow-up PR.
