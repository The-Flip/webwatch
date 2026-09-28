"""Tests for value normalization — the cosmetic-difference cases that must NOT
read as mismatches, plus the agy Gap-D traps (street/phone/midnight hours)."""

from __future__ import annotations

import pytest

from webwatch import normalize


@pytest.mark.parametrize(
    ("a", "b"),
    [
        ("  Hello   World ", "hello world"),
        ("The Flip", "the   flip"),
    ],
)
def test_text_equivalences(a: str, b: str) -> None:
    assert normalize.text(a) == normalize.text(b)


@pytest.mark.parametrize(
    ("a", "b"),
    [
        ("(555) 123-4567", "+1 555 123 4567"),
        ("555.123.4567", "5551234567"),
        ("+1 (555) 123-4567", "15551234567"),
    ],
)
def test_phone_equivalences(a: str, b: str) -> None:
    assert normalize.phone(a) == normalize.phone(b)


def test_phone_rejects_too_few_digits() -> None:
    with pytest.raises(ValueError):
        normalize.phone("call us")


def test_street_expands_trailing_suffix() -> None:
    assert normalize.street("123 Main St") == normalize.street("123 Main Street")


def test_street_does_not_mangle_leading_saint() -> None:
    """A leading 'St.' (Saint) must not be expanded to 'Street' (agy Gap D)."""
    assert normalize.street("123 St. John Ave") == ("123", "st", "john", "avenue")


def test_street_expands_directionals_anywhere() -> None:
    assert normalize.street("100 N Main St") == ("100", "north", "main", "street")


def test_time_to_minutes_handles_12h_and_24h() -> None:
    assert normalize.time_to_minutes("09:00") == 540
    assert normalize.time_to_minutes("9 AM") == 540
    assert normalize.time_to_minutes("5pm") == 1020
    assert normalize.time_to_minutes("12:30 AM") == 30


def test_time_to_minutes_single_letter_meridiem() -> None:
    """The museum site writes '10a'/'8p'; '8p' must be 20:00, not 08:00 (agy #1)."""
    assert normalize.time_to_minutes("10a") == 600
    assert normalize.time_to_minutes("8p") == 20 * 60
    assert normalize.time_to_minutes("12p") == 12 * 60
    assert normalize.time_to_minutes("12a") == 0


def test_time_range_crossing_midnight() -> None:
    """A window that crosses midnight keeps a positive span (agy Gap D)."""
    assert normalize.time_range("6 PM - 2 AM") == (18 * 60, 26 * 60)


def test_time_range_accepts_en_dash() -> None:
    assert normalize.time_range(f"10:00{chr(0x2013)}17:00") == (600, 1020)  # en dash


def test_day_hours_closed() -> None:
    assert normalize.day_hours("closed") == "closed"


def test_day_hours_window_order_insensitive() -> None:
    a = normalize.day_hours(
        [{"open": "09:00", "close": "12:00"}, {"open": "13:00", "close": "17:00"}]
    )
    b = normalize.day_hours(
        [{"open": "13:00", "close": "17:00"}, {"open": "09:00", "close": "12:00"}]
    )
    assert a == b


def test_day_hours_raw_string_equals_dict() -> None:
    """A source's visible hours text and a facts dict must normalize equal (agy Gap C)."""
    assert normalize.day_hours("10:00 - 20:00") == normalize.day_hours(
        {"open": "10:00", "close": "20:00"}
    )


def test_day_hours_comma_separated_double_window() -> None:
    raw = normalize.day_hours("09:00-12:00, 13:00-17:00")
    structured = normalize.day_hours(
        [{"open": "13:00", "close": "17:00"}, {"open": "09:00", "close": "12:00"}]
    )
    assert raw == structured


def test_day_hours_raw_string_crosses_midnight() -> None:
    assert normalize.day_hours("18:00 - 02:00") == frozenset({(18 * 60, 26 * 60)})


def test_day_hours_rejects_bad_shape() -> None:
    with pytest.raises(ValueError):
        normalize.day_hours({"open": "09:00"})  # missing close


def test_day_hours_rejects_unparseable_string() -> None:
    with pytest.raises(ValueError):
        normalize.day_hours("by appointment")


# --- day labels (expand_days) ---------------------------------------------------


def test_expand_full_range() -> None:
    assert normalize.expand_days("Monday - Saturday") == [
        "monday",
        "tuesday",
        "wednesday",
        "thursday",
        "friday",
        "saturday",
    ]


def test_expand_single_day() -> None:
    assert normalize.expand_days("Sunday") == ["sunday"]


def test_expand_non_day_is_empty() -> None:
    assert normalize.expand_days("Private Tours") == []


def test_expand_wraps_around_week() -> None:
    assert normalize.expand_days("Saturday - Tuesday") == [
        "saturday",
        "sunday",
        "monday",
        "tuesday",
    ]


def test_expand_en_dash_wraparound_abbreviations() -> None:
    # Apple Maps renders en-dash ranges that can wrap the week (Sunday through Monday).
    assert normalize.expand_days("Sun \u2013 Mon") == ["sunday", "monday"]


def test_expand_unrecognized_endpoint_is_empty() -> None:
    assert normalize.expand_days("Mon - Someday") == []


def test_expand_abbreviations_and_to() -> None:
    assert normalize.expand_days("Mon - Fri") == [
        "monday",
        "tuesday",
        "wednesday",
        "thursday",
        "friday",
    ]
    assert normalize.expand_days("Mon to Wed") == ["monday", "tuesday", "wednesday"]


# --- urls -------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("a", "b"),
    [
        ("https://www.theflip.museum/", "https://www.theflip.museum"),
        ("HTTPS://WWW.TheFlip.museum/", "https://www.theflip.museum/"),
        ("https://www.theflip.museum/#visit", "https://www.theflip.museum"),
        (
            "https://www.theflip.museum/?utm_source=apple&utm_medium=maps",
            "https://www.theflip.museum",
        ),
        ("https://theflip.museum/", "https://www.theflip.museum/"),
    ],
)
def test_url_equivalences(a: str, b: str) -> None:
    assert normalize.url(a) == normalize.url(b)


@pytest.mark.parametrize(
    ("a", "b"),
    [
        ("http://www.theflip.museum/", "https://www.theflip.museum/"),
        ("https://www.theflip.museum/visit", "https://www.theflip.museum/"),
        ("https://www.theflip.museum/?page=2", "https://www.theflip.museum/"),
        ("https://wwwtheflip.museum/", "https://theflip.museum/"),
        ("https://shop.theflip.museum/", "https://theflip.museum/"),
    ],
)
def test_url_differences(a: str, b: str) -> None:
    assert normalize.url(a) != normalize.url(b)


def test_url_rejects_relative() -> None:
    with pytest.raises(ValueError):
        normalize.url("theflip.museum")


def test_week_hours_joins_windows_and_closes_missing_days() -> None:
    week = normalize.week_hours({"monday": ["09:00 - 12:00", "13:00 - 17:00"], "tuesday": []})
    assert week["monday"] == "09:00 - 12:00, 13:00 - 17:00"
    assert week["tuesday"] == "closed"
    assert week["sunday"] == "closed"
    assert list(week) == list(normalize.WEEKDAYS)
