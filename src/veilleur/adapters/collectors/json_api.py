# SPDX-License-Identifier: EUPL-1.2
"""Collector `json_api`: items of a JSON API (cahier EF-02).

Parameters: the address, the path of the item list in the response (`data.items`; empty for the response itself),
the field that serves as key, an optional field holding the item's address, the fields to keep, and simple paging
(the path of the next page's address in the response, and a page limit). Paths are names and list positions
separated by dots. A collection stopped by the page limit is partial: no item is then considered gone (EF-31).
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import datetime
from typing import Any
from urllib.parse import urljoin

from veilleur.core.domain import errors
from veilleur.core.domain.errors import CollectorError
from veilleur.core.domain.model import Collected, CollectedItem
from veilleur.core.ports.http import HttpClient

from .common import URL_SCHEMA

JSON_TYPES = ("application/json", "text/json", "*+json")
MAX_PAGES = 20
_PATH = {"type": "string", "maxLength": 200, "pattern": r"^([A-Za-z0-9_$@:-]+(\.[A-Za-z0-9_$@:-]+)*)?$"}


class _Missing(Exception):
    pass


def walk(document: Any, path: str) -> Any:
    """The value at `path` (names and list positions separated by dots; empty for the document itself)."""
    value = document
    for segment in path.split(".") if path else ():
        if isinstance(value, dict) and segment in value:
            value = value[segment]
        elif isinstance(value, list) and segment.isdigit() and int(segment) < len(value):
            value = value[int(segment)]
        else:
            raise _Missing(segment)
    return value


def _reject_constant(name: str) -> Any:
    raise ValueError(name)


def load(data: bytes) -> Any:
    try:
        return json.loads(data, parse_constant=_reject_constant)
    except (ValueError, RecursionError) as exc:  # UnicodeDecodeError is a ValueError
        raise CollectorError(errors.BAD_RESPONSE) from exc


def _item(entry: dict[str, Any], params: Mapping[str, Any]) -> CollectedItem:
    key: str | None = None
    if params.get("key_field"):
        try:
            raw = walk(entry, params["key_field"])
        except _Missing:
            raw = None
        if isinstance(raw, str) or (isinstance(raw, int) and not isinstance(raw, bool)):
            key = str(raw)
    url: str | None = None
    if params.get("url_field"):
        try:
            raw = walk(entry, params["url_field"])
        except _Missing:
            raw = None
        if isinstance(raw, str) and raw.startswith(("http://", "https://")):
            url = raw
    fields = entry
    if params.get("fields"):
        fields = {name: entry[name] for name in params["fields"] if name in entry}
    return CollectedItem(fields, key=key, url=url)


class JsonApiCollector:
    name = "json_api"
    follows_client_urls = True
    schema: Mapping[str, Any] = {
        "type": "object",
        "title": "JSON API",
        "properties": {
            "url": URL_SCHEMA,
            "items_path": {**_PATH, "default": ""},
            "key_field": _PATH,
            "url_field": _PATH,
            "fields": {
                "type": "array",
                "items": {"type": "string", "minLength": 1, "maxLength": 100},
                "minItems": 1,
                "maxItems": 100,
                "uniqueItems": True,
            },
            "next_path": _PATH,
            "max_pages": {"type": "integer", "minimum": 1, "maximum": MAX_PAGES, "default": 1},
        },
        "required": ["url"],
        "additionalProperties": False,
    }

    def collect(self, params: Mapping[str, Any], since: datetime | None, http: HttpClient) -> Collected:
        url: str | None = params["url"]
        seen: set[str] = set()
        items: list[CollectedItem] = []
        complete = True
        pages = 0
        while url is not None:
            if pages == int(params.get("max_pages", 1)):
                complete = False
                break
            seen.add(url)
            response = http.get(url, accept=JSON_TYPES)
            pages += 1
            document = load(response.body)
            try:
                entries = walk(document, params.get("items_path", ""))
            except _Missing as exc:
                raise CollectorError(errors.BAD_RESPONSE) from exc
            if not isinstance(entries, list):
                raise CollectorError(errors.BAD_RESPONSE)
            for entry in entries:
                if isinstance(entry, dict):
                    items.append(_item(entry, params))
                else:
                    complete = False  # an entry that is not an object is skipped
            url = self._next(document, response.url, params, seen)
        return Collected(tuple(items), complete=complete)

    @staticmethod
    def _next(document: Any, current: str, params: Mapping[str, Any], seen: set[str]) -> str | None:
        if not params.get("next_path"):
            return None
        try:
            following = walk(document, params["next_path"])
        except _Missing:
            return None
        if not isinstance(following, str) or not following:
            return None
        url = urljoin(current, following)
        return None if url in seen else url
