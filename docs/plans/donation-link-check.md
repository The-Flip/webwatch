# Plan — Donation link check (theflip.museum/donate → Square checkout)

## Context

The museum added `https://www.theflip.museum/donate`. Its "Donate Now" button links out to a Square
online-checkout donation link. If that link is deleted or disabled in the Square dashboard, mistyped
on the site, or pointed at the wrong merchant, donors hit a dead end and nobody notices. This adds a
check that the link is still valid.

"Valid" has two halves, and each fails differently:

1. **The donate page links to the right checkout.** Someone edits the site and the button now points
   somewhere else (an old link, a test link, a different merchant).
2. **That checkout is live.** The link was deleted or disabled in Square, or the Square store
   stopped accepting payments.

## What the pages look like (probed live, read-only, 2026-10-15)

- **`/donate`** is server-rendered (Next.js) like the rest of the site. The main CTA is
  `<a href="https://checkout.square.site/merchant/ML3SPVMTSCZBA/checkout/C3TD5MW7HG3FIIATNS4GALNL"
target="_blank">Donate Now</a>`. The nav and footer also have "Donate" links, but they're internal
  (`/donate`). There's no JSON-LD on the page about donations.
- **The Square checkout link** returns HTTP 200. The visible page is a JS shell; only the `<title>`
  ("Support The Flip - The Flip: Chicago's Playable Pinball Museum") is server-rendered. It embeds
  Square's own state as `window.bootstrap = {...}` JSON, which includes:
  - `merchantId: "ML3SPVMTSCZBA"`, `checkoutLinkId: "C3TD5MW7HG3FIIATNS4GALNL"`. These are the same
    IDs as in the URL, which makes them a self-identity guard.
  - `storeIsAcceptingPayments: true`
  - `checkoutLink.is_deleted: false`, `checkoutLink.checkout_link_data.enabled: true`,
    `link_type: "DONATION_LINK"`
  - `fetch.looks_blocked` does not flag it.
- **An unknown checkout id on the same merchant** returns **HTTP 404** with a "Something went wrong /
  We couldn't find that page" body.
- **Not observed:** what a _disabled_ (not deleted) link renders as. That would need the Square
  dashboard. It's probably either a 404 or a 200 whose bootstrap says `enabled: false`. Both are
  handled below. Any other shape (a 200 without a bootstrap we can read) degrades to
  `STRUCTURE_CHANGED`, never `OK`.

## Approach

Two sources, because there are two pages and a source fetches exactly one page. Each fetches once, so
the "one fetch per source" rule holds.

### 1. Fact: `organization.donation_url`

Add `donation_url` to `Organization` in `facts.py` (a plain string, blank → `SKIPPED`) and to
`facts.yaml`. Document it in `docs/Facts.md`. This is the canonical link donors should land on. If the
museum swaps to a new Square link, it's changed here first, the same as every other fact.

### 2. Source `theflip_museum_donate` (`https://www.theflip.museum/donate`)

- `tracks = {"donation_url"}`.
- **Anchor (semantic, not positional):** the CTA is an `<a>` that is (a) inside `<main>` (or, if
  the page has no `<main>`, outside `<header>`/`<nav>`/`<footer>`), (b) off-site: its href is an
  absolute `http(s)` URL with a host other than `theflip.museum`, and (c) labeled with a donate call
  to action. Its label is its visible text, `aria-label`, or a child `img[alt]`, normalized. The
  label has to be **exactly** one of a small phrase set: "donate", "donate now", "make a donation",
  "give", "give now" (agy 2.1). The exact match keeps in-kind links ("Donate a machine"),
  charity-rating badges, and "Donate via PayPal"-style alternatives out of the candidate set. If one
  of those turned up, it would otherwise be a false "candidates disagree". Relative and internal
  links (the nav/footer `/donate`) and `mailto:` links are excluded by (b). So a page whose only
  donate link is relative has **no candidate**, which is `STRUCTURE_CHANGED` (agy 5.1).
- Outcomes:
  - no candidate → `missing` → `STRUCTURE_CHANGED` (the button was renamed or removed; we can't tell
    which, so we don't guess);
  - all candidates normalize (`normalize.url`) to one URL → `found(url)`;
  - candidates that disagree (two donate buttons pointing at different places) → `missing` with a
    note listing them → `STRUCTURE_CHANGED`, following the doctrine's "strategies disagree".
- **Check:** `Check("donation_url", lambda f: f.organization.donation_url, normalize.url)`. A
  different link → `MISMATCH`. Filter (b) only admits an absolute `http(s)` URL with a host, which
  is exactly what `normalize.url` accepts. So `PARSE_ERROR` can't happen on this field: a malformed
  href is simply not a candidate, and it ends up as `STRUCTURE_CHANGED`. `normalize.url` keeps path case, which matters because Square IDs are case-sensitive.

### 3. Source `square_donation` (the checkout link itself)

- `url` is the checkout URL, hardcoded in the module the same way Apple Maps pins its place-id. A
  test asserts it equals `facts.yaml`'s `donation_url` (normalized), so the two can't drift apart
  silently. Only the canonical `checkout.square.site/merchant/<merchant>/checkout/<link>` form is
  supported, because the identity guard parses both IDs from it. Parsing runs at import and raises
  `ValueError` on any other shape, such as a `square.link` short URL, so a misconfiguration fails
  loudly rather than as a perpetual `STRUCTURE_CHANGED` (agy 2.3).
- `tracks = {"link_status"}`.
- **Parse `window.bootstrap` defensively.** Locate the assignment, then decode the object with
  `json.JSONDecoder().raw_decode` from its first `{`. That way a trailing `;` or more script text
  doesn't matter, and there's no greedy regex over nested braces. If it's absent, not JSON, or not a
  dict → `missing` → `STRUCTURE_CHANGED`.
- **Self-identity guard (pure):** the bootstrap's `merchantId` and `checkoutLinkId` must equal the
  IDs parsed from `url`. If they don't, → `missing` → `STRUCTURE_CHANGED`. That covers a redirect to
  some other checkout, or to a Square or merchant landing page that has no checkout bootstrap. It's
  never a `MISMATCH` about someone else's link.
- **Status derivation.** It reads three flags, each traversed defensively with
  `isinstance(..., dict)` at every level. A `null` or non-dict `checkoutLink` or
  `checkout_link_data` counts as "flag absent", never a `TypeError`:
  - `bootstrap.checkoutLink.is_deleted`: unhealthy if `True` → `"deleted"`
  - `bootstrap.checkoutLink.checkout_link_data.enabled`: unhealthy if `False` → `"disabled"`
  - `bootstrap.storeIsAcceptingPayments`: unhealthy if `False` → `"not accepting payments"`

  Evaluation order (agy 2.2): **any flag that's present and unhealthy wins**, in the order listed,
  even when the other flags are absent or malformed. A deleted link whose `enabled` was omitted is
  still `"deleted"` → `MISMATCH`. Otherwise, any flag present but not a bool → `unparseable`
  (`PARSE_ERROR`). Otherwise, any flag absent → `missing` (`STRUCTURE_CHANGED`). An absent flag is
  never read as healthy. Otherwise → `"active"`.

- **Check:** `Check("link_status", <expected>, normalize.text)`, where `<expected>` is `"active"`
  when `facts.organization.donation_url` is set and `""` when it's blank. So blanking the fact skips
  **both** donation checks, matching the documented "blank fact → `SKIPPED`" convention (agy 1.1).
  Anything other than active → `MISMATCH`, with the observed status ("disabled", "deleted", …) shown
  in the report.

### 4. A 404 on the checkout link is a finding, not a fetch failure

The most likely way this link breaks is that it gets deleted, which Square serves as **HTTP 404**.
Today `fetch()` raises `FetchError` on any non-2xx, so that would surface as `FETCH_ERROR` ("we
couldn't fetch"). That's misleading for this check. The server answered authoritatively that the link
doesn't exist, which is exactly the world-state problem we're watching for, and it should be a
`MISMATCH` (exit 1), not a checker problem (exit 2).

A small opt-in extension to the fetch boundary handles this:

- `fetch(..., accept_statuses: frozenset[int] = frozenset())`. A response whose status is in the set
  is returned as a `FetchResult` instead of raising. It's checked **after** block detection (so a
  challenge served as a 404 is still `BLOCKED`) and only for statuses that aren't retryable.
- `Source.accept_statuses: frozenset[int] = frozenset()` (default: none, so behavior is unchanged
  for every existing source). `Source.fetch` passes it through and then calls a new hook,
  `observe_result(result: FetchResult) -> Observation`, which by default returns
  `self.observe(result.text)`. That keeps `observe` pure and unchanged for every source.
- `square_donation` sets `accept_statuses = {404, 410}` and overrides `observe_result`: a 404 or 410
  → `link_status = found("not found (HTTP 404)")` → `MISMATCH`. Other statuses go through `observe`.
- `docs/Extraction.md` and `docs/Checks.md` will say that `accept_statuses` is only for sources whose
  fact _is_ "this URL exists", where a 404 is the answer and not an obstacle. Listing sources
  (like Apple Maps, where a 404 means our place-id is wrong) keep mapping it to `FETCH_ERROR`.

False-alarm risk: a 404 is an authoritative answer, not a guess, and the state layer only alerts
after N consecutive unhealthy runs, which absorbs a one-off CDN blip. 5xx and network errors keep
retrying and stay `FETCH_ERROR`.

### 5. Registration and docs

- Add both pairs to `_BUILTINS` in `run.py`.
- Show `donation_url` in `webwatch facts` (`cli.py`) (agy 1.3).
- Docs to update: `Facts.md` (`donation_url`), `Checks.md` (the "link-validity sources" subsection,
  `accept_statuses`/`observe_result`), `Extraction.md` (404-as-finding carve-out), and
  `Project_Structure.md` if it lists sources.

## Testing

Both fixtures get captured with `scripts/capture_fixture.py --source <name>`.

`tests/test_theflip_museum_donate.py`:

- golden fixture → `donation_url` `OK`;
- CTA removed → `STRUCTURE_CHANGED`; CTA text changed to something without "donat" →
  `STRUCTURE_CHANGED`;
- href changed to another valid Square link → `MISMATCH`; href changed to a non-Square site →
  `MISMATCH`;
- CTA href made relative, or malformed (`https:///x`, no host) → not a candidate →
  `STRUCTURE_CHANGED`;
- an extra in-kind link ("Donate a machine" → a Google Form) and a "Donate via PayPal" link don't
  disturb the result (`OK`);
- an image-only CTA (`<a><img alt="Donate Now"></a>`) is recognized;
- a second donate CTA pointing at a different URL → `STRUCTURE_CHANGED`; a second CTA pointing at the
  same URL (with cosmetic differences like a trailing `/`) → `OK`;
- internal `/donate` nav links never count as candidates;
- challenge page → `BLOCKED` (via `Source.fetch` with a mock transport);
- blank `donation_url` fact → `SKIPPED`.

`tests/test_square_donation.py`:

- golden fixture → `link_status` `OK`;
- bootstrap mutated: `enabled: false` → `MISMATCH` ("disabled"); `is_deleted: true` → `MISMATCH`;
  `storeIsAcceptingPayments: false` → `MISMATCH`;
- a flag removed → `STRUCTURE_CHANGED`; a flag set to a string → `PARSE_ERROR`;
- bootstrap removed, or not valid JSON → `STRUCTURE_CHANGED`; `checkoutLink: null` →
  `STRUCTURE_CHANGED` (no crash); `is_deleted: true` with `checkout_link_data` removed → still
  `MISMATCH` ("deleted");
- trailing script after the bootstrap object (`window.bootstrap = {...}; function f() {}`) parses;
- blank `donation_url` fact → `SKIPPED`;
- `checkoutLinkId`/`merchantId` changed → `STRUCTURE_CHANGED` (identity guard), not `MISMATCH`;
- via `Source.fetch` with a mock transport: 404 → `MISMATCH`; 410 → `MISMATCH`; 500 (after retries)
  → `FetchError`; challenge body → `BLOCKED`, including a challenge body served _with_ a 404;
- `SOURCE.url` equals `facts.yaml` `donation_url`.

`tests/test_fetch.py`: `accept_statuses` returns a 404 instead of raising, a 404 still raises when
it's not accepted, and a blocked 404 is still `blocked`.

`tests/test_facts.py`: `donation_url` parses, and its absence is blank.

## Verification

- `make quality`, `make test`.
- `webwatch check --site theflip_museum_donate` and `--site square_donation` against live sites both
  `OK`.
- `webwatch list` shows the two new sources.

## Alternatives considered

- **One source that follows the href it finds.** That's two fetches in one source and a dynamic URL,
  and it breaks the one-page-per-source model. It also couldn't tell "page links to the wrong
  checkout" apart from "checkout is dead". Rejected.
- **Accept a 404 as `FETCH_ERROR`** (the Apple Maps precedent). It needs no framework change, but it
  labels the precise failure we're monitoring as a checker problem. Rejected for this source. Apple
  Maps keeps its behavior.
- **Use the Square API to read the link's status.** That needs an access token on the production host
  for what the public page already exposes. Deferred unless the public page stops embedding its state.
- **Accept Square's `square.link/u/...` short URL as equivalent** on the donate page. Deferred. If the
  site switches to the short link, it shows as a `MISMATCH`, and the fix is a one-line `facts.yaml`
  change.

## Review feedback incorporated (agy)

`agy` reviewed this plan. Changes made above:

- **1.1 — blank fact must skip the Square check too:** `link_status` expects `"active"` only when
  `donation_url` is set, and `""` (→ `SKIPPED`) otherwise. Test added.
- **1.3 — `webwatch facts`** now shows `donation_url`.
- **2.1 — loose anchor:** candidates are limited to `<main>` and to an exact donate-CTA phrase set
  (text, `aria-label`, or `img[alt]`). That way, in-kind, charity-badge, or alternative-payment
  links can't create a false "candidates disagree". Tests added for each.
- **2.2 — bootstrap traversal and order:** every level is traversed defensively, a present unhealthy
  flag beats an absent companion, and paths are spelled out in full. Tests added for a null
  `checkoutLink`, and for deleted plus missing `checkout_link_data`.
- **2.3 — redirects and short URLs:** an off-target redirect is documented as `STRUCTURE_CHANGED`.
  The Square source supports only the canonical URL form and fails loudly at import otherwise.
- **5.1 — hedged spec:** a relative href is excluded by the anchor filter → `STRUCTURE_CHANGED`.
  The anchor filter admits only URLs that `normalize.url` accepts, so this field has no
  `PARSE_ERROR` path, and the plan now says so.
- **5.2 — missing tests:** all three added.

Considered and declined:

- **1.2 — derive the Square source's URL from `facts.yaml` at runtime** (e.g. a `url` property that
  loads facts). The premise is that facts get edited in production without a code release. That
  doesn't happen here. `facts.yaml` lives in the repo and production deploys with `git pull`, so a
  facts change and its code always ship together, and the equality test (run by the pre-push hook)
  blocks a commit where they disagree. Loading facts inside a source would also break the rule that
  a source never sees facts, which keeps `observe` pure.
- **3.2 — make `capture_fixture.py` honor `accept_statuses`.** A golden fixture should be the
  _healthy_ page. If the link is returning 404 when someone tries to capture it, refusing to save
  that as golden is the right behavior. The 404 path is tested with an in-memory response.
- **4.1 — scrub tokens from the Square fixture.** We checked instead of assuming: the captured page
  carries no `sq0…` tokens, and `detect-secrets scan` reports nothing on either new fixture. Its only
  identifiers are public client-side telemetry IDs (Sentry DSN, Datadog client token) that Square
  serves to every visitor. They're committed as captured, so the fixture stays the real page.

## Pre-PR review changes

The pre-PR review agents raised these, and they were addressed during implementation:

- **The 404 handling is now part of the `Source` contract.** The base `observe_result` sends an
  accepted status to a new `observe_not_found(result)` hook. A source that sets `accept_statuses`
  without overriding it raises `TypeError` when its class is defined, so an accepted 404 can never
  fall through to `observe`.
- **A 404 must be Square's own not-found page to count as "deleted".** A bare 404 with an
  unrecognized body (from a CDN or routing glitch) is `STRUCTURE_CHANGED`, so it can never turn into
  a false `MISMATCH`.
- **A malformed href (such as `http://[broken`) is not a candidate.** `urlsplit` raised
  `ValueError` on it, which would have crashed the donate source.
- **Readability:** the flags are now a `_Flag` NamedTuple, and `_link_status` is private.

Declined, with reasons:

- **An off-site "Donate" link that isn't Square could produce a `MISMATCH`.** That's intended. The
  page's donate button pointing somewhere other than `donation_url` is exactly the finding.
- **A present unhealthy flag should need a corroborating healthy flag.** The identity guard already
  ties the payload to our link, and requiring a corroborating flag would hide a real deletion.
- **`str(None)` handling for YAML `null` in `facts.py`.** This is existing behavior shared by every
  field. It fails loudly today, because `normalize.url` raises on the expected value.
