"""Tests for JSON-LD extraction and type filtering across multiple blocks."""

from __future__ import annotations

from webwatch.extract import structured

# A page with several JSON-LD blocks: breadcrumbs, the museum, and an event —
# the helpers must select the right one (agy Gap F).
MULTI_BLOCK = """
<html><head>
<script type="application/ld+json">
{"@context":"https://schema.org","@type":"BreadcrumbList","itemListElement":[]}
</script>
<script type="application/ld+json">
{"@context":"https://schema.org","@type":"Museum",
 "name":"The Flip","telephone":"+1 555 123 4567"}
</script>
<script type="application/ld+json">
{"@context":"https://schema.org","@type":"Event","name":"Repair Day"}
</script>
</head><body></body></html>
"""

GRAPH = """
<html><head>
<script type="application/ld+json">
{"@context":"https://schema.org","@graph":[
  {"@type":"Organization","name":"The Flip"},
  {"@type":"Event","name":"Tournament"}
]}
</script>
</head><body></body></html>
"""


def test_extract_jsonld_finds_all_blocks() -> None:
    assert len(structured.extract_jsonld(MULTI_BLOCK)) == 3


def test_graph_is_flattened() -> None:
    nodes = structured.extract_jsonld(GRAPH)
    names = {n.get("name") for n in nodes}
    assert names == {"The Flip", "Tournament"}


def test_extract_local_business_picks_museum_not_breadcrumb_or_event() -> None:
    business = structured.extract_local_business(MULTI_BLOCK)
    assert business is not None
    assert business["name"] == "The Flip"


def test_extract_events() -> None:
    events = structured.extract_events(MULTI_BLOCK)
    assert [e["name"] for e in events] == ["Repair Day"]


def test_absent_structured_data() -> None:
    assert structured.extract_local_business("<html><body>nothing</body></html>") is None
    assert structured.extract_jsonld("<html></html>") == []
