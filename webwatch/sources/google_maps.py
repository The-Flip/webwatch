"""Source for The Flip's Google Maps listing, read through the Places API (New).

Google Maps place pages are JavaScript shells with no data in their HTML (and
scraping them is against Google's terms), so this source reads Google's official
Place Details endpoint instead:
``GET https://places.googleapis.com/v1/places/{PLACE_ID}`` with the API key and a
field mask sent as headers — never in the URL, so the key can't leak into errors.

The API *is* Google's canonical data, so there is no visible-vs-structured split and
no ``METADATA_DRIFT`` path: each JSON field is the observation. Doctrine still holds:

- A requested field the response omits is ``missing`` -> ``STRUCTURE_CHANGED``. We
  can't tell "not listed" from a field-mask/schema change, and ``MISMATCH`` must
  only come from a value actually read.
- The response ``id`` must be the place we asked for; otherwise every field is
  ``missing``. ``url``/``phone``/hours also ``require`` the ``name`` check, so a
  place-id now belonging to another business can't fan out into false MISMATCHes.
  ``business_status`` is deliberately *not* gated on the name: a renamed listing
  that is also marked closed must still raise the closure.
- No key configured -> :class:`~webwatch.fetch.FetchError` -> ``FETCH_ERROR``
  (unhealthy), never a ``SKIPPED`` that would quietly clear an alert.

Hours come from ``regularOpeningHours`` (which excludes holiday ``specialDays``, so
holidays can't cause a false MISMATCH). Google numbers days 0 = Sunday and omits
zero-valued ints (proto3 JSON), so both are handled explicitly. Days without a
period are closed; always-open and overnight periods are modeled; any other shape
makes every hours field unparseable rather than yielding a guessed partial week.
"""

from __future__ import annotations

import json
from typing import Any

from webwatch import config, normalize
from webwatch.checks.registry import HOURS_FIELDS, Check, hours_checks, listing_name
from webwatch.fetch import FetchError
from webwatch.sources.base import Observation, Observed, Source

# The Flip's Google place ID (from Google's Place ID Finder). Google can retire IDs;
# a 404 from the API (FETCH_ERROR) means it needs refreshing.
PLACE_ID = "ChIJsTdpH5YtDogRBflFk96koMo"

_FIELD_MASK = "id,displayName,businessStatus,nationalPhoneNumber,websiteUri,regularOpeningHours"
# Google's Point.day: 0 = Sunday ... 6 = Saturday (normalize.WEEKDAYS starts Monday).
_GOOGLE_DAYS = (
    "sunday",
    "monday",
    "tuesday",
    "wednesday",
    "thursday",
    "friday",
    "saturday",
)


class _UnmodeledHoursError(ValueError):
    """``regularOpeningHours`` has a shape we don't model."""


def _point(point: object) -> tuple[int, int, int]:
    """(day, hour, minute) of a Point; proto3 JSON omits zero values, so default 0."""
    if not isinstance(point, dict) or point.get("truncated"):
        raise _UnmodeledHoursError(f"unexpected point {point!r}")
    values = tuple(point.get(key, 0) for key in ("day", "hour", "minute"))
    day, hour, minute = values
    if not all(isinstance(v, int) for v in values) or not 0 <= day <= 6:
        raise _UnmodeledHoursError(f"unexpected point {point!r}")
    return day, hour, minute


def _clock(hour: int, minute: int) -> str:
    return f"{hour:02d}:{minute:02d}"


def _weekly_hours(opening_hours: dict[str, Any]) -> dict[str, str]:
    """Per-weekday ``"HH:MM - HH:MM"`` windows; ``"closed"`` for days without one.

    Raises :class:`_UnmodeledHoursError` for anything but plain, overnight, or
    always-open periods.
    """
    periods = opening_hours.get("periods")
    if not isinstance(periods, list):
        raise _UnmodeledHoursError("periods is not a list")

    # Always open: a single period opening Sunday 00:00 with no close.
    if len(periods) == 1 and isinstance(periods[0], dict) and "close" not in periods[0]:
        if _point(periods[0].get("open")) == (0, 0, 0):
            return dict.fromkeys(normalize.WEEKDAYS, "00:00 - 00:00")
        raise _UnmodeledHoursError("open period without a close")

    windows: dict[str, list[str]] = {day: [] for day in normalize.WEEKDAYS}
    for period in periods:
        if not isinstance(period, dict) or "close" not in period:
            raise _UnmodeledHoursError(f"unexpected period {period!r}")
        open_day, open_hour, open_minute = _point(period.get("open"))
        close_day, close_hour, close_minute = _point(period.get("close"))
        # Same day, or closing the next day (overnight; normalize handles the wrap).
        if close_day not in (open_day, (open_day + 1) % 7):
            raise _UnmodeledHoursError(f"period spans more than a day: {period!r}")
        window = f"{_clock(open_hour, open_minute)} - {_clock(close_hour, close_minute)}"
        windows[_GOOGLE_DAYS[open_day]].append(window)
    return normalize.week_hours(windows)


def _omitted(field: str) -> Observed[str]:
    return Observed.missing(f"{field} omitted from Places API response")


def _text_field(place: dict[str, Any], key: str) -> Observed[str]:
    value = place.get(key)
    if value is None:
        return _omitted(key)
    if not isinstance(value, str) or not value.strip():
        return Observed.unparseable(f"{key} is not a non-empty string: {value!r}")
    return Observed.found(value)


def _name(place: dict[str, Any]) -> Observed[str]:
    display_name = place.get("displayName")
    if display_name is None:
        return _omitted("displayName")
    text = display_name.get("text") if isinstance(display_name, dict) else None
    if not isinstance(text, str) or not text.strip():
        return Observed.unparseable(f"displayName has no text: {display_name!r}")
    return Observed.found(text)


def _hours(place: dict[str, Any]) -> dict[str, Observed[str]]:
    opening_hours = place.get("regularOpeningHours")
    if opening_hours is None:
        return {field: _omitted("regularOpeningHours") for field in HOURS_FIELDS}
    try:
        if not isinstance(opening_hours, dict):
            raise _UnmodeledHoursError("regularOpeningHours is not an object")
        weekly = _weekly_hours(opening_hours)
    except _UnmodeledHoursError as err:
        return {field: Observed.unparseable(str(err)) for field in HOURS_FIELDS}
    return {f"hours.{day}": Observed.found(value) for day, value in weekly.items()}


class GoogleMaps(Source):
    name = "google_maps"
    label = "Google Maps"
    url = f"https://places.googleapis.com/v1/places/{PLACE_ID}"
    tracks = frozenset({"name", "url", "phone", "business_status", *HOURS_FIELDS})

    def request_headers(self) -> dict[str, str]:
        key = config.GOOGLE_PLACES_API_KEY
        if not key:
            raise FetchError("WEBWATCH_GOOGLE_PLACES_API_KEY is not set")
        return {"X-Goog-Api-Key": key, "X-Goog-FieldMask": _FIELD_MASK}

    def observe(self, html: str) -> Observation:
        try:
            place = json.loads(html)
        except json.JSONDecodeError as err:
            return self._unparseable(f"response is not JSON: {err}")
        if not isinstance(place, dict):
            return self._unparseable("response is not a JSON object")

        if place.get("id") != PLACE_ID:
            note = f"response is for place {place.get('id')!r}, not {PLACE_ID!r}"
            return Observation(self.site, {f: Observed.missing(note) for f in self.tracks})

        fields: dict[str, Observed[str]] = {
            "name": _name(place),
            "url": _text_field(place, "websiteUri"),
            "phone": _text_field(place, "nationalPhoneNumber"),
            "business_status": _text_field(place, "businessStatus"),
            **_hours(place),
        }
        return Observation(self.site, fields)

    def _unparseable(self, note: str) -> Observation:
        return Observation(self.site, {f: Observed.unparseable(note) for f in self.tracks})


SOURCE = GoogleMaps()

CHECKS = [
    Check("name", listing_name, normalize.text),
    Check("business_status", lambda f: f.organization.business_status, normalize.text),
    Check("url", lambda f: f.organization.url, normalize.url, requires="name"),
    Check("phone", lambda f: f.organization.phone, normalize.phone, requires="name"),
    *hours_checks(requires="name"),
]
