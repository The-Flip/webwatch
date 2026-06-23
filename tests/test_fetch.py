"""Tests for the fetch boundary: retries, honest failure, and block detection."""

from __future__ import annotations

import httpx
import pytest

from webwatch.fetch import DomainThrottle, FetchError, fetch, looks_blocked


def test_fetch_returns_text_and_sends_user_agent() -> None:
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["ua"] = request.headers["User-Agent"]
        return httpx.Response(200, html="<html><body>hi</body></html>")

    result = fetch("https://example.test/", transport=httpx.MockTransport(handler))
    assert "hi" in result.text
    assert result.status_code == 200
    assert not result.blocked
    assert "webwatch" in seen["ua"]


def test_fetch_retries_transient_then_succeeds() -> None:
    calls = {"n": 0}
    slept: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] < 3:
            return httpx.Response(503, html="<html>busy</html>")
        return httpx.Response(200, html="<html><body>ok</body></html>")

    result = fetch(
        "https://example.test/",
        transport=httpx.MockTransport(handler),
        max_retries=3,
        sleep=slept.append,
    )
    assert result.status_code == 200
    assert calls["n"] == 3
    assert len(slept) == 2  # slept between the two retries


def test_fetch_gives_up_and_raises_fetch_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, html="<html>down</html>")

    with pytest.raises(FetchError):
        fetch(
            "https://example.test/",
            transport=httpx.MockTransport(handler),
            max_retries=1,
            sleep=lambda _s: None,
        )


def test_fetch_4xx_is_fetch_error_not_retried() -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(404, html="<html>nope</html>")

    with pytest.raises(FetchError):
        fetch(
            "https://example.test/", transport=httpx.MockTransport(handler), sleep=lambda _s: None
        )
    assert calls["n"] == 1  # 404 is not retried


def test_fetch_detects_block_on_200() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, html="<html><title>Just a moment...</title></html>")

    result = fetch("https://example.test/", transport=httpx.MockTransport(handler))
    assert result.blocked
    assert result.block_reason


def test_fetch_detects_block_on_403_not_fetch_error() -> None:
    """Cloudflare-style 403 challenge must surface as BLOCKED, not FETCH_ERROR (agy Gap C)."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, html="<html>Attention Required! Cloudflare</html>")

    result = fetch("https://example.test/", transport=httpx.MockTransport(handler))
    assert result.blocked


def test_looks_blocked_flags_empty_js_shell() -> None:
    shell = "<html><body><div id='root'></div><script src='/app.js'></script></body></html>"
    assert looks_blocked(shell, 200) is not None


def test_looks_blocked_passes_real_page() -> None:
    page = "<html><body><h1>The Flip</h1><p>Open Saturdays 10-5.</p></body></html>"
    assert looks_blocked(page, 200) is None


def test_domain_throttle_waits_between_same_host() -> None:
    slept: list[float] = []
    clock = {"t": 0.0}
    throttle = DomainThrottle(delay=2.0, sleep=slept.append, now=lambda: clock["t"])

    throttle.wait("example.test")  # first call: no wait
    throttle.wait("example.test")  # immediately again: should wait the full delay
    assert slept == [2.0]
