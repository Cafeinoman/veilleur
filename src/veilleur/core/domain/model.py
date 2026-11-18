# SPDX-License-Identifier: EUPL-1.2
"""Domain objects (cahier §4): pairings, subscriptions, collections, items, reports, jobs."""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any

LANGUAGES = ("en", "fr")
RETENTION_DAYS = 90
"""Packages, gone items and finished jobs are kept 90 days (cahier EF-45)."""


def canonical_json(value: Any) -> bytes:
    """Compact JSON with sorted member names, UTF-8: the form hashed for items and collection keys (EF-03, EF-04).

    Raises `ValueError` for a value that is not JSON (NaN, infinities, non-string keys, other types).
    """
    _check_json(value)
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")


def _check_json(value: Any) -> None:
    if value is None or isinstance(value, (bool, int, str)):
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("NaN and infinities are not JSON")
        return
    if isinstance(value, list):
        for element in value:
            _check_json(element)
        return
    if isinstance(value, dict):
        for key, element in value.items():
            if not isinstance(key, str):
                raise ValueError("object keys are strings")
            _check_json(element)
        return
    raise ValueError(f"{type(value).__name__} is not JSON")


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def item_hash(fields: Mapping[str, Any]) -> str:
    """SHA-256 of the canonical JSON of an item's fields (EF-03)."""
    return sha256_hex(canonical_json(dict(fields)))


def collection_id(collector: str, params: Mapping[str, Any]) -> str:
    """Key of a shared collection: same collector and canonical parameters, same collection (EF-04).

    The first 16 bytes of a hash: it names the collection in reports without revealing its parameters.
    """
    return sha256_hex(canonical_json({"collector": collector, "params": dict(params)}))[:32]


class Frequency(Enum):
    """How often a subscription gets a report (EF-13)."""

    EVERY_ROUND = "every_round"
    DAILY = "daily"
    WEEKLY = "weekly"


class Kind(Enum):
    """Kinds of packages (protocol §5)."""

    DELTA = "delta"
    STATE = "state"
    HISTORY = "history"


class Change(Enum):
    NEW = "new"
    CHANGED = "changed"
    GONE = "gone"


class Origin(Enum):
    """Who created a subscription: the administrator (team subscription, EF-10) or a receiving tool (EF-11)."""

    TEAM = "team"
    CLIENT = "client"


@dataclass(frozen=True)
class Pairing:
    key_id: str
    label: str
    secret: bytes = field(repr=False)
    created_at: datetime
    revoked_at: datetime | None = None
    topic: str = ""
    """Notification topic (EF-52): random, unguessable, given in the pairing code (drawn by `create_pairing`)."""

    @property
    def active(self) -> bool:
        return self.revoked_at is None


@dataclass(frozen=True)
class FilterSpec:
    name: str
    params: dict[str, Any]


@dataclass(frozen=True)
class SubscriptionSpec:
    """What a subscription asks for: a collector, its parameters, filters, frequency, language, renderings."""

    collector: str
    params: dict[str, Any]
    filters: tuple[FilterSpec, ...] = ()
    frequency: Frequency = Frequency.DAILY
    language: str = "en"
    renderings: tuple[str, ...] = ()

    @property
    def collection_id(self) -> str:
        return collection_id(self.collector, self.params)


@dataclass(frozen=True)
class Subscription:
    """A subscription of one pairing. Packages are sealed with keys derived from that pairing's secret, so a team
    subscription attached to several pairings exists once per pairing."""

    key_id: str
    uid: str
    spec: SubscriptionSpec
    version: int
    origin: Origin
    created_at: datetime
    updated_at: datetime
    team_name: str | None = None
    deleted: bool = False
    """A deleted subscription stays as a tombstone, so that its uid is never reused and its version keeps
    increasing: a replayed `DELETE` or creation then has no effect (threat model §4)."""


@dataclass(frozen=True)
class CollectedItem:
    """An item as a collector returns it (EF-01, EF-03). The core computes its key when missing, and its hash."""

    fields: dict[str, Any]
    key: str | None = None
    url: str | None = None


@dataclass(frozen=True)
class Collected:
    """Result of a collection. `complete` is False when the collector knows it did not see every item (paging
    stopped early, items skipped): no item is then considered gone (EF-31)."""

    items: tuple[CollectedItem, ...]
    complete: bool = True


@dataclass(frozen=True)
class StoredItem:
    """Current state of an item of a collection (EF-30)."""

    key: str
    hash: str
    fields: dict[str, Any]
    url: str | None
    fetched_at: datetime
    first_seen: datetime
    last_seen: datetime
    gone_at: datetime | None = None


@dataclass(frozen=True)
class ReportedItem:
    """What a subscription last reported about an item: the base of its next `delta`, and its `state`."""

    key: str
    hash: str
    fields: dict[str, Any]
    url: str | None
    fetched_at: datetime
    first_reported: datetime
    last_changed: datetime
    gone_at: datetime | None = None


@dataclass(frozen=True)
class ItemChange:
    """One line of `items.jsonl` (protocol §7.4)."""

    key: str
    change: Change
    hash: str
    fields: dict[str, Any]
    fetched_at: datetime
    url: str | None


@dataclass(frozen=True)
class SourceStatus:
    """State of a collection (EF-05): `error` is a stable code, never internal detail."""

    collection_id: str
    collector: str
    last_attempt: datetime | None
    last_success: datetime | None
    error: str | None
    failing_since: datetime | None = None

    @property
    def ok(self) -> bool:
        return self.error is None and self.last_success is not None


@dataclass(frozen=True)
class PackageInfo:
    seq: int
    kind: Kind
    size: int
    sha256: str
    created_at: datetime
    period_to: datetime


@dataclass(frozen=True)
class PackageBounds:
    """Numbers of a subscription's packages: `last` (0 if none yet), the oldest still kept, the last purged."""

    last: int
    oldest: int | None
    purged_through: int


class JobKind(Enum):
    FIRST_STATE = "first_state"
    HISTORY = "history"


class JobStatus(Enum):
    PENDING = "pending"
    DONE = "done"
    FAILED = "failed"


@dataclass(frozen=True)
class Job:
    """A long task run by the service's worker thread (cahier §7.5)."""

    id: int
    kind: JobKind
    key_id: str
    uid: str
    argument: str
    status: JobStatus
    created_at: datetime
    finished_at: datetime | None = None
    seq: int | None = None
    result: bytes | None = field(default=None, repr=False)


@dataclass(frozen=True)
class Event:
    """An entry of the administration log (`veilleur log`): a stable code and parameters, translated when shown.
    Never a secret, a subscription parameter or an address."""

    at: datetime
    code: str
    params: dict[str, Any]
