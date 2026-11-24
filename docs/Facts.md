# Facts and Rules

[`facts.yaml`](../facts.yaml) is webwatch's source of truth — the canonical description of The Flip that web pages are checked against. It is hand-maintained and reviewed in git. When the museum's real-world details change, change them **here first**; webwatch will then flag any site still showing the old information.

There are two parts: static **facts** and dynamic **rules**.

## Static facts

A nested mapping of the museum's stable details. Checks compare observed page values (after [normalization](Extraction.md#normalization-before-comparison)) to these.

```yaml
organization:
  name: 'The Flip'
  url: 'https://www.theflip.museum/'
  address:
    street: '...'
    city: '...'
    region: '...' # state/province
    postal_code: '...'
    country: 'US'
  phone: '+1 555 123 4567'
  email: 'hello@example.org'
  business_status: 'operational' # as listings report it; see below
  donation_url: 'https://checkout.square.site/merchant/.../checkout/...' # see below
  listing_names: # other names map/listing sites may legitimately show
    - "The Flip: Chicago's Playable Pinball Museum"
  hours:
    monday: '10:00 - 20:00' # a range string
    saturday: { open: '10:00', close: '17:00' } # or an open/close map
    sunday: closed
    # ...one entry per weekday
  holiday_hours: # see "Holiday hours" below
    thanksgiving: closed
    christmas_eve: '10:00 - 15:00'
```

Conventions:

- Each day's hours may be written three ways, all equivalent after normalization (`normalize.day_hours`): a range string (`"10:00 - 20:00"`, or comma-separated for multiple windows `"9-12, 1-5"`), an `{open, close}` map, a list of either, or the literal `closed`. Times accept 24h (`"17:00"`) or 12h (`"5 PM"`), and windows may cross midnight (`"18:00 - 02:00"`).
- `listing_names` are other names that map and listing sites (Apple Maps, Google Maps) may show for the museum, such as Google's longer descriptive name. A listing's name check passes if it matches `name` or any of these exactly (case- and whitespace-insensitive), with no fuzzy matching. The museum's own site is still checked against `name` alone.
- `business_status` is what listing sites should say about whether the museum is open for business at all. It's compared case-insensitively with Google's `businessStatus` (`OPERATIONAL` / `CLOSED_TEMPORARILY` / `CLOSED_PERMANENTLY`). If the museum ever closes temporarily, change it here (e.g. `closed_temporarily`) so listings that say so aren't flagged.
- `donation_url` is the online checkout that the "Donate Now" button on `theflip.museum/donate` should link to. Two checks use it: `theflip_museum_donate` asserts the page links here, and `square_donation` asserts the link is still live (not deleted or disabled, and the store is accepting payments). It must be a canonical `https://checkout.square.site/merchant/<id>/checkout/<id>` URL, not a `square.link` short link. If you replace the link, also change `SquareDonation.url` in `webwatch/sources/square_donation.py`. A test fails until the two agree. Leaving it blank skips both checks.
- Leave a value as `""` (empty) to mean "not yet verified — don't check this." Checks treat empty expected facts as `SKIPPED` rather than asserting against a blank.
- `facts.py` validates the shape on load and fails loudly on a malformed file.

## Holiday hours

`organization.holiday_hours` maps a **named holiday** to its hours, written in the same forms as `hours` (`closed`, a range, an `{open, close}` map, or a list).

The names come from a fixed vocabulary in `webwatch/holidays.py`:

| Name            | Date                     | Visible labels recognized      |
| --------------- | ------------------------ | ------------------------------ |
| `thanksgiving`  | 4th Thursday of November | Thanksgiving, Thanksgiving Day |
| `christmas_eve` | Dec 24                   | Christmas Eve                  |
| `christmas`     | Dec 25                   | Christmas, Christmas Day       |
| `new_years_eve` | Dec 31                   | New Year's Eve                 |
| `new_years_day` | Jan 1                    | New Year's Day, New Year's     |

`facts.py` rejects an unknown name or an unparseable value when it loads the file, so a typo can't quietly go unchecked. To add a holiday, add one entry to `webwatch/holidays.py` with a test of its dates. Every holiday in the vocabulary is always reported. One that is missing here, or blank, shows as `SKIPPED`.

**Why this is a fact, not a rule.** Rules are evaluated against a page's events list. Holiday hours are expected values compared through `normalize.day_hours`, just like `hours`. The only difference is that their date depends on the calendar.

### When a holiday must be posted, and removed

The museum's website (the `/visit` "Holiday Hours" rows and the homepage JSON-LD `specialOpeningHoursSpecification`) is checked against this policy (`webwatch/holiday_hours.py`). "Today" is in the museum's timezone.

| Situation                                                  | Result                               |
| ---------------------------------------------------------- | ------------------------------------ |
| Listed, and the holiday has passed (see below)             | `MISMATCH`: "has passed … remove it" |
| Listed for the upcoming occurrence, with hours that match  | `OK`                                 |
| Listed for the upcoming occurrence, with hours that differ | `MISMATCH`                           |
| Listed while **no** configured holiday is within 60 days   | `MISMATCH`: "posted too early"       |
| Not listed, holiday within 30 days                         | `MISMATCH`: "not posted"             |
| Not listed, holiday more than 30 days away                 | `OK`                                 |

A `/visit` row has no date, so it is taken to be about whichever occurrence is nearer: once the previous one is nearer than the next, the holiday has passed. A leftover row more than half a year old therefore reads as "posted too early" rather than "remove it"; both are `MISMATCH`.

Posting early is judged by the **season**, not per holiday. The five rows are usually posted together when Thanksgiving falls due (30 days out), and New Year's Day is then about 66 days away. That is fine because the season is open.

Some states are reported as checker conditions rather than verdicts:

- **Unreadable listing.** An unreadable page region is `STRUCTURE_CHANGED`. Examples: the Hours card or the JSON-LD `Museum` node is gone, or holiday rows show up outside the card.
- **Section removed.** A missing "Holiday Hours" section or `specialOpeningHoursSpecification` key means none are posted. That is legitimate off-season. It is also what a renamed JSON-LD key would look like; we accept that ambiguity because the `/visit` rows are checked independently, and a "Holiday Hours" heading with no readable rows under it is `STRUCTURE_CHANGED`, not "none posted". A blank hours value is `PARSE_ERROR`.
- **Unrecognized row.** A holiday row whose label isn't recognized (say, "Xmas") is reported once, as `holiday_hours.unrecognized` (`STRUCTURE_CHANGED`). It also turns a "not posted" verdict into `STRUCTURE_CHANGED`, since that row might be the missing holiday.
- **Dated entries.** JSON-LD entries are matched to holidays by the dates they cover (`validFrom`/`validThrough`, Date or DateTime).
  - Where several entries cover a holiday, only the narrowest is judged: a specific "Dec 25: closed" overrides a wide "Dec 20–31" range for Christmas.
  - A dated entry is stale only once its own range has ended. An entry covering an occurrence beyond the next one is "posted too early" regardless of the season.
  - A well-formed entry not judged for any configured holiday (a one-off closure, or a holiday left blank in `facts.yaml`) is not judged, until it has ended; then it is reported as `holiday_hours.expired`.

A row left up after a holiday alerts on the second daily run after it (`WEBWATCH_ALERT_AFTER_FAILURES`, default 2). To preview a date, run `webwatch check --today YYYY-MM-DD`.

## Dynamic rules

A list under `rules:`. Each rule has an `id`, a human `description`, a `type`, an `enabled` flag, and type-specific fields. Rules are evaluated by `rules.py` against a source's observed events.

```yaml
rules:
  - id: weekly-repair-day
    description: 'Volunteer repair day every Saturday'
    type: recurring_event
    match: repair # which upcoming event this rule corresponds to (title/description)
    frequency: weekly
    weekday: saturday
    start: '10:00' # event time matters — volunteer days run 10:00-16:00
    end: '16:00'
    enabled: true
```

### Rule types

| `type`            | Fields                                          | Checks that…                                                                   |
| ----------------- | ----------------------------------------------- | ------------------------------------------------------------------------------ |
| `recurring_event` | `match`, `frequency`, `weekday`, `start`, `end` | an upcoming event matching `match` is listed on `weekday`, starting at `start` |

`match` is a keyword sought in event titles (and, as a fallback, descriptions) to find the event the rule is about. For recurring events the **time** is significant, not just the day — `start`/`end` are 24h `"HH:MM"`. The engine reads each event's _stated_ weekday and time, so:

- the events list can't be read → `STRUCTURE_CHANGED`;
- no upcoming event matches `match` → `MISMATCH` (the expected event isn't scheduled);
- a match is found but its weekday or start time differs → `MISMATCH`;
- a match is found but its weekday/time text is missing → `STRUCTURE_CHANGED` for that aspect;
- everything agrees → `OK`.

This table grows as we add rule types (e.g. seasonal hours, one-off events). Add a new type by extending `rules.py` and documenting it here, with a plan reviewed per [plans/](plans/README.md).

## Disabling a check

Set `enabled: false` on a rule, or leave a static fact empty, when the canonical value isn't verified yet or the corresponding source/check doesn't exist. Disabled items report `SKIPPED` and never alert.
