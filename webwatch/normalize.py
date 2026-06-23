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
_TIME = re.compile(r"^(\d{1,2})(?::(\d{2}))?\s*([ap]\.?m\.?)?$", re.IGNORECASE)

MINUTES_PER_DAY = 24 * 60


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


def time_to_minutes(value: str) -> int:
    """Minutes since midnight for a clock time like ``"09:00"``, ``"9am"``, ``"5 PM"``.

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
        hour = hour % 12 + (12 if meridiem == "pm" else 0)
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
