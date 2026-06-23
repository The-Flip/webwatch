"""Locate values in HTML by *stable, meaningful* anchors — never positional CSS.

Anchors are the visible/authoritative half of extraction (see ``docs/Extraction.md``).
Every locator returns either :class:`Found` (a value we are confident in) or
:class:`NotFound` (with a reason) — **never** a bare string or ``None`` that a
caller could mistake for a real value. That distinction is what lets a source map
"region missing" to ``STRUCTURE_CHANGED`` instead of guessing.
"""

from __future__ import annotations

from dataclasses import dataclass

from bs4 import BeautifulSoup, Tag

from webwatch import normalize

# Elements that conventionally label a value, paired with how to reach the value.
_LABEL_TAGS = {"dt": "dd", "th": "td"}


@dataclass(frozen=True, slots=True)
class Found[T]:
    value: T


@dataclass(frozen=True, slots=True)
class NotFound:
    reason: str


# A located string, or an explanation of why it wasn't found.
Anchor = Found[str] | NotFound


def _clean(node: Tag) -> str:
    return normalize.collapse_whitespace(node.get_text(" ", strip=True))


def by_itemprop(soup: BeautifulSoup, prop: str) -> Anchor:
    """schema.org microdata: an element with ``itemprop="prop"``.

    Prefers an explicit ``content`` attribute (used on ``meta``/``time``), else the
    element's visible text.
    """
    node = soup.select_one(f'[itemprop="{prop}"]')
    if not isinstance(node, Tag):
        return NotFound(f"no element with itemprop={prop!r}")
    content = node.get("content")
    if isinstance(content, str) and content.strip():
        return Found(content.strip())
    text = _clean(node)
    return Found(text) if text else NotFound(f"itemprop={prop!r} present but empty")


def by_microformat(soup: BeautifulSoup, class_name: str) -> Anchor:
    """Microformats (h-card / h-event): an element carrying ``class_name``."""
    node = soup.find(class_=class_name)
    if not isinstance(node, Tag):
        return NotFound(f"no element with class {class_name!r}")
    text = _clean(node)
    return Found(text) if text else NotFound(f"class {class_name!r} present but empty")


def by_label(soup: BeautifulSoup, label: str) -> Anchor:
    """A definition/table value sitting next to a label cell.

    Finds a ``<dt>``/``<th>`` whose text matches ``label`` and returns the paired
    ``<dd>``/``<td>``. Matching is whitespace- and case-insensitive.
    """
    target = normalize.text(label)
    for label_tag, value_tag in _LABEL_TAGS.items():
        for node in soup.find_all(label_tag):
            if not isinstance(node, Tag) or normalize.text(node.get_text()) != target:
                continue
            value = node.find_next_sibling(value_tag)
            if isinstance(value, Tag):
                text = _clean(value)
                if text:
                    return Found(text)
                return NotFound(f"label {label!r} found but its value is empty")
            return NotFound(f"label {label!r} found but no {value_tag} value beside it")
    return NotFound(f"no label matching {label!r}")
