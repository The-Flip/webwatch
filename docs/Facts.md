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
  hours:
    monday: '10:00 - 20:00' # a range string
    saturday: { open: '10:00', close: '17:00' } # or an open/close map
    sunday: closed
    # ...one entry per weekday
```

Conventions:

- Each day's hours may be written three ways, all equivalent after normalization (`normalize.day_hours`): a range string (`"10:00 - 20:00"`, or comma-separated for multiple windows `"9-12, 1-5"`), an `{open, close}` map, a list of either, or the literal `closed`. Times accept 24h (`"17:00"`) or 12h (`"5 PM"`), and windows may cross midnight (`"18:00 - 02:00"`).
- Leave a value as `""` (empty) to mean "not yet verified — don't check this." Checks treat empty expected facts as `SKIPPED` rather than asserting against a blank.
- `facts.py` validates the shape on load and fails loudly on a malformed file.

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
