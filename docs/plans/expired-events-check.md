# Expired-events check

## Context

Stale events linger: an event that has already happened should not still be advertised. The
requirement: **an event must not appear on the homepage or the /visit page past midnight of the day
it ends.** So if "now" is any time on a later calendar day than the event's end date, and the event
is still listed, that is a problem to flag.

This is webwatch's first **time-dependent** check, and the events cards carry **no year and no
machine-readable date** — only a "Jun 27" badge and a weekday in the meta line. Inferring the year is
the crux, and the reason this needs a plan.

## What "ends" means here

- Events on these pages are single-day (a date badge + a time, possibly a range). The **end date is
  the badge date**; the time range is within that day.
- "Past midnight of the day it ends" = `now`'s calendar date is **strictly after** the end date. An
  event whose end date is _today_ is still valid (midnight hasn't passed). Future-dated events are
  fine.
- **Recurring events are included.** The badge shows the next occurrence's date; if a recurring
  event's displayed date is in the past, the site failed to roll it forward — still stale, still flag.

## Year inference (no year on the page)

To get an absolute end date from `("Jun", 27, weekday="Saturday")`:

1. Map the month abbreviation to a number, the day to an int.
2. Consider candidate years near `now` (`now.year - 1`, `now.year`, `now.year + 1`).
3. Build the valid `date(year, month, day)` for each (skip invalid, e.g. Feb 29 in a non-leap year).
4. **If the card shows a weekday, keep only candidates whose date falls on that weekday** — this is a
   strong disambiguator (a given month/day lands on a given weekday only every few years).
5. Among the survivors, pick the date **closest to `now`** (min absolute day difference).
6. If nothing survives (e.g. the weekday is inconsistent with every nearby year, or the month is
   unparseable), the date is **indeterminate** → that event is _skipped_ (not flagged expired), to
   avoid false positives. Indeterminate dates are surfaced in the detail so they're visible.

This weekday+nearest heuristic correctly catches the realistic failure (an event days/weeks stale:
the weekday pins the year to the recent past). Documented limitation: a yearless date with **no
weekday** that is more than ~6 months stale can be mis-read as next year's occurrence; with a weekday
present, that case is still caught.

## Design

1. **Both sources provide events.** `theflip_museum.py` (homepage) gains event reading and
   `provides_events = True`, alongside the existing `/visit` source. The reusable `events.extract_events`
   already handles both (identical card markup).

2. **`webwatch/expiry.py`** — `check_expired_events(observed_events, *, now, site) -> CheckResult`:
   - events unreadable (`Observed.missing`) → `STRUCTURE_CHANGED`.
   - for each event, compute the end date (above); collect those strictly before `now.date()`.
   - any expired events still listed → `MISMATCH` ("N expired event(s) still shown: 'Title' (Jun 19)…").
   - none expired → `OK`. Indeterminate-date events are noted in the detail but don't fail the check.
   - `now` is injected (timezone-aware) for testability.

3. **Timezone + clock.** "Midnight" is the museum's local midnight. Add `WEBWATCH_TIMEZONE`
   (default `America/Chicago`). `run_checks` gains a `now: datetime | None` parameter; when `None` it
   uses `datetime.now(ZoneInfo(config.TIMEZONE))`. Tests pass a fixed `now` (no `freezegun` needed —
   the parameter is the seam).

4. **Wire into the run.** For every `provides_events` source, `run_checks` runs the expiry check
   (named `expired_events`) against the source's observed events, alongside its field checks and
   recurring-event rules. `--fact expired_events` targets it.

5. **Refresh fixtures.** Re-capture the homepage (its current events differ from the committed
   pre-fix snapshot) so the golden fixtures reflect reality; the all-OK run test pins `now` to the
   capture date so nothing is expired.

## Testing (`tests/test_expiry.py`, extend `tests/test_run.py`)

- **Year inference:** `("Jun", 27, "Saturday")` with `now = 2026-06-20` → `2026-06-27`; the same with
  `now = 2026-07-01` (past) → still `2026-06-27` (nearest, weekday-consistent) → expired.
- **Expired vs not:** an event ending yesterday → `MISMATCH`; ending today → `OK` (not past midnight);
  ending tomorrow → `OK`.
- **Recurring stale event** (past date, `recurring=True`) → still `MISMATCH`.
- **Indeterminate date** (unparseable month, or weekday inconsistent with all nearby years) → not
  flagged; noted in detail; check is `OK` if nothing else expired.
- **Unreadable events** (`Observed.missing`) → `STRUCTURE_CHANGED`.
- **Run wiring:** with `now` pinned to each fixture's capture date, the full run is all-OK; advancing
  `now` past an event date makes `expired_events` a `MISMATCH` (exit 1).

## Verification

- `make quality` / `make test` green.
- `webwatch check` against the live pages (real `now`) includes an `expired_events` result per page.
- A pinned-`now` demo shows OK before an event's date and MISMATCH after it.

## Review status (agy still 429 — self-review applied)

`agy` is still returning HTTP 429 (model overloaded), so an independent review remains **owed**
(`make review-plan PLAN=docs/plans/expired-events-check.md`). Self-review folded in:

- **Timezone-correct comparison:** compare `now.date()` (in `WEBWATCH_TIMEZONE`) to the naive
  inferred date, so "midnight" is the museum's local midnight, not the server's. Add a `tzdata`
  dependency so `ZoneInfo("America/Chicago")` resolves on any platform.
- **Boundary:** expired iff `now.date()` is _strictly after_ the end date (ending today ≠ expired).
- **Indeterminate dates never false-flag:** an event whose year can't be pinned (unparseable month,
  or weekday inconsistent with every nearby year) is skipped and surfaced in the detail; if nothing
  is confidently expired the check is `OK` (with the indeterminate count noted), not a guess.
- **No-weekday limitation** is explicit: a yearless, weekday-less date >~6 months stale can read as
  future; the realistic stale-by-days case (and any case with a weekday) is still caught.
