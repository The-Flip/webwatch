"""Canonicalize values before comparison.

Checks never compare raw strings — cosmetic differences (whitespace, ``Street``
vs ``St``, ``(555) 123-4567`` vs ``+15551234567``, ``9 AM`` vs ``09:00``) are not
mismatches. Each normalizer turns a value into a canonical, comparable form;
compare the *normalized* expected and observed values. Functions raise
``ValueError`` on input they cannot model, which a check maps to ``PARSE_ERROR``.

See ``docs/Extraction.md`` (Normalization) and the agy review of Phase B (Gap D)
for why the street/phone/hours handling is deliberately not naive.
"""

from __future__ import annotations

import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

_WS = re.compile(r"\s+")

# Street-type suffixes, expanded only when they are the FINAL token — the street
# type conventionally comes last ("John St" -> "john street"), so a leading "St."
# (almost always "Saint") is left untouched rather than mangled to "Street".
_STREET_SUFFIXES = {
    "st": "street",
    "str": "street",
    "ave": "avenue",
    "av": "avenue",
    "rd": "road",
    "blvd": "boulevard",
    "dr": "drive",
    "ln": "lane",
    "ct": "court",
    "pl": "place",
    "sq": "square",
    "ter": "terrace",
    "hwy": "highway",
    "pkwy": "parkway",
}
# Directionals are unambiguous enough to expand anywhere in the address.
_DIRECTIONALS = {
    "n": "north",
    "s": "south",
    "e": "east",
    "w": "west",
    "ne": "northeast",
    "nw": "northwest",
    "se": "southeast",
    "sw": "southwest",
}

# Hyphen, en dash, em dash — built via chr() to avoid ambiguous-unicode literals.
_DASH_CLASS = re.escape("-" + chr(0x2013) + chr(0x2014))
_TIME_RANGE_SEP = re.compile(rf"\s*(?:[{_DASH_CLASS}]|to)\s*", re.IGNORECASE)
# Meridiem may be a/p, am/pm, or a.m./p.m. (the museum's site uses bare "10a"/"8p").
_TIME = re.compile(r"^(\d{1,2})(?::(\d{2}))?\s*([ap]\.?m?\.?)?$", re.IGNORECASE)

MINUTES_PER_DAY = 24 * 60

# Canonical weekday names, Monday first (matching ``datetime.weekday()``).
WEEKDAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
_DAY_INDEX = {day: i for i, day in enumerate(WEEKDAYS)}
# Full names and 3-letter abbreviations both resolve to the canonical weekday.
_DAY_ALIASES = {alias: day for day in WEEKDAYS for alias in (day, day[:3])}
# Split a day range on a dash or a space-delimited "to" ("to" is space-bounded so
# it doesn't split inside words like "Tours").
_DAY_RANGE_SEP = re.compile(rf"\s*[{_DASH_CLASS}]\s*|\s+to\s+", re.IGNORECASE)


def collapse_whitespace(value: str) -> str:
    """Trim and collapse internal whitespace runs to a single space."""
    return _WS.sub(" ", value).strip()


def text(value: str) -> str:
    """Canonical free-text form: whitespace-collapsed and casefolded."""
    return collapse_whitespace(value).casefold()


def phone(value: str, *, default_country: str = "1") -> str:
    """Canonical phone form ``+<digits>``.

    Strips formatting and applies a default country code when none is present, so
    ``555 123 4567`` and ``+1 (555) 123-4567`` compare equal. Raises ``ValueError``
    if there aren't enough digits to be a phone number.
    """
    had_plus = value.lstrip().startswith("+")
    digits = re.sub(r"\D", "", value)
    if len(digits) < 7:
        raise ValueError(f"not enough digits for a phone number: {value!r}")
    if not had_plus and len(digits) == 10:
        digits = default_country + digits
    return "+" + digits


def street(value: str) -> tuple[str, ...]:
    """Canonical street form: a tuple of normalized tokens.

    Lowercases, drops punctuation, expands directionals anywhere, and expands a
    street-type suffix only as the final token. So ``"123 Main St"`` becomes
    ``("123", "main", "street")`` while ``"123 St. John St."`` becomes
    ``("123", "st", "john", "street")`` — the leading "St" (Saint) is preserved.
    Compare two streets by equality of their token tuples.
    """
    cleaned = re.sub(r"[^\w\s]", " ", value.lower())
    tokens = collapse_whitespace(cleaned).split()
    last = len(tokens) - 1
    out: list[str] = []
    for index, token in enumerate(tokens):
        if token in _DIRECTIONALS:
            out.append(_DIRECTIONALS[token])
        elif index == last and token in _STREET_SUFFIXES:
            out.append(_STREET_SUFFIXES[token])
        else:
            out.append(token)
    return tuple(out)


def postal_code(value: str) -> str:
    """Canonical postal code: uppercased, inner spaces removed."""
    return re.sub(r"\s+", "", value).upper()


def url(value: str) -> str:
    """Canonical URL form: scheme and host lowercased; a leading ``www.``, trailing
    ``/``, fragment, and ``utm_*`` campaign-tracking parameters dropped.

    So ``HTTPS://www.TheFlip.museum/``, ``https://theflip.museum``, and
    ``https://www.theflip.museum/?utm_source=x`` compare equal (a bare domain and its
    ``www.`` form serve the same site, and listing sites often tag outbound links),
    while a different scheme, domain, path, or any other query parameter still
    differs. Raises ``ValueError`` for anything without a scheme and host.
    """
    parts = urlsplit(value.strip())
    if not parts.scheme or not parts.netloc:
        raise ValueError(f"not an absolute URL: {value!r}")
    path = parts.path.rstrip("/")
    params = parse_qsl(parts.query, keep_blank_values=True)
    query = urlencode([(k, v) for k, v in params if not k.lower().startswith("utm_")])
    host = parts.netloc.lower().removeprefix("www.")
    return urlunsplit((parts.scheme.lower(), host, path, query, ""))


def week_hours(windows: dict[str, list[str]]) -> dict[str, str]:
    """Per-weekday hours text from each day's ``"HH:MM - HH:MM"`` windows.

    Days with several windows are comma-joined (as ``day_hours`` reads them); a
    weekday with no windows — or missing from ``windows`` — is ``"closed"``.
    """
    return {day: ", ".join(windows.get(day, [])) or "closed" for day in WEEKDAYS}


def expand_days(label: str) -> list[str]:
    """Expand a day label into canonical weekdays.

    ``"Monday - Saturday"`` -> the six days; ``"Sunday"`` -> ``["sunday"]``;
    a wrap-around like ``"Saturday - Tuesday"`` -> sat, sun, mon, tue. Anything not
    recognizable as a day (or range) yields ``[]`` — so an unreadable label degrades
    to a missing day, never a guess.
    """
    parts = [part for part in _DAY_RANGE_SEP.split(label.strip().lower()) if part]
    days = [_DAY_ALIASES.get(part) for part in parts]
    if len(days) == 1 and days[0] is not None:
        return [days[0]]
    if len(days) == 2:
        first, last = days
        if first is None or last is None:
            return []
        start, end = _DAY_INDEX[first], _DAY_INDEX[last]
        if start <= end:
            return list(WEEKDAYS[start : end + 1])
        return list(WEEKDAYS[start:]) + list(WEEKDAYS[: end + 1])
    return []


def time_to_minutes(value: str) -> int:
    """Minutes since midnight for a clock time like ``"09:00"``, ``"9am"``, ``"5 PM"``, ``"8p"``.

    Raises ``ValueError`` on anything it can't parse.
    """
    match = _TIME.match(value.strip())
    if not match:
        raise ValueError(f"unparseable time: {value!r}")
    hour = int(match.group(1))
    minute = int(match.group(2) or 0)
    meridiem = (match.group(3) or "").replace(".", "").lower()
    if meridiem:
        if not 1 <= hour <= 12:
            raise ValueError(f"invalid 12-hour time: {value!r}")
        # Reduce to the first letter so "p", "pm", and "p.m." all mean PM.
        hour = hour % 12 + (12 if meridiem[0] == "p" else 0)
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise ValueError(f"invalid time: {value!r}")
    return hour * 60 + minute


def time_range(value: str) -> tuple[int, int]:
    """Parse an opening window like ``"10:00-17:00"`` or ``"6 PM - 2 AM"``.

    Returns ``(open_minutes, close_minutes)``. A window that crosses midnight has
    ``close > MINUTES_PER_DAY`` (e.g. ``18:00-02:00`` becomes ``(1080, 1560)``), so
    duration and comparison stay correct rather than wrapping to a negative span.
    """
    parts = _TIME_RANGE_SEP.split(value.strip(), maxsplit=1)
    if len(parts) != 2:
        raise ValueError(f"not a time range: {value!r}")
    start, end = time_to_minutes(parts[0]), time_to_minutes(parts[1])
    if end <= start:
        end += MINUTES_PER_DAY
    return start, end


def _window(item: object) -> tuple[int, int]:
    """One opening window from a ``{"open","close"}`` mapping or a range string."""
    if isinstance(item, str):
        return time_range(item)
    if isinstance(item, dict) and "open" in item and "close" in item:
        open_min = time_to_minutes(str(item["open"]))
        close_min = time_to_minutes(str(item["close"]))
        if close_min <= open_min:
            close_min += MINUTES_PER_DAY
        return open_min, close_min
    raise ValueError(f"hours window must be a range string or have open/close: {item!r}")


def day_hours(value: object) -> frozenset[tuple[int, int]] | str:
    """Canonicalize one day's hours into a comparable form.

    Accepts ``"closed"``; a raw range string (``"10:00 - 20:00"``) or several
    comma-separated ranges (``"9-12, 1-5"``); a single ``{"open","close"}`` mapping;
    or a list of any of those. Returns ``"closed"`` or a ``frozenset`` of
    ``(open, close)`` minute tuples so window order doesn't matter. This lets a
    source emit the *visible* hours text while ``facts.yaml`` uses whichever form
    is convenient — both normalize to the same value. Raises ``ValueError`` on
    shapes it can't model (the caller maps that to ``PARSE_ERROR``).
    """
    if isinstance(value, str):
        text_value = value.strip()
        if text_value.lower() == "closed":
            return "closed"
        return frozenset(_window(part.strip()) for part in text_value.split(",") if part.strip())

    windows = value if isinstance(value, list) else [value]
    return frozenset(_window(window) for window in windows)
