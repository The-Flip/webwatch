"""Source for the museum's donate page, https://www.theflip.museum/donate.

The page's job is to send donors to an online checkout. Its main call to action is
an off-site link ("Donate Now" -> a Square checkout). This source reads where that
button points, and the check compares it to ``facts.yaml``'s ``donation_url``.
Whether that checkout is itself still live is the ``square_donation`` source's job.

Anchoring decision: the CTA is identified by meaning, not position. It's an ``<a>``
that is

- inside ``<main>`` (or, without one, outside ``<header>``/``<nav>``/``<footer>``),
- off-site: an absolute ``http(s)`` URL with a host other than the museum's, which
  drops the nav/footer ``/donate`` links and ``mailto:`` links, and
- labeled (by text, ``aria-label``, or an ``img[alt]``) with exactly one of a small
  set of donate phrases.

The phrase match is exact on purpose. "Donate a machine" (in-kind), a charity-rating
badge, or "Donate via PayPal" beside the main button aren't *the* donate button, and
counting them would turn a healthy page into a false "candidates disagree".

No candidate, or candidates pointing at different places, is ``missing`` ->
``STRUCTURE_CHANGED``: we can't tell which link is meant, so we don't guess. Every
candidate already satisfies ``normalize.url``, so this field has no ``PARSE_ERROR``
path. A malformed href simply isn't a candidate.
"""

from __future__ import annotations

from urllib.parse import urlsplit

from bs4 import BeautifulSoup, Tag

from webwatch import normalize
from webwatch.checks.registry import Check
from webwatch.sources.base import Observation, Observed, Source

#: Labels (after ``normalize.text``) that mark a link as the page's donate button.
CTA_LABELS = frozenset({"donate", "donate now", "make a donation", "give", "give now"})

_MUSEUM_HOST = "theflip.museum"
_CHROME = ("header", "nav", "footer")


def _content_links(soup: BeautifulSoup) -> list[Tag]:
    """Links in the page's main content: ``<main>``, else everything but the chrome."""
    main = soup.find("main")
    if isinstance(main, Tag):
        return main.find_all("a", href=True)
    return [a for a in soup.find_all("a", href=True) if a.find_parent(_CHROME) is None]


def _labels(link: Tag) -> set[str]:
    """Every accessible label the link carries, normalized."""
    raw = [link.get_text(" ", strip=True), str(link.get("aria-label") or "")]
    raw += [str(img.get("alt") or "") for img in link.find_all("img")]
    return {normalize.text(label) for label in raw if label.strip()}


def _offsite_url(href: str) -> str | None:
    """``href`` if it's an absolute ``http(s)`` URL off the museum's site, else None.

    An href ``urlsplit`` can't parse (e.g. ``http://[broken``) isn't a candidate.
    """
    url = href.strip()
    try:
        parts = urlsplit(url)
        hostname = parts.hostname
    except ValueError:
        return None
    # The museum is served from both theflip.museum and www.theflip.museum.
    host = (hostname or "").removeprefix("www.")
    if parts.scheme not in ("http", "https") or not host or host == _MUSEUM_HOST:
        return None
    return url


def donate_cta_urls(html: str) -> list[str]:
    """The off-site URLs of every donate call to action in the page's main content."""
    urls = []
    for link in _content_links(BeautifulSoup(html, "lxml")):
        url = _offsite_url(str(link["href"]))
        if url is not None and _labels(link) & CTA_LABELS:
            urls.append(url)
    return urls


class TheFlipMuseumDonate(Source):
    name = "theflip_museum_donate"
    label = "Donate page"
    url = "https://www.theflip.museum/donate"
    tracks = frozenset({"donation_url"})

    def observe(self, html: str) -> Observation:
        return Observation(self.site, {"donation_url": self._donation_url(html)})

    @staticmethod
    def _donation_url(html: str) -> Observed[str]:
        urls = donate_cta_urls(html)
        if not urls:
            return Observed.missing("no off-site donate button in the page's main content")
        distinct = {normalize.url(url) for url in urls}
        if len(distinct) > 1:
            return Observed.missing(f"donate buttons disagree: {sorted(distinct)}")
        return Observed.found(urls[0])


SOURCE = TheFlipMuseumDonate()

CHECKS = [Check("donation_url", lambda f: f.organization.donation_url, normalize.url)]
