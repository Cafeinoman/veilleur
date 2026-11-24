# SPDX-License-Identifier: EUPL-1.2
"""The networked HTTP client (spec EF-06, ES-08): SSRF guard, redirections, limits, cache, robots.txt."""

from __future__ import annotations

import gzip
import ipaddress
import socket
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from veilleur.adapters.http import guard
from veilleur.adapters.http.cache import CachedResponse, SqliteCache
from veilleur.adapters.http.client import RawResponse
from veilleur.adapters.http.transport import SocketTransport
from veilleur.core.domain.errors import CollectorError

from .http_fakes import PUBLIC, FakeWeb, client


def _code(web: FakeWeb, url: str, **kwargs: Any) -> str:
    with pytest.raises(CollectorError) as caught:
        client(web).get(url, **kwargs)
    return caught.value.code


REFUSED = [
    "127.0.0.1",
    "127.1.2.3",
    "0.0.0.0",
    "10.1.2.3",
    "172.16.0.1",
    "172.31.255.255",
    "192.168.1.1",
    "169.254.169.254",
    "100.64.0.1",
    "100.127.255.254",
    "224.0.0.1",
    "239.255.255.250",
    "255.255.255.255",
    "240.0.0.1",
    "192.0.2.1",
    "198.18.0.1",
    "192.88.99.1",
    "::1",
    "::",
    "fe80::1",
    "fc00::1",
    "fd12:3456::1",
    "ff02::1",
    "ff0e::1",
    "::ffff:127.0.0.1",
    "::ffff:10.0.0.1",
    "64:ff9b::7f00:1",
    "64:ff9b::a00:1",
    "2002:7f00:1::1",
    "2002:c0a8:101::1",
    "2001::1",
    "2001:db8::1",
    "fec0::1",
]
ALLOWED = ["93.184.215.14", "8.8.8.8", "2606:4700:4700::1111", "::ffff:8.8.8.8", "64:ff9b::808:808", "2002:808:808::1"]


@pytest.mark.parametrize("address", REFUSED)
def test_guard_refuses_internal_addresses(address: str) -> None:
    assert not guard.is_allowed(ipaddress.ip_address(address))


@pytest.mark.parametrize("address", ALLOWED)
def test_guard_allows_global_addresses(address: str) -> None:
    assert guard.is_allowed(ipaddress.ip_address(address))


@pytest.mark.parametrize("address", ["127.0.0.1", "10.0.0.1", "::1", "169.254.169.254", "100.100.100.100"])
def test_a_name_resolving_to_an_internal_address_is_refused_before_connecting(address: str) -> None:
    web = FakeWeb(dns={"trap.example.org": [address]})
    assert _code(web, "https://trap.example.org/feed") == "address_refused"
    assert web.sent == []


def test_one_internal_address_among_public_ones_is_enough_to_refuse() -> None:
    """DNS trap: a name with a public and a private address."""
    web = FakeWeb(dns={"mixed.example.org": [PUBLIC, "192.168.0.1"]})
    assert _code(web, "https://mixed.example.org/") == "address_refused"
    assert web.sent == []


def test_literal_addresses_are_checked_too() -> None:
    web = FakeWeb(dns={"127.0.0.1": ["127.0.0.1"], "::1": ["::1"]})
    assert _code(web, "http://127.0.0.1/") == "address_refused"
    assert _code(web, "http://[::1]:8080/") == "address_refused"
    assert web.sent == []


def test_the_connection_goes_to_the_checked_address() -> None:
    """The name is never resolved again after the check (DNS rebinding)."""
    web = FakeWeb()
    web.page("feed.example.org", "/a", "ok", "text/plain")
    resolved: list[str] = []

    def resolve(host: str, port: int) -> list[str]:
        resolved.append(host)
        return [PUBLIC] if len(resolved) <= 2 else ["127.0.0.1"]

    http = client(web)
    http._resolve = resolve
    assert http.get("https://feed.example.org/a").body == b"ok"
    assert {s.address for s in web.sent} == {PUBLIC}
    assert all(s.host == "feed.example.org" for s in web.sent)


def test_a_redirection_to_an_internal_address_is_refused() -> None:
    web = FakeWeb(dns={"inside.example.org": ["10.0.0.5"]})
    web.page("feed.example.org", "/old", "", "text/plain")
    web.pages[("feed.example.org", "/old")] = RawResponse(302, {"location": "http://inside.example.org/admin"}, b"")
    assert _code(web, "https://feed.example.org/old") == "address_refused"
    assert not any(s.host == "inside.example.org" for s in web.sent)


def test_a_redirection_to_a_literal_internal_address_is_refused() -> None:
    web = FakeWeb(dns={"169.254.169.254": ["169.254.169.254"]})
    web.page("feed.example.org", "/old", "", "text/plain")
    web.pages[("feed.example.org", "/old")] = RawResponse(
        301, {"location": "http://169.254.169.254/latest/meta-data/"}, b""
    )
    assert _code(web, "https://feed.example.org/old") == "address_refused"


def test_redirections_are_followed_and_capped() -> None:
    web = FakeWeb()
    web.page("feed.example.org", "/new", "<rss/>", "application/rss+xml")
    web.pages[("feed.example.org", "/old")] = RawResponse(301, {"location": "/new"}, b"")
    response = client(web).get("https://feed.example.org/old")
    assert response.url == "https://feed.example.org/new"
    assert response.body == b"<rss/>"
    web.pages[("feed.example.org", "/loop")] = RawResponse(302, {"location": "/loop"}, b"")
    assert _code(web, "https://feed.example.org/loop") == "too_many_redirects"


@pytest.mark.parametrize(
    "url",
    [
        "ftp://example.org/",
        "file:///etc/passwd",
        "gopher://example.org/",
        "https://user:pass@example.org/",
        "https:///nohost",
        "https://example.org:99999/",
        "javascript:alert(1)",
        "https://exa mple.org/",
    ],
)
def test_bad_addresses_are_refused(url: str) -> None:
    web = FakeWeb(dns={"example.org": [PUBLIC]})
    assert _code(web, url) == "bad_url"
    assert web.sent == []


def test_unknown_host() -> None:
    assert _code(FakeWeb(), "https://nowhere.example.org/") == "dns_failed"


def test_response_size_is_capped() -> None:
    web = FakeWeb()
    web.page("big.example.org", "/", b"x" * 2000, "text/plain")
    with pytest.raises(CollectorError) as caught:
        client(web, max_bytes=1000).get("https://big.example.org/")
    assert caught.value.code == "response_too_large"


def test_gzip_bombs_are_capped() -> None:
    web = FakeWeb()
    web.page("bomb.example.org", "/", gzip.compress(b"0" * 100_000), "text/plain", **{"content-encoding": "gzip"})
    with pytest.raises(CollectorError) as caught:
        client(web, max_bytes=1000).get("https://bomb.example.org/")
    assert caught.value.code == "response_too_large"
    web.page("zip.example.org", "/", gzip.compress(b"hello"), "text/plain", **{"content-encoding": "gzip"})
    assert client(web).get("https://zip.example.org/").body == b"hello"


def test_content_type_is_checked() -> None:
    web = FakeWeb()
    web.page("feed.example.org", "/", "<html/>", "text/html; charset=utf-8")
    assert _code(web, "https://feed.example.org/", accept=("application/json",)) == "unexpected_content_type"
    assert client(web).get("https://feed.example.org/", accept=("text/*",)).body == b"<html/>"


def test_http_errors_have_a_code_without_detail() -> None:
    web = FakeWeb()
    web.pages[("down.example.org", "/")] = RawResponse(503, {}, b"internal stack trace")
    web.dns["down.example.org"] = [PUBLIC]
    assert _code(web, "https://down.example.org/") == "http_503"
    assert _code(web, "https://down.example.org/missing") == "http_404"


def test_network_failure_and_timeout() -> None:
    class Failing(FakeWeb):
        def request(self, **kwargs: Any) -> RawResponse:
            raise ConnectionRefusedError("detail")

    web = Failing(dns={"down.example.org": [PUBLIC]})
    assert _code(web, "https://down.example.org/") == "network_error"

    class Slow(FakeWeb):
        def request(self, **kwargs: Any) -> RawResponse:
            self.clock += 100
            return RawResponse(200, {"content-type": "text/plain"}, b"late")

    assert _code(Slow(dns={"slow.example.org": [PUBLIC]}), "https://slow.example.org/") == "timeout"


def test_user_agent_and_headers() -> None:
    web = FakeWeb()
    web.page("feed.example.org", "/", "ok", "text/plain")
    client(web).get("https://feed.example.org/", accept=("text/plain",))
    sent = web.requests_to("/")[0]
    assert sent.headers["User-Agent"].startswith("Veilleur/")
    assert sent.headers["User-Agent"].endswith("(+https://veille.example.org)")
    assert sent.headers["Accept"] == "text/plain"
    assert "Authorization" not in sent.headers and "Cookie" not in sent.headers


def test_robots_txt_is_obeyed_and_read_once() -> None:
    web = FakeWeb()
    web.page("site.example.org", "/robots.txt", "User-agent: Veilleur\nDisallow: /private\n", "text/plain")
    web.page("site.example.org", "/public", "ok", "text/plain")
    web.page("site.example.org", "/private/x", "secret", "text/plain")
    http = client(web)
    assert http.get("https://site.example.org/public").body == b"ok"
    with pytest.raises(CollectorError) as caught:
        http.get("https://site.example.org/private/x")
    assert caught.value.code == "robots_disallowed"
    assert len(web.requests_to("/robots.txt")) == 1
    assert web.requests_to("/private/x") == []


def test_robots_txt_that_cannot_be_read_refuses() -> None:
    web = FakeWeb()
    web.page("site.example.org", "/page", "ok", "text/plain")
    web.pages[("site.example.org", "/robots.txt")] = RawResponse(500, {}, b"")
    assert _code(web, "https://site.example.org/page") == "robots_unavailable"


def test_host_delay_and_quota() -> None:
    web = FakeWeb()
    web.page("feed.example.org", "/", "ok", "text/plain")
    http = client(web, host_interval=2.0, host_quota=3)
    http.get("https://feed.example.org/")  # robots.txt, then the page: 2 requests
    assert web.slept == [2.0]
    with pytest.raises(CollectorError) as caught:
        http.get("https://feed.example.org/")
        http.get("https://feed.example.org/")
    assert caught.value.code == "host_quota_exceeded"


def test_conditional_requests_use_the_cache() -> None:
    web = FakeWeb()
    web.page("feed.example.org", "/", "v1", "text/plain", etag='"abc"')
    http = client(web)
    assert http.get("https://feed.example.org/").body == b"v1"
    web.pages[("feed.example.org", "/")] = RawResponse(304, {}, b"")
    assert http.get("https://feed.example.org/").body == b"v1"
    assert web.requests_to("/")[-1].headers["If-None-Match"] == '"abc"'


def test_sqlite_cache(tmp_path: Path) -> None:
    now = datetime(2026, 11, 18, tzinfo=UTC)
    cache = SqliteCache(tmp_path / "cache" / "http.db", now)
    entry = CachedResponse("https://a.example.org/", {"etag": "x"}, b"body", "x", None, now)
    cache.put("https://a.example.org/", entry)
    assert cache.get("https://a.example.org/") == entry
    cache.close()
    assert (tmp_path / "cache" / "http.db").stat().st_mode & 0o777 == 0o600
    later = SqliteCache(tmp_path / "cache" / "http.db", datetime(2027, 1, 1, tzinfo=UTC))
    assert later.get("https://a.example.org/") is None
    later.close()


def test_socket_transport_connects_to_the_checked_address(monkeypatch: pytest.MonkeyPatch) -> None:
    """The real transport never resolves the host name: it connects to the address it is given."""
    connected: list[tuple[str, int]] = []

    def fake_connect(address: tuple[str, int], timeout: float) -> socket.socket:
        connected.append(address)
        raise ConnectionRefusedError

    monkeypatch.setattr(socket, "create_connection", fake_connect)
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **k: pytest.fail("resolved again"))
    for scheme in ("http", "https"):
        with pytest.raises(OSError):
            SocketTransport().request(
                scheme=scheme,
                address=PUBLIC,
                host="feed.example.org",
                port=443,
                target="/",
                headers={},
                timeout=1.0,
                max_bytes=10,
            )
    assert connected == [(PUBLIC, 443), (PUBLIC, 443)]
