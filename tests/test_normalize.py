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


def test_day_hours_rejects_bad_shape() -> None:
    with pytest.raises(ValueError):
        normalize.day_hours({"open": "09:00"})  # missing close
