"""Tests for semantic anchors — and that a missing region is an explicit NotFound."""

from __future__ import annotations

from bs4 import BeautifulSoup

from webwatch.extract import anchors
from webwatch.extract.anchors import Found, NotFound


def soup(html: str) -> BeautifulSoup:
    return BeautifulSoup(html, "lxml")


def test_by_itemprop_prefers_content_attribute() -> None:
    result = anchors.by_itemprop(
        soup('<meta itemprop="telephone" content="+1 555 123 4567">'), "telephone"
    )
    assert isinstance(result, Found)
    assert result.value == "+1 555 123 4567"


def test_by_itemprop_falls_back_to_text() -> None:
    result = anchors.by_itemprop(soup('<span itemprop="name"> The Flip </span>'), "name")
    assert isinstance(result, Found)
    assert result.value == "The Flip"


def test_by_itemprop_missing_is_notfound() -> None:
    assert isinstance(anchors.by_itemprop(soup("<div>nothing</div>"), "name"), NotFound)


def test_by_microformat() -> None:
    result = anchors.by_microformat(soup('<p class="p-tel">555-1234</p>'), "p-tel")
    assert isinstance(result, Found)
    assert result.value == "555-1234"


def test_by_label_matches_dt_dd() -> None:
    html = "<dl><dt>Hours</dt><dd>Sat 10-5</dd><dt>Phone</dt><dd>555-1234</dd></dl>"
    result = anchors.by_label(soup(html), "hours")  # case-insensitive
    assert isinstance(result, Found)
    assert result.value == "Sat 10-5"


def test_by_label_missing_is_notfound_with_reason() -> None:
    result = anchors.by_label(soup("<dl><dt>Phone</dt><dd>x</dd></dl>"), "Hours")
    assert isinstance(result, NotFound)
    assert "hours" in result.reason.lower()


def test_by_label_present_but_empty_value() -> None:
    result = anchors.by_label(soup("<dl><dt>Hours</dt><dd></dd></dl>"), "Hours")
    assert isinstance(result, NotFound)
