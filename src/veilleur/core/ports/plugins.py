# SPDX-License-Identifier: EUPL-1.2
"""Plugin interfaces (cahier EF-01, EF-20, EF-43, EF-52), found through entry points by the applications:
`veilleur.collectors`, `veilleur.filters`, `veilleur.renderers`, `veilleur.notifiers`."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol, runtime_checkable

from veilleur.core.domain.model import Collected, CollectedItem, ItemChange, Kind, SourceStatus

from .http import HttpClient


class Collector(Protocol):
    """Returns the items of a source for validated parameters (EF-01)."""

    @property
    def name(self) -> str: ...

    @property
    def schema(self) -> Mapping[str, Any]:
        """JSON schema of the parameters (subset of `veilleur.core.domain.schema`)."""
        ...

    @property
    def follows_client_urls(self) -> bool:
        """True when the parameters name an address to fetch (`rss`, `page`, `json_api`): refused to receiving
        tools unless the administrator allows it for their pairing (EF-11)."""
        ...

    def collect(
        self, params: Mapping[str, Any], since: datetime | None, http: HttpClient
    ) -> Collected | Iterable[CollectedItem]:
        """Items of the source. `since` is the date of the last successful collection. Network access goes through
        `http` only (EF-06). Raise `CollectorError` with a stable code for a failure the collector can name."""
        ...


@runtime_checkable
class ParamsCheck(Protocol):
    """Optional for a collector or a filter: a check of its parameters that a schema cannot express (a CSS selector,
    a regular expression). Run after the schema, when a subscription is received (EF-12)."""

    def check_params(self, params: Mapping[str, Any]) -> str | None:
        """None if the parameters are acceptable, otherwise the JSON pointer of the faulty one (`/pattern`)."""
        ...


@dataclass(frozen=True)
class FilterItem:
    """What a filter sees of an item; it never modifies stored items (EF-21)."""

    key: str
    fields: dict[str, Any]
    url: str | None


class Filter(Protocol):
    """Keeps, drops or transforms the items of a report (EF-20)."""

    @property
    def name(self) -> str: ...

    @property
    def schema(self) -> Mapping[str, Any]: ...

    def apply(self, item: FilterItem, params: Mapping[str, Any]) -> FilterItem | None:
        """The item to report (possibly transformed), or None to leave it out."""
        ...


@runtime_checkable
class SetFilter(Protocol):
    """Optional for a filter that needs every item at once (deduplication): `select` is then used, not `apply`."""

    def select(self, items: Sequence[FilterItem], params: Mapping[str, Any]) -> Sequence[FilterItem]:
        """The items to report, among `items` (sorted by key), possibly transformed."""
        ...


@dataclass(frozen=True)
class ReportView:
    """What a renderer reads: the content of `items.jsonl` and of the manifest."""

    uid: str
    seq: int
    kind: Kind
    created_at: datetime
    period_from: datetime | None
    period_to: datetime
    items: Sequence[ItemChange]
    sources: Sequence[SourceStatus]


class Renderer(Protocol):
    """Readable rendering of a report, in the subscription's language (EF-43)."""

    @property
    def name(self) -> str: ...

    def render(self, report: ReportView, language: str) -> Mapping[str, bytes]:
        """Files to add to the package, named `report.<extension>`."""
        ...


@dataclass(frozen=True)
class RoundCounts:
    """All a notification may carry (EF-52): counts, never content."""

    reports: int
    new_items: int
    failing_sources: int


@dataclass(frozen=True)
class NotificationTarget:
    """Who a notification is for: a pairing, through its random topic (the one in its pairing code)."""

    key_id: str
    topic: str


class Notifier(Protocol):
    """Tells a pairing that a round produced reports for it (EF-52)."""

    @property
    def name(self) -> str: ...

    def notify(self, target: NotificationTarget, counts: RoundCounts) -> None:
        """Send `counts` for `target`. Raise on failure; the round goes on."""
        ...


@dataclass(frozen=True)
class Plugins:
    """Installed plugins, by name."""

    collectors: Mapping[str, Collector]
    filters: Mapping[str, Filter]
    renderers: Mapping[str, Renderer]
