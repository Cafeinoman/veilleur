# SPDX-License-Identifier: EUPL-1.2
"""Collector `rss`: RSS 2.0 and Atom feeds (cahier EF-02).

A feed shows its latest entries only: an entry that leaves it has not disappeared from the source. The collection
is therefore never complete (EF-31): no item becomes `gone` because it left the feed.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from collections.abc import Mapping
from datetime import datetime
from typing import Any

from veilleur.core.domain import errors
from veilleur.core.domain.errors import CollectorError
from veilleur.core.domain.model import Collected, CollectedItem
from veilleur.core.ports.http import HttpClient

from . import xml
from .common import URL_SCHEMA, clean, iso_date

ATOM = "{http://www.w3.org/2005/Atom}"
DC = "{http://purl.org/dc/elements/1.1/}"
FEED_TYPES = (
    "application/rss+xml",
    "application/atom+xml",
    "application/rdf+xml",
    "application/xml",
    "text/xml",
    "application/x-rss+xml",
)
MAX_ITEMS = 1000


def _text(element: ET.Element | None) -> str:
    return clean("".join(element.itertext())) if element is not None else ""


def _http(url: str) -> str | None:
    return url if url.startswith(("http://", "https://")) else None


def _fields(**values: Any) -> dict[str, Any]:
    return {k: v for k, v in values.items() if v not in (None, "", [])}


def _rss_item(item: ET.Element) -> CollectedItem:
    link = _text(item.find("link"))
    guid = _text(item.find("guid"))
    fields = _fields(
        title=_text(item.find("title")),
        link=link,
        summary=_text(item.find("description")),
        published=iso_date(_text(item.find("pubDate"))),
        author=_text(item.find("author")) or _text(item.find(f"{DC}creator")),
        categories=[_text(c) for c in item.findall("category") if _text(c)],
    )
    return CollectedItem(fields, key=guid or None, url=_http(link))


def _atom_link(entry: ET.Element) -> str:
    links = entry.findall(f"{ATOM}link")
    for link in links:
        if link.get("rel", "alternate") == "alternate" and link.get("href"):
            return clean(link.get("href"))
    return clean(links[0].get("href")) if links else ""


def _atom_entry(entry: ET.Element) -> CollectedItem:
    link = _atom_link(entry)
    author = entry.find(f"{ATOM}author")
    fields = _fields(
        title=_text(entry.find(f"{ATOM}title")),
        link=link,
        summary=_text(entry.find(f"{ATOM}summary")) or _text(entry.find(f"{ATOM}content")),
        published=iso_date(_text(entry.find(f"{ATOM}published"))),
        updated=iso_date(_text(entry.find(f"{ATOM}updated"))),
        author=_text(author.find(f"{ATOM}name")) if author is not None else "",
        categories=[clean(c.get("term")) for c in entry.findall(f"{ATOM}category") if clean(c.get("term"))],
    )
    return CollectedItem(fields, key=_text(entry.find(f"{ATOM}id")) or None, url=_http(link))


def parse_feed(data: bytes, limit: int = MAX_ITEMS) -> list[CollectedItem]:
    """The entries of an RSS 2.0 or Atom document. Raise `CollectorError(bad_response)` for anything else."""
    try:
        root = xml.parse(data)
    except xml.XmlRefused as exc:
        raise CollectorError(errors.BAD_RESPONSE) from exc
    if root.tag == "rss":
        channel = root.find("channel")
        if channel is None:
            raise CollectorError(errors.BAD_RESPONSE)
        return [_rss_item(item) for item in channel.findall("item")[:limit]]
    if root.tag == f"{ATOM}feed":
        return [_atom_entry(entry) for entry in root.findall(f"{ATOM}entry")[:limit]]
    raise CollectorError(errors.BAD_RESPONSE)


class RssCollector:
    name = "rss"
    follows_client_urls = True
    schema: Mapping[str, Any] = {
        "type": "object",
        "title": "RSS 2.0 or Atom feed",
        "properties": {
            "url": URL_SCHEMA,
            "max_items": {"type": "integer", "minimum": 1, "maximum": MAX_ITEMS, "default": 200},
        },
        "required": ["url"],
        "additionalProperties": False,
    }

    def collect(self, params: Mapping[str, Any], since: datetime | None, http: HttpClient) -> Collected:
        response = http.get(params["url"], accept=FEED_TYPES)
        items = parse_feed(response.body, int(params.get("max_items", 200)))
        return Collected(tuple(items), complete=False)
