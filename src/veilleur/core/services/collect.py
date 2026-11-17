# SPDX-License-Identifier: EUPL-1.2
"""Shared collections and change detection at the source (cahier EF-03 to EF-05, EF-30, EF-31)."""

from __future__ import annotations

import logging
import re
from collections.abc import Iterable
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Any

from veilleur.core.domain import errors
from veilleur.core.domain.errors import CollectorError
from veilleur.core.domain.model import (
    Collected,
    CollectedItem,
    SourceStatus,
    StoredItem,
    SubscriptionSpec,
    item_hash,
)
from veilleur.core.domain.schema import validate

from .context import Core

log = logging.getLogger(__name__)
_CODE = re.compile(r"[a-z][a-z0-9_]{0,63}")
MAX_KEY = 1024


@dataclass(frozen=True)
class CollectionResult:
    status: SourceStatus
    new: int = 0
    changed: int = 0
    gone: int = 0


def _key(item: CollectedItem, digest: str) -> str:
    """The collector's key, otherwise the item's address, otherwise the hash of its content (EF-03)."""
    for candidate in (item.key, item.url):
        if isinstance(candidate, str) and candidate:
            return candidate
    return digest


def _normalise(raw: Iterable[Any], now: datetime) -> tuple[dict[str, tuple[str, CollectedItem]], bool]:
    """Items by key, and whether every item was valid. A duplicate key keeps the first item."""
    items: dict[str, tuple[str, CollectedItem]] = {}
    valid = True
    for item in raw:
        try:
            if not isinstance(item, CollectedItem) or not isinstance(item.fields, dict):
                raise ValueError("not an item")
            if item.url is not None and not isinstance(item.url, str):
                raise ValueError("url")
            digest = item_hash(item.fields)
            key = _key(item, digest)
            # A lone surrogate (valid JSON, decoded by json.loads) cannot be stored: the item is invalid, the
            # round goes on (EF-05). UnicodeEncodeError is a ValueError.
            key.encode("utf-8")
            if item.url is not None:
                item.url.encode("utf-8")
        except ValueError:
            valid = False
            continue
        if len(key) > MAX_KEY:
            valid = False
            continue
        items.setdefault(key, (digest, item))
    return items, valid


def collect(core: Core, spec: SubscriptionSpec) -> CollectionResult:
    """Run the collection of `spec` (shared by every subscription with the same collector and parameters) and
    store what changed. A failing source never raises: its status records a stable error code (EF-05)."""
    collection_id = spec.collection_id
    now = core.clock.now()
    previous = core.store.get_source(collection_id)
    since = previous.last_success if previous else None
    collector = core.plugins.collectors.get(spec.collector)
    error: str | None = None
    collected: Collected | None = None
    if collector is None:
        error = errors.COLLECTOR_MISSING
    elif validate(spec.params, collector.schema) is not None:
        error = errors.INVALID_PARAMS
    else:
        try:
            result = collector.collect(spec.params, since, core.http)
            collected = result if isinstance(result, Collected) else Collected(tuple(result))
        except CollectorError as exc:
            error = exc.code if _CODE.fullmatch(exc.code) else errors.COLLECTOR_FAILED
        except Exception as exc:  # a plugin may raise anything; the round goes on (EF-05)
            log.warning("collection %s failed: %s", collection_id, type(exc).__name__)
            error = errors.COLLECTOR_FAILED
    if collected is None:
        status = SourceStatus(
            collection_id,
            spec.collector,
            now,
            previous.last_success if previous else None,
            error,
            (previous.failing_since if previous and previous.failing_since else now),
        )
        core.store.save_source(status)
        return CollectionResult(status)
    items, valid = _normalise(collected.items, now)
    complete = collected.complete and valid
    with core.store.transaction():
        current = core.store.current_items(collection_id)
        changes: list[StoredItem] = []
        new = changed = gone = 0
        for key, (digest, item) in items.items():
            old = current.get(key)
            if old is None:
                new += 1
                changes.append(StoredItem(key, digest, item.fields, item.url, now, now, now))
            elif old.hash != digest or old.url != item.url:
                changed += old.hash != digest
                changes.append(
                    replace(old, hash=digest, fields=item.fields, url=item.url, fetched_at=now, last_seen=now)
                )
            else:
                changes.append(replace(old, last_seen=now))
        if complete:
            for key, old in current.items():
                if key not in items:
                    gone += 1
                    changes.append(replace(old, gone_at=now))
        core.store.save_items(collection_id, changes)
        status = SourceStatus(collection_id, spec.collector, now, now, None if valid else errors.BAD_ITEM, None)
        core.store.save_source(status)
    return CollectionResult(status, new, changed, gone)
