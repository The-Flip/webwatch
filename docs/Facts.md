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
    monday: closed
    saturday: { open: '10:00', close: '17:00' } # 24h times
    # ...one entry per weekday
```

Conventions:

- Hours use 24-hour `"HH:MM"` strings, or the literal `closed`. A day with multiple windows may be a list of `{open, close}` maps.
- Leave a value as `""` (empty) to mean "not yet verified — don't check this." Checks treat empty expected facts as `SKIPPED` rather than asserting against a blank.
- `facts.py` validates the shape on load and fails loudly on a malformed file.

## Dynamic rules

A list under `rules:`. Each rule has an `id`, a human `description`, a `type`, an `enabled` flag, and type-specific fields. Rules are evaluated by `rules.py` against an injected clock (so tests can pin "now").

```yaml
rules:
  - id: weekly-repair-day
    description: 'Volunteer repair day every Saturday'
    type: recurring_event
    frequency: weekly
    weekday: saturday
    enabled: true
```

### Rule types

| `type`            | Fields                 | Checks that…                                                       |
| ----------------- | ---------------------- | ------------------------------------------------------------------ |
| `recurring_event` | `frequency`, `weekday` | a matching recurring event appears in the site's observed schedule |

This table grows as we add rule types (e.g. seasonal hours, one-off events). Add a new type by extending `rules.py` and documenting it here, with a plan reviewed per [plans/](plans/README.md).

## Disabling a check

Set `enabled: false` on a rule, or leave a static fact empty, when the canonical value isn't verified yet or the corresponding source/check doesn't exist. Disabled items report `SKIPPED` and never alert.
