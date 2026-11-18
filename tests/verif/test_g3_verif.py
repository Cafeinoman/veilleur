# SPDX-License-Identifier: EUPL-1.2
"""Independent check of milestone G3 (cahier EF-02 to EF-06, EF-20, EF-52, ES-08, ES-09, §10 of 2026-11-18;
protocol §9 for `GET /v1/subscriptions`).

No network: answers come from `tests.server.http_fakes.FakeWeb`; the socket transport is fed through a
`socket.socketpair()` (no port is opened); the WSGI application is called directly.
"""

from __future__ import annotations

import contextlib
import hashlib
import hmac
import ipaddress
import json
import logging
import socket
import subprocess
import sys
import threading
import time
from collections.abc import Iterator, Mapping
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest

from tests.server.fakes import FakeClock, World, make_world
from tests.server.http_fakes import PUBLIC, FakeWeb, client
from tests.verif.test_g2_api import Caller
from veilleur.adapters.collectors import html
from veilleur.adapters.collectors.json_api import JsonApiCollector
from veilleur.adapters.collectors.rss import RssCollector
from veilleur.adapters.filters import KeywordsFilter, RegexFilter
from veilleur.adapters.http import NetworkHttpClient, OfflineHttpClient, guard
from veilleur.adapters.http.client import RawResponse
from veilleur.adapters.http.transport import SocketTransport
from veilleur.adapters.notifiers import NtfyNotifier, WebhookNotifier
from veilleur.adapters.plugins import installed
from veilleur.apps.server.config import Config
from veilleur.apps.server.context import open_app
from veilleur.core.domain.errors import CollectorError, VeilleurError
from veilleur.core.ports.plugins import FilterItem, Plugins
from veilleur.core.services import pairing, round, subscriptions
from veilleur.core.services.subscriptions import TeamSubscription, parse_spec, sync_team

UID1 = "11111111111111111111111111111111"
UID2 = "22222222222222222222222222222222"
UID3 = "33333333333333333333333333333333"


@pytest.fixture
def world(tmp_path: Path) -> Iterator[World]:
    w = make_world(tmp_path / "state")
    yield w
    w.app.close()


def _code(web: FakeWeb, url: str, **kwargs: Any) -> str:
    with pytest.raises(CollectorError) as caught:
        client(web).get(url, **kwargs)
    return caught.value.code


# --- ES-08: SSRF guard ---------------------------------------------------------------------------------------------

MORE_REFUSED = [
    "::127.0.0.1",  # IPv4-compatible (deprecated)
    "::ffff:0:7f00:1",  # IPv4-translated
    "::ffff:169.254.169.254",
    "64:ff9b:1::a00:1",  # local-use NAT64
    "100::1",  # discard-only
    "2001:10::1",  # ORCHID
    "2001:2::1",  # benchmarking
    "fe80::1%eth0",  # scoped link-local
    "fd00:ec2::254",  # cloud metadata (ULA)
    "2001:0:4136:e378:8000:63bf:3fff:fdd2",  # Teredo
    "0.1.2.3",
    "192.0.0.170",
    "198.51.100.7",
    "203.0.113.9",
    "255.255.255.255",
]


@pytest.mark.parametrize("address", MORE_REFUSED)
def test_guard_refuses_more_internal_or_special_addresses(address: str) -> None:
    assert not guard.is_allowed(ipaddress.ip_address(address))


@pytest.mark.parametrize("address", ["::ffff:10.0.0.1", "64:ff9b::a9fe:a9fe", "fe80::1%eth0", "2002:a00:1::1"])
def test_aaaa_records_hiding_internal_ipv4_are_refused_before_connecting(address: str) -> None:
    web = FakeWeb(dns={"v6trap.example.org": [address]})
    assert _code(web, "https://v6trap.example.org/") == "address_refused"
    assert web.sent == []


@pytest.mark.parametrize(
    "location", ["file:///etc/passwd", "ftp://ftp.example.org/x", "gopher://example.org/", "https://u:p@example.org/"]
)
def test_redirection_to_another_scheme_or_with_credentials_is_refused(location: str) -> None:
    web = FakeWeb(dns={"example.org": [PUBLIC]})
    web.page("feed.example.org", "/old", "", "text/plain")
    web.pages[("feed.example.org", "/old")] = RawResponse(302, {"location": location}, b"")
    assert _code(web, "https://feed.example.org/old") == "bad_url"
    assert all(s.host == "feed.example.org" for s in web.sent)


def test_internal_address_at_the_third_hop_is_refused() -> None:
    web = FakeWeb(dns={"a.example.org": [PUBLIC], "b.example.org": [PUBLIC], "c.example.org": ["10.9.8.7"]})
    web.pages[("a.example.org", "/")] = RawResponse(301, {"location": "https://b.example.org/"}, b"")
    web.pages[("b.example.org", "/")] = RawResponse(307, {"location": "http://c.example.org:8080/admin"}, b"")
    assert _code(web, "https://a.example.org/") == "address_refused"
    assert not any(s.host == "c.example.org" for s in web.sent)


def test_robots_txt_redirected_to_an_internal_address_is_never_fetched() -> None:
    web = FakeWeb(dns={"inside.example.org": ["192.168.1.1"]})
    web.page("site.example.org", "/page", "ok", "text/plain")
    web.pages[("site.example.org", "/robots.txt")] = RawResponse(
        302, {"location": "http://inside.example.org/robots.txt"}, b""
    )
    with pytest.raises(CollectorError):
        client(web).get("https://site.example.org/page")
    assert not any(s.host == "inside.example.org" for s in web.sent)
    assert web.requests_to("/page") == []


def test_json_api_next_page_to_an_internal_address_is_refused() -> None:
    web = FakeWeb(dns={"inside.example.org": ["127.0.0.1"]})
    web.page("api.example.org", "/items", json.dumps({"items": [{"id": 1}], "next": "http://inside.example.org/"}),
             "application/json")  # fmt: skip
    params = {"url": "https://api.example.org/items", "items_path": "items", "key_field": "id",
              "next_path": "next", "max_pages": 3}  # fmt: skip
    with pytest.raises(CollectorError) as caught:
        JsonApiCollector().collect(params, None, client(web))
    assert caught.value.code == "address_refused"
    assert not any(s.host == "inside.example.org" for s in web.sent)


def test_client_logs_no_address_nor_query_on_failure(caplog: pytest.LogCaptureFixture) -> None:
    """ES-09: a subscription parameter (here an address with a token) never reaches the logs."""

    class Failing(FakeWeb):
        def request(self, **kwargs: Any) -> RawResponse:
            raise ConnectionResetError(f"reset by {kwargs['host']}{kwargs['target']}")

    web = Failing(dns={"down.example.org": [PUBLIC]})
    caplog.set_level(logging.DEBUG)
    assert _code(web, "https://down.example.org/feed?token=s3cr3t-value") == "network_error"
    assert "s3cr3t" not in caplog.text and "down.example.org" not in caplog.text


@pytest.mark.xfail(strict=True, reason="minor: a cached answer (304) is not checked against the expected types")
def test_a_cached_answer_is_checked_against_the_expected_content_types() -> None:
    """ES-08: the content type is checked; a 304 serves a copy fetched earlier, maybe for another collector."""
    web = FakeWeb()
    web.page("site.example.org", "/x", "<html><body>page</body></html>", "text/html", etag='"v1"')
    http = client(web)
    http.get("https://site.example.org/x", accept=("text/html",))
    web.pages[("site.example.org", "/x")] = RawResponse(304, {}, b"")
    with pytest.raises(CollectorError) as caught:
        http.get("https://site.example.org/x", accept=("application/rss+xml",))
    assert caught.value.code == "unexpected_content_type"


def test_socket_transport_caps_the_duration_even_for_slowly_dripped_headers(monkeypatch: pytest.MonkeyPatch) -> None:
    """ES-08 / §10: the duration of a request is capped (30 s by default). A hostile source that sends its status line
    and headers one byte at a time must not hold the request (hence the round) past that cap."""
    server, near = socket.socketpair()
    stop = threading.Event()

    def fake_connect(address: Any, timeout: float | None = None, *args: Any, **kwargs: Any) -> socket.socket:
        near.settimeout(timeout)
        return near

    def drip() -> None:
        try:
            server.recv(65536)
            server.sendall(b"HTTP/1.1 200 OK\r\nContent-Type: text/plain\r\nX-Slow: ")
            end = time.monotonic() + 6.0
            while time.monotonic() < end and not stop.is_set():
                server.sendall(b"x")
                time.sleep(0.2)
            server.sendall(b"\r\nContent-Length: 2\r\n\r\nok")
        except OSError:
            pass

    monkeypatch.setattr(socket, "create_connection", fake_connect)
    thread = threading.Thread(target=drip, daemon=True)
    thread.start()
    started = time.monotonic()
    with contextlib.suppress(OSError):
        SocketTransport().request(
            scheme="http", address=PUBLIC, host="slow.example.org", port=80, target="/",
            headers={"Host": "slow.example.org"}, timeout=1.0, max_bytes=1000,
        )  # fmt: skip
    elapsed = time.monotonic() - started
    stop.set()
    server.close()
    thread.join(2)
    assert elapsed < 3.0, f"a 1 s request lasted {elapsed:.1f} s"


# --- EF-06: offline mode, cache --------------------------------------------------------------------------------------


def _open(tmp_path: Path, **config: Any) -> Any:
    return open_app(Config(state_dir=tmp_path / "state", public_url="https://veille.example.org", **config),
                    plugins=Plugins({}, {}, {}), clock=FakeClock(), notifiers=[])  # fmt: skip


def test_offline_true_uses_the_offline_client(tmp_path: Path) -> None:
    app = _open(tmp_path, offline=True)
    try:
        assert isinstance(app.core.http, OfflineHttpClient)
        assert not (tmp_path / "state" / "cache" / "http.db").exists()
    finally:
        app.close()


def test_networked_client_by_default_with_a_private_cache(tmp_path: Path) -> None:
    app = _open(tmp_path)
    try:
        assert isinstance(app.core.http, NetworkHttpClient)
        assert app.core.http.user_agent.endswith("(+https://veille.example.org)")
        cache = tmp_path / "state" / "cache" / "http.db"
        assert cache.stat().st_mode & 0o077 == 0
    finally:
        app.close()


# --- EF-02, EF-03: collectors ----------------------------------------------------------------------------------------


def test_rss_item_without_guid_has_no_key_but_its_link_and_the_feed_is_never_complete() -> None:
    feed = (b'<?xml version="1.0"?><rss version="2.0"><channel><title>t</title>'
            b"<item><title>A</title><link>https://example.org/a</link></item></channel></rss>")  # fmt: skip
    web = FakeWeb()
    web.page("feed.example.org", "/rss", feed, "application/rss+xml; charset=utf-8")
    collected = RssCollector().collect({"url": "https://feed.example.org/rss"}, None, client(web))
    assert collected.complete is False
    (item,) = collected.items
    assert item.key is None and item.url == "https://example.org/a"


@pytest.mark.parametrize(
    "document",
    [
        b'<?xml version="1.0"?><!DOCTYPE r [<!ENTITY % p SYSTEM "file:///etc/passwd"> %p;]><rss/>',
        b'<?xml version="1.0"?><!DOCTYPE rss SYSTEM "http://example.org/x.dtd"><rss/>',
        b'<?xml version="1.0"?><rss version="2.0"><channel><item><title>&xxe;</title></item></channel></rss>',
    ],
)
def test_rss_refuses_dtds_and_undeclared_entities(document: bytes) -> None:
    web = FakeWeb()
    web.page("feed.example.org", "/rss", document, "application/rss+xml")
    with pytest.raises(CollectorError) as caught:
        RssCollector().collect({"url": "https://feed.example.org/rss"}, None, client(web))
    assert caught.value.code == "bad_response"


@pytest.mark.xfail(strict=True, reason="minor: a page selector is only checked at collection time (bad_selector)")
def test_unsupported_page_selector_is_refused_on_reception() -> None:
    """EF-12 / §10: `check_params` exists for 'a CSS selector, a regular expression' (its own docstring)."""
    document = {"collector": "page", "params": {"url": "https://example.org/", "selector": "a:hover"}}
    with pytest.raises(VeilleurError) as caught:
        parse_spec(document, installed())
    assert caught.value.code == "invalid_params"


@pytest.mark.xfail(strict=True, reason="minor: a comma inside a quoted attribute value splits the selector group")
def test_quoted_attribute_value_with_a_comma() -> None:
    root = html.parse('<p data-x="a,b">kept</p><p>other</p>')
    assert [html.text_of(e) for e in html.select(root, 'p[data-x="a,b"]')] == ["kept"]


# --- EF-20: filters --------------------------------------------------------------------------------------------------


def test_keywords_accent_and_case_options_combine() -> None:
    item = FilterItem("k", {"title": "ELECTION du conseil"}, None)
    f = KeywordsFilter()
    assert f.apply(item, {"words": ["élection"], "accent_sensitive": False}) is not None
    assert f.apply(item, {"words": ["élection"]}) is None
    assert f.apply(item, {"words": ["ÉLECTION"], "case_sensitive": True, "accent_sensitive": False}) is not None
    assert f.apply(item, {"words": ["Élection"], "case_sensitive": True, "accent_sensitive": False}) is None


_APPLY = (
    "import sys\n"
    "from veilleur.adapters.filters import RegexFilter\n"
    "from veilleur.core.ports.plugins import FilterItem\n"
    "RegexFilter().apply(FilterItem('k', {'summary': sys.argv[2]}, None), {'pattern': sys.argv[1]})\n"
)
ORDINARY_TEXT = ("Lorem ipsum dolor sit amet, consectetur adipiscing elit, sed do eiusmod tempor. " * 30)[:2000]


@pytest.mark.parametrize("pattern", [r".*.*.*.*=", r"\w*\w*\w*\w*\w*!", r"\s*\s*\s*\s*x"])
def test_regex_patterns_that_backtrack_catastrophically_are_refused(pattern: str) -> None:
    """§10 (2026-11-18): the `regex` filter refuses patterns with catastrophic backtracking. A pattern it accepts
    must run in reasonable time on an ordinary 2000-character summary (the filter reads up to 20 000 per field);
    otherwise one receiving tool can stop the round (and the service's worker) for everyone."""
    if RegexFilter().check_params({"pattern": pattern}) is not None:
        return  # refused on reception: fine
    timed_out = False
    try:
        subprocess.run([sys.executable, "-c", _APPLY, pattern, ORDINARY_TEXT], timeout=10, check=True)
    except subprocess.TimeoutExpired:
        timed_out = True
    assert not timed_out, f"accepted pattern {pattern!r} ran more than 10 s on 2000 characters of ordinary text"


# --- EF-52: notifications --------------------------------------------------------------------------------------------


class Posts:
    def __init__(self) -> None:
        self.posts: list[tuple[str, bytes, dict[str, str]]] = []

    def __call__(self, url: str, body: bytes, headers: Mapping[str, str]) -> int:
        self.posts.append((url, body, dict(headers)))
        return 200


def test_notifications_go_per_pairing_and_carry_counts_only(world: World) -> None:
    core = world.app.core
    ntfy_posts, hook_posts = Posts(), Posts()
    key = b"hook-key"
    object.__setattr__(core, "notifiers", (
        NtfyNotifier("http://127.0.0.1:2586", "publish-token", "en", ntfy_posts),
        WebhookNotifier("https://hooks.example.org/v", key, poster=hook_posts),
    ))  # fmt: skip
    a = pairing.create_pairing(core, "desk a")
    b = pairing.create_pairing(core, "desk b")
    pairing.create_pairing(core, "desk c")  # no subscription: never notified
    document = {"collector": "fake", "params": {"topic": "confidential-topic"}, "frequency": "every_round"}
    subscriptions.put_subscription(core, a.key_id, UID1, 0, document)
    subscriptions.put_subscription(core, b.key_id, UID2, 0, document)
    pairing.revoke_pairing(core, b.key_id)
    world.collector.set("confidential-topic", ("item-key-1", {"title": "CONFIDENTIAL-TITLE"}))
    summary = round.run_round(core)
    assert summary.reports + summary.states >= 1
    assert [url for url, _, _ in ntfy_posts.posts] == [f"http://127.0.0.1:2586/{a.topic}"]
    assert len(hook_posts.posts) == 1
    for _url, body, headers in ntfy_posts.posts + hook_posts.posts:
        text = body.decode() + json.dumps(headers)
        for secret in ("CONFIDENTIAL", "confidential-topic", "item-key-1", UID1, a.key_id):
            assert secret not in text
    _url, body, headers = hook_posts.posts[0]
    assert headers["X-Veilleur-Signature"] == "sha256=" + hmac.new(key, body, hashlib.sha256).hexdigest()
    sent = json.loads(body)
    assert sent["topic"] == a.topic and sent["reports"] >= 1 and sent["failing_sources"] == 0
    # A round without any report sends nothing (EF-44, EF-52).
    world.clock.advance(hours=1)
    assert round.run_round(core).reports == 0
    assert len(ntfy_posts.posts) == 1 and len(hook_posts.posts) == 1


def test_notification_reports_sources_failing_for_more_than_two_days(world: World) -> None:
    """EF-05: beyond two days of failure, the notification says so."""
    core = world.app.core
    a = pairing.create_pairing(core, "desk a")
    subscriptions.put_subscription(
        core, a.key_id, UID1, 0, {"collector": "fake", "params": {"topic": "ok"}, "frequency": "every_round"}
    )
    team_spec = parse_spec({"collector": "fetch", "params": {"topic": "down"}, "frequency": "every_round"},
                           core.plugins)  # fmt: skip
    sync_team(core, [TeamSubscription("down_source", team_spec, (a.key_id,))])
    world.url_collector.fail = "http_503"
    world.collector.set("ok", ("1", {"title": "one"}))
    round.run_round(core)
    world.clock.advance(days=3)
    world.collector.set("ok", ("1", {"title": "one"}), ("2", {"title": "two"}))
    world.notifier.sent.clear()
    round.run_round(core)
    assert len(world.notifier.sent) == 1
    target, counts = world.notifier.sent[0]
    assert target.key_id == a.key_id and counts.failing_sources == 1 and counts.new_items == 1


# --- Protocol §9: GET /v1/subscriptions ------------------------------------------------------------------------------


def test_get_subscriptions_lists_the_live_subscriptions_of_this_pairing_only(world: World) -> None:
    core = world.app.core
    a = pairing.create_pairing(core, "desk a")
    b = pairing.create_pairing(core, "desk b")
    document = {"collector": "fake", "params": {"topic": "confidential-topic"}}
    subscriptions.put_subscription(core, a.key_id, UID3, 0, document)
    subscriptions.put_subscription(core, a.key_id, UID3, 1, {**document, "frequency": "weekly"})
    subscriptions.put_subscription(core, a.key_id, UID2, 0, document)
    subscriptions.delete_subscription(core, a.key_id, UID2)
    subscriptions.put_subscription(core, b.key_id, UID1, 0, document)
    sync_team(core, [TeamSubscription("team_feed", parse_spec(document, core.plugins), (a.key_id,))])
    call = Caller(world, a)
    status, headers, body = call("GET", "/v1/subscriptions")
    assert status == 200 and headers["Content-Type"] == "application/json"
    listed = json.loads(body)
    assert set(listed) == {"subscriptions"}
    entries = listed["subscriptions"]
    assert [e["uid"] for e in entries] == sorted(e["uid"] for e in entries)
    assert UID2 not in body.decode() and UID1 not in body.decode()
    assert b"confidential" not in body and b"params" not in body
    client_entry = next(e for e in entries if e["uid"] == UID3)
    assert client_entry == {"uid": UID3, "origin": "client", "version": 2}
    (team_entry,) = [e for e in entries if e["origin"] == "team"]
    assert set(team_entry) == {"uid", "origin", "name", "version"} and team_entry["name"] == "team_feed"
    assert len(entries) == 2


def test_get_subscriptions_errors(world: World) -> None:
    core = world.app.core
    a = pairing.create_pairing(core, "desk a")
    call = Caller(world, a)
    assert call("GET", "/v1/subscriptions?x=1")[0] == 400
    assert call("POST", "/v1/subscriptions")[0] in (404, 405)
    assert call("GET", "/v1/subscriptions", sign=False)[0] == 401
    late = world.clock.now() - timedelta(minutes=10)
    assert call("GET", "/v1/subscriptions", at=late)[0] == 401
    pairing.revoke_pairing(core, a.key_id)
    assert call("GET", "/v1/subscriptions")[0] == 403


def test_items_of_a_page_change_when_normalised_text_changes_only() -> None:
    """EF-02: a change of the normalised content is a changed item; markup alone is not."""
    a = html.text_of(html.parse("<body><p>Hello   <b>world</b></p><script>x=1</script></body>"))
    b = html.text_of(html.parse("<body><p>Hello <i>world</i></p><script>x=2</script></body>"))
    c = html.text_of(html.parse("<body><p>Hello there</p></body>"))
    assert a == b != c
