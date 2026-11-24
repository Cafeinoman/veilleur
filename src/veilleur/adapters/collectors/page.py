# SPDX-License-Identifier: EUPL-1.2
"""Collector `page`: the content of a web page, or of the parts a CSS selector designates (spec EF-02).

The page is one item, keyed by its address, whose field `content` is the visible text, normalised (white space
collapsed, scripts and styles left out): a change of that text is a changed item.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from datetime import datetime
from typing import Any

from veilleur.core.domain import errors
from veilleur.core.domain.errors import CollectorError
from veilleur.core.domain.model import Collected, CollectedItem
from veilleur.core.ports.http import HttpClient

from . import html
from .common import URL_SCHEMA

PAGE_TYPES = ("text/html", "application/xhtml+xml")
_CHARSET = re.compile(rb"""charset\s*=\s*["']?([A-Za-z0-9_.:-]{1,40})""", re.IGNORECASE)


def decode(body: bytes, content_type: str) -> str:
    """Text of a page: the charset of the `Content-Type`, otherwise of a `<meta>` near the start, otherwise UTF-8."""
    candidates = []
    header = _CHARSET.search(content_type.encode("latin-1", "replace"))
    if header:
        candidates.append(header.group(1).decode("ascii"))
    meta = _CHARSET.search(body[:4096])
    if meta:
        candidates.append(meta.group(1).decode("ascii"))
    for charset in candidates:
        try:
            return body.decode(charset)
        except (LookupError, UnicodeDecodeError):
            continue
    return body.decode("utf-8", "replace")


class PageCollector:
    name = "page"
    follows_client_urls = True
    schema: Mapping[str, Any] = {
        "type": "object",
        "title": "Web page",
        "properties": {
            "url": URL_SCHEMA,
            "selector": {
                "type": "string",
                "description": "CSS selector: type, #id, .class, [attribute], descendant and child combinators",
                "minLength": 1,
                "maxLength": 500,
            },
        },
        "required": ["url"],
        "additionalProperties": False,
    }

    def collect(self, params: Mapping[str, Any], since: datetime | None, http: HttpClient) -> Collected:
        selector = params.get("selector")
        if selector is not None:
            try:
                html.compile_selector(selector)
            except ValueError as exc:
                raise CollectorError(errors.BAD_SELECTOR) from exc
        response = http.get(params["url"], accept=PAGE_TYPES)
        root = html.parse(decode(response.body, response.headers.get("content-type", "")))
        if selector is None:
            body = next((e for e in root.elements() if e.tag == "body"), root)
            content = html.text_of(body)
        else:
            parts = html.select(root, selector)
            if not parts:
                raise CollectorError(errors.SELECTOR_NO_MATCH)
            content = "\n".join(text for text in (html.text_of(p) for p in parts) if text)
        fields = {"content": content}
        title = html.title_of(root)
        if title:
            fields["title"] = title
        return Collected((CollectedItem(fields, key=params["url"], url=params["url"]),))
