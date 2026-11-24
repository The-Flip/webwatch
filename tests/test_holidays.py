"""Tests for the named-holiday vocabulary: dates, next/previous occurrence, labels."""

from __future__ import annotations

import datetime as dt

import pytest

from webwatch import holidays


@pytest.mark.parametrize(
    ("year", "expected"),
    [
        (2026, dt.date(2026, 11, 26)),
        (2027, dt.date(2027, 11, 25)),
        (2028, dt.date(2028, 11, 23)),
        # Nov 1 is a Thursday: the earliest possible Thanksgiving.
        (2029, dt.date(2029, 11, 22)),
        # Nov 1 is a Friday: the latest possible Thanksgiving.
        (2030, dt.date(2030, 11, 28)),
    ],
)
def test_thanksgiving_is_fourth_thursday_of_november(year: int, expected: dt.date) -> None:
    assert holidays.date_of("thanksgiving", year) == expected


@pytest.mark.parametrize(
    ("name", "month", "day"),
    [
        ("christmas_eve", 12, 24),
        ("christmas", 12, 25),
        ("new_years_eve", 12, 31),
        ("new_years_day", 1, 1),
    ],
)
def test_fixed_date_holidays(name: str, month: int, day: int) -> None:
    assert holidays.date_of(name, 2026) == dt.date(2026, month, day)


def test_every_holiday_has_a_label() -> None:
    for name in holidays.NAMES:
        assert holidays.label(name)


def test_unknown_holiday_raises() -> None:
    with pytest.raises(KeyError):
        holidays.date_of("festivus", 2026)


def test_next_occurrence_on_the_day_is_today() -> None:
    assert holidays.next_occurrence("thanksgiving", dt.date(2026, 11, 26)) == dt.date(2026, 11, 26)


def test_next_occurrence_after_the_day_is_next_year() -> None:
    assert holidays.next_occurrence("thanksgiving", dt.date(2026, 11, 27)) == dt.date(2027, 11, 25)


def test_next_new_years_day_crosses_the_year_boundary() -> None:
    assert holidays.next_occurrence("new_years_day", dt.date(2026, 12, 26)) == dt.date(2027, 1, 1)


def test_previous_occurrence_is_strictly_before_today() -> None:
    assert holidays.previous_occurrence("thanksgiving", dt.date(2026, 11, 26)) == dt.date(
        2025, 11, 27
    )
    assert holidays.previous_occurrence("thanksgiving", dt.date(2026, 11, 27)) == dt.date(
        2026, 11, 26
    )


def test_previous_new_years_eve_crosses_the_year_boundary() -> None:
    assert holidays.previous_occurrence("new_years_eve", dt.date(2027, 1, 2)) == dt.date(
        2026, 12, 31
    )


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Thanksgiving", "thanksgiving"),
        ("Thanksgiving Day", "thanksgiving"),
        ("Christmas Eve", "christmas_eve"),
        ("Christmas Day", "christmas"),
        ("Christmas", "christmas"),
        ("New Year's Eve", "new_years_eve"),
        (f"New Year{chr(0x2019)}s Eve", "new_years_eve"),  # curly apostrophe
        ("New Years Day", "new_years_day"),
        ("  new year's   day ", "new_years_day"),
        ("New Year's Day:", "new_years_day"),
    ],
)
def test_holiday_for_label(text: str, expected: str) -> None:
    assert holidays.holiday_for_label(text) == expected


@pytest.mark.parametrize("text", ["Xmas", "Christmas Week", "Monday", "", "Private Tours"])
def test_unrecognized_label_is_none(text: str) -> None:
    # Unrecognized labels are never guessed into a holiday.
    assert holidays.holiday_for_label(text) is None


def test_aliases_are_stored_in_label_key_form() -> None:
    # An alias with capitals or an apostrophe would otherwise silently never match.
    for name in holidays.NAMES:
        for alias in holidays._HOLIDAYS[name].aliases:
            assert holidays.holiday_for_label(alias) == name
