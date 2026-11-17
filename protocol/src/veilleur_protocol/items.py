# SPDX-License-Identifier: EUPL-1.2
"""`items.jsonl` (specification §7.4): the authoritative content of a package, one item per line, sorted by key."""

from __future__ import annotations

import itertools
import re
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any

from . import strict_json
from .encoding import format_time, parse_time
from .errors import BAD_ITEMS, ProtocolError

_HASH = re.compile(r"[0-9a-f]{64}")


class Change(Enum):
    NEW = "new"
    CHANGED = "changed"
    GONE = "gone"


@dataclass(frozen=True)
class Item:
    key: str
    change: Change
    hash: str
    """SHA-256 (lowercase hexadecimal) computed by the server; receivers compare it, never recompute it."""
    fields: dict[str, Any]
    fetched_at: datetime
    url: str | None = None


def _line(item: Item) -> bytes:
    if not item.key or not _HASH.fullmatch(item.hash):
        raise ValueError(f"invalid item {item.key!r}")
    document = {
        "key": item.key,
        "change": item.change.value,
        "hash": item.hash,
        "fields": item.fields,
        "fetched_at": format_time(item.fetched_at),
        "url": item.url,
    }
    return strict_json.dumps(document) + b"\n"


def encode_items(items: Iterable[Item]) -> bytes:
    """Content of `items.jsonl`; keys must be unique."""
    ordered = sorted(items, key=lambda item: item.key)
    for before, after in itertools.pairwise(ordered):
        if before.key == after.key:
            raise ValueError(f"duplicate item key {before.key!r}")
    return b"".join(_line(item) for item in ordered)


def _item(line: bytes, number: int) -> Item:
    try:
        document = strict_json.loads(line)
    except strict_json.InvalidJson as exc:
        raise ProtocolError(BAD_ITEMS, f"line {number}: not UTF-8 JSON") from exc
    if not isinstance(document, dict):
        raise ProtocolError(BAD_ITEMS, f"line {number}: not an object")
    key, change, digest = document.get("key"), document.get("change"), document.get("hash")
    fields, url = document.get("fields"), document.get("url", ...)
    if not isinstance(key, str) or not key:
        raise ProtocolError(BAD_ITEMS, f"line {number}: key")
    if not isinstance(change, str) or change not in {c.value for c in Change}:
        raise ProtocolError(BAD_ITEMS, f"line {number}: change")
    if not isinstance(digest, str) or not _HASH.fullmatch(digest):
        raise ProtocolError(BAD_ITEMS, f"line {number}: hash")
    if not isinstance(fields, dict):
        raise ProtocolError(BAD_ITEMS, f"line {number}: fields")
    if url is not None and not isinstance(url, str):
        raise ProtocolError(BAD_ITEMS, f"line {number}: url")
    try:
        fetched_at = parse_time(document.get("fetched_at"))
    except ProtocolError as exc:
        raise ProtocolError(BAD_ITEMS, f"line {number}: fetched_at") from exc
    return Item(key, Change(change), digest, fields, fetched_at, url)


def parse_items(data: bytes) -> list[Item]:
    """Parse and check `items.jsonl`: every line ends with LF, keys strictly increasing."""
    if not data:
        return []
    if not data.endswith(b"\n"):
        raise ProtocolError(BAD_ITEMS, "the last line does not end with LF")
    items = [_item(line, number) for number, line in enumerate(data[:-1].split(b"\n"), start=1)]
    for number, (before, after) in enumerate(itertools.pairwise(items), start=2):
        if not before.key < after.key:
            raise ProtocolError(BAD_ITEMS, f"line {number}: keys not sorted or not unique")
    return items
