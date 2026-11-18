# SPDX-License-Identifier: EUPL-1.2
"""Collectors `rss`, `json_api` and `page` (cahier EF-02) on recorded responses, through the networked client."""

from __future__ import annotations

from typing import Any

import pytest

from veilleur.adapters.collectors import html
from veilleur.adapters.collectors.json_api import JsonApiCollector
from veilleur.adapters.collectors.page import PageCollector
from veilleur.adapters.collectors.rss import RssCollector, parse_feed
from veilleur.adapters.plugins import installed, validated
from veilleur.core.domain.errors import CollectorError
from veilleur.core.domain.model import Collected
from veilleur.core.domain.schema import validate
from veilleur.core.ports.plugins import Plugins

from .http_fakes import FakeWeb, client


def _collect(collector: Any, web: FakeWeb, params: dict[str, Any]) -> Collected:
    assert validate(params, collector.schema) is None
    result = collector.collect(params, None, client(web))
    assert isinstance(result, Collected)
    return result


def _fails(collector: Any, web: FakeWeb, params: dict[str, Any]) -> str:
    with pytest.raises(CollectorError) as caught:
        collector.collect(params, None, client(web))
    return caught.value.code


def test_provided_plugins_are_installed_with_valid_schemas() -> None:
    plugins = installed()
    assert {"rss", "json_api", "page"} <= set(plugins.collectors)
    assert {"keywords", "regex", "dedup"} <= set(plugins.filters)
    validated(Plugins(plugins.collectors, plugins.filters, {}))
    assert all(plugins.collectors[n].follows_client_urls for n in ("rss", "json_api", "page"))


# --- rss -------------------------------------------------------------------------------------------------------


def test_rss2_feed() -> None:
    web = FakeWeb()
    web.recorded("news.example.org", "/feed.xml", "feed-rss2.xml", "application/rss+xml; charset=utf-8")
    result = _collect(RssCollector(), web, {"url": "https://news.example.org/feed.xml"})
    assert result.complete is False  # a feed is a window: leaving it is not disappearing
    first, second, third = result.items
    assert first.key == "news-2026-0042"
    assert first.url == "https://news.example.org/2026/budget"
    assert first.fields == {
        "title": "Council adopts the budget",
        "link": "https://news.example.org/2026/budget",
        "summary": "<p>The council adopted the budget.</p>",
        "published": "2026-11-17T07:30:00Z",
        "author": "Editorial desk",
        "categories": ["Budget", "Council"],
    }
    assert second.key is None and second.url == "https://news.example.org/2026/bridge"
    assert second.fields["published"] == "not a date"
    assert third.key is None and third.url is None


def test_atom_feed() -> None:
    web = FakeWeb()
    web.recorded("releases.example.net", "/atom", "feed-atom.xml", "application/atom+xml")
    items = _collect(RssCollector(), web, {"url": "https://releases.example.net/atom", "max_items": 1}).items
    assert len(items) == 1
    assert items[0].key == "tag:releases.example.net,2026:2.0"
    assert items[0].url == "https://releases.example.net/2.0"
    assert items[0].fields == {
        "title": "Version 2.0 & more",
        "link": "https://releases.example.net/2.0",
        "summary": "Second major version.",
        "published": "2026-11-16T07:00:00Z",
        "updated": "2026-11-17T10:00:00Z",
        "author": "Release team",
        "categories": ["release"],
    }


@pytest.mark.parametrize(
    "document",
    [
        b'<?xml version="1.0"?><!DOCTYPE lolz [<!ENTITY lol "lol"><!ENTITY lol2 "&lol;&lol;">]>'
        b"<rss><channel><item><title>&lol2;</title></item></channel></rss>",
        b'<?xml version="1.0"?><!DOCTYPE r [<!ENTITY x SYSTEM "file:///etc/passwd">]>'
        b"<rss><channel><item><title>&x;</title></item></channel></rss>",
        b"<rss><channel><item><title>unclosed</channel></rss>",
        b"<html><body>not a feed</body></html>",
        b"<rss><nochannel/></rss>",
        b"",
    ],
)
def test_hostile_or_malformed_feeds_are_refused(document: bytes) -> None:
    with pytest.raises(CollectorError) as caught:
        parse_feed(document)
    assert caught.value.code == "bad_response"


def test_rss_refuses_an_unexpected_content_type() -> None:
    web = FakeWeb()
    web.page("news.example.org", "/feed", "<html/>", "text/html")
    assert _fails(RssCollector(), web, {"url": "https://news.example.org/feed"}) == "unexpected_content_type"


# --- json_api --------------------------------------------------------------------------------------------------


def _api_web() -> FakeWeb:
    web = FakeWeb()
    web.recorded("api.example.org", "/api/v1/notices", "api-page1.json", "application/json")
    web.recorded("api.example.org", "/api/v1/notices?page=2", "api-page2.json", "application/vnd.api+json")
    return web


API = {"url": "https://api.example.org/api/v1/notices", "items_path": "data.items", "key_field": "id"}


def test_json_api_with_paging() -> None:
    params = {**API, "url_field": "href", "fields": ["title", "body"], "next_path": "meta.next", "max_pages": 5}
    result = _collect(JsonApiCollector(), _api_web(), params)
    assert [i.key for i in result.items] == ["101", "102", "103", None]
    assert result.items[0].fields == {"title": "Notice one", "body": "First"}
    assert result.items[0].url == "https://api.example.org/notices/101"
    assert result.items[2].url is None  # not an http(s) address
    assert result.complete is False  # an entry that is not an object was skipped


def test_json_api_page_limit_makes_a_partial_collection() -> None:
    web = _api_web()
    result = _collect(JsonApiCollector(), web, {**API, "next_path": "meta.next"})
    assert [i.key for i in result.items] == ["101", "102"]
    assert result.complete is False
    assert web.requests_to("/api/v1/notices?page=2") == []


def test_json_api_complete_collection() -> None:
    web = FakeWeb()
    web.page("api.example.org", "/list", '[{"id": "a", "n": 1}, {"id": "b", "n": 2}]', "application/json")
    result = _collect(JsonApiCollector(), web, {"url": "https://api.example.org/list", "key_field": "id"})
    assert result.complete is True and [i.fields for i in result.items] == [{"id": "a", "n": 1}, {"id": "b", "n": 2}]


@pytest.mark.parametrize(
    ("body", "params"),
    [
        ("not json", {}),
        ('{"a": NaN}', {}),
        ('{"items": {}}', {"items_path": "items"}),
        ('{"other": []}', {"items_path": "items"}),
        ("[" * 100_000 + "]" * 100_000, {}),
    ],
)
def test_json_api_bad_responses(body: str, params: dict[str, Any]) -> None:
    web = FakeWeb()
    web.page("api.example.org", "/x", body, "application/json")
    assert _fails(JsonApiCollector(), web, {"url": "https://api.example.org/x", **params}) == "bad_response"


def test_json_api_paging_loop_stops() -> None:
    web = FakeWeb()
    web.page("api.example.org", "/loop", '{"next": "/loop", "items": [{"id": 1}]}', "application/json")
    params = {"url": "https://api.example.org/loop", "items_path": "items", "next_path": "next", "max_pages": 5}
    result = _collect(JsonApiCollector(), web, params)
    assert len(web.requests_to("/loop")) == 1 and result.complete is True


# --- page ------------------------------------------------------------------------------------------------------


def _page_web() -> FakeWeb:
    web = FakeWeb()
    web.recorded("www.example.org", "/hours", "page.html", "text/html")
    return web


def test_page_whole_body() -> None:
    result = _collect(PageCollector(), _page_web(), {"url": "https://www.example.org/hours"})
    (item,) = result.items
    assert item.key == item.url == "https://www.example.org/hours"
    assert item.fields["title"] == "Opening hours"
    content = item.fields["content"]
    assert "Monday to Friday: 9:00 to 17:00.\nClosed on public holidays." in content
    assert "Café desk." in content  # charset from the <meta>
    assert "tracking" not in content and "ignored" not in content and "color" not in content
    assert "Desk B\nupstairs" in content


@pytest.mark.parametrize(
    ("selector", "expected"),
    [
        ("div.notice.important", "Monday to Friday: 9:00 to 17:00.\nClosed on public holidays."),
        (
            "#content > .notice p",
            "Monday to Friday: 9:00 to 17:00.\nClosed on public holidays.\nLast updated: 17 November. Café desk.",
        ),
        ('[data-kind="hours"] p:nth-child', None),
        ("[data-kind=hours] p", "Monday to Friday: 9:00 to 17:00.\nClosed on public holidays."),
        ("ul.list li, footer", "Desk A\nDesk B\nupstairs\nVisitor counter: 123456"),
        ("main > p", "selector_no_match"),
        ("nav a[href^='/c']", "Contact"),
    ],
)
def test_page_selectors(selector: str, expected: str | None) -> None:
    web = _page_web()
    params = {"url": "https://www.example.org/hours", "selector": selector}
    if expected is None:
        assert _fails(PageCollector(), web, params) == "bad_selector"
        assert web.sent == []  # refused before any request
    elif expected == "selector_no_match":
        assert _fails(PageCollector(), web, params) == "selector_no_match"
    else:
        assert _collect(PageCollector(), web, params).items[0].fields["content"] == expected


def test_page_change_is_a_changed_content() -> None:
    web = FakeWeb()
    web.page("www.example.org", "/p", "<p>Price:   10</p>", "text/html")
    first = _collect(PageCollector(), web, {"url": "https://www.example.org/p"}).items[0]
    web.page("www.example.org", "/p", "<p>Price: 10</p><script>x=1</script>", "text/html")
    assert _collect(PageCollector(), web, {"url": "https://www.example.org/p"}).items[0].fields == first.fields


@pytest.mark.parametrize("selector", ["", "a >", "> a", "a:hover", "a::before", "a + b", "a ~ b", "[x", "a,"])
def test_unsupported_selectors(selector: str) -> None:
    with pytest.raises(ValueError):
        html.compile_selector(selector)


def test_deep_pages_and_long_selectors_stay_fast() -> None:
    root = html.parse("<div>" * 2000 + "x" + "</div>" * 2000)
    assert len(html.select(root, " ".join(["div"] * 100) + " span")) == 0
    assert len(html.select(root, "div div")) > 0
