"""The single HTTP boundary.

Every network request in webwatch goes through :func:`fetch`. It owns the
``User-Agent``, timeout, retry/backoff for transient errors, per-domain
politeness delay, and — crucially — *honest* failure classification:

- a network/HTTP error that persists after retries raises :class:`FetchError`
  (the caller maps it to ``CheckStatus.FETCH_ERROR``);
- a response that is actually a CAPTCHA/challenge/login wall/empty-JS shell is
  detected by :func:`looks_blocked` **on any status code** (Cloudflare often uses
  ``403``/``503``) and returned as a :class:`FetchResult` with ``blocked`` set, so
  the caller can map it to ``CheckStatus.BLOCKED`` rather than chasing a phantom
  layout bug.

The ``transport`` seam lets tests inject ``httpx.MockTransport`` and lets a future
JS-rendering fetcher (e.g. Playwright) slot in per-source.
"""

from __future__ import annotations

import re
import time
from collections.abc import Callable
from dataclasses import dataclass, field

import httpx

from webwatch import config

#: Statuses worth retrying — transient by nature.
_RETRYABLE = frozenset({429, 500, 502, 503, 504})

# Markers that betray a challenge/interstitial rather than the real page.
_BLOCK_MARKERS = (
    "just a moment",
    "attention required",
    "cf-browser-verification",
    "challenge-platform",
    "enable javascript and cookies to continue",
    "please verify you are a human",
    "captcha",
    "access denied",
)
_JS_MOUNT = re.compile(r"""<div[^>]+id=["'](root|app|__next)["'][^>]*>\s*</div>""", re.IGNORECASE)
_TAG = re.compile(r"<[^>]+>")


class FetchError(Exception):
    """A page could not be fetched (network/HTTP failure after retries)."""


@dataclass(frozen=True, slots=True)
class FetchResult:
    """A fetched page. ``blocked`` distinguishes an access barrier from real content."""

    url: str
    status_code: int
    text: str
    headers: dict[str, str] = field(default_factory=dict)
    blocked: bool = False
    block_reason: str | None = None


@dataclass
class DomainThrottle:
    """Enforce a minimum delay between requests to the same host.

    Clock and sleep are injectable so tests neither wait nor depend on wall time.
    """

    delay: float
    sleep: Callable[[float], None] = time.sleep
    now: Callable[[], float] = time.monotonic
    _last: dict[str, float] = field(default_factory=dict)

    def wait(self, host: str) -> None:
        previous = self._last.get(host)
        current = self.now()
        if previous is not None:
            elapsed = current - previous
            if elapsed < self.delay:
                self.sleep(self.delay - elapsed)
                current = self.now()
        self._last[host] = current


def _visible_text_length(html: str) -> int:
    return len(_TAG.sub(" ", html).strip())


def looks_blocked(text: str, status_code: int, headers: dict[str, str] | None = None) -> str | None:
    """Return a reason if the response looks like a block/challenge, else ``None``.

    Checks happen regardless of status code (challenges commonly arrive as 403/503).
    """
    lowered = text.lower()
    for marker in _BLOCK_MARKERS:
        if marker in lowered:
            return f"challenge/interstitial marker: {marker!r}"
    # An empty single-page-app shell: a mount node and scripts, but no real text.
    if _JS_MOUNT.search(text) and _visible_text_length(text) < 64:
        return "empty JS-hydration shell (no server-rendered content)"
    return None


def _backoff_seconds(response: httpx.Response | None, attempt: int, base: float) -> float:
    """Honor ``Retry-After`` when present, else exponential backoff."""
    if response is not None:
        retry_after = response.headers.get("Retry-After")
        if retry_after and retry_after.isdigit():
            return float(retry_after)
    return base * (2**attempt)


def fetch(
    url: str,
    *,
    transport: httpx.BaseTransport | None = None,
    throttle: DomainThrottle | None = None,
    max_retries: int | None = None,
    backoff_base: float = 0.5,
    sleep: Callable[[float], None] = time.sleep,
) -> FetchResult:
    """Fetch ``url`` and return a :class:`FetchResult`.

    Retries transient failures (``429``/``5xx`` and transport errors) up to
    ``max_retries`` times, then raises :class:`FetchError`. A block/challenge is
    returned (not raised) with ``blocked=True``.
    """
    retries = config.HTTP_MAX_RETRIES if max_retries is None else max_retries
    if throttle is not None:
        throttle.wait(httpx.URL(url).host)

    headers = {"User-Agent": config.USER_AGENT}
    last_error: Exception | None = None

    with httpx.Client(
        transport=transport,
        headers=headers,
        timeout=config.HTTP_TIMEOUT,
        follow_redirects=True,
    ) as client:
        for attempt in range(retries + 1):
            response: httpx.Response | None = None
            try:
                response = client.get(url)
            except httpx.HTTPError as err:
                last_error = err
            else:
                reason = looks_blocked(response.text, response.status_code, dict(response.headers))
                if reason is not None:
                    return FetchResult(
                        url=str(response.url),
                        status_code=response.status_code,
                        text=response.text,
                        headers=dict(response.headers),
                        blocked=True,
                        block_reason=reason,
                    )
                if response.status_code not in _RETRYABLE:
                    if response.is_success:
                        return FetchResult(
                            url=str(response.url),
                            status_code=response.status_code,
                            text=response.text,
                            headers=dict(response.headers),
                        )
                    raise FetchError(f"{url} returned HTTP {response.status_code}")
                last_error = FetchError(f"{url} returned HTTP {response.status_code}")

            if attempt < retries:
                sleep(_backoff_seconds(response, attempt, backoff_base))

    raise FetchError(f"failed to fetch {url} after {retries + 1} attempt(s)") from last_error
