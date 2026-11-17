# SPDX-License-Identifier: EUPL-1.2
"""Fakes for the server's tests: a clock, a collector, a filter and a renderer; no network anywhere."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from veilleur.apps.server.config import Config
from veilleur.apps.server.context import App, open_app
from veilleur.core.domain.errors import CollectorError
from veilleur.core.domain.model import Collected, CollectedItem
from veilleur.core.ports.http import HttpClient
from veilleur.core.ports.plugins import FilterItem, Plugins, ReportView, RoundCounts

START = datetime(2026, 11, 17, 6, 0, 0, tzinfo=UTC)


class FakeClock:
    def __init__(self, now: datetime = START) -> None:
        self.current = now

    def now(self) -> datetime:
        return self.current

    def advance(self, **delta: float) -> None:
        self.current += timedelta(**delta)


@dataclass
class FakeCollector:
    """Returns `items[topic]` for parameters `{"topic": ...}`; counts its calls."""

    name: str = "fake"
    follows_client_urls: bool = False
    items: dict[str, list[CollectedItem]] = field(default_factory=dict)
    fail: str | None = None
    complete: bool = True
    calls: list[tuple[dict[str, Any], datetime | None]] = field(default_factory=list)
    schema: dict[str, Any] = field(
        default_factory=lambda: {
            "type": "object",
            "properties": {"topic": {"type": "string", "minLength": 1, "maxLength": 50}},
            "required": ["topic"],
            "additionalProperties": False,
        }
    )

    def collect(
        self, params: Mapping[str, Any], since: datetime | None, http: HttpClient
    ) -> Collected | Iterable[CollectedItem]:
        self.calls.append((dict(params), since))
        if self.fail == "crash":
            raise RuntimeError("internal detail that must not leak")
        if self.fail:
            raise CollectorError(self.fail)
        return Collected(tuple(self.items.get(params["topic"], [])), complete=self.complete)

    def set(self, topic: str, *items: tuple[str, dict[str, Any]]) -> None:
        self.items[topic] = [CollectedItem(fields, key=key, url=f"https://example.org/{key}") for key, fields in items]


@dataclass
class KeywordFilter:
    name: str = "keyword"
    schema: dict[str, Any] = field(
        default_factory=lambda: {
            "type": "object",
            "properties": {"word": {"type": "string"}},
            "required": ["word"],
        }
    )

    def apply(self, item: FilterItem, params: Mapping[str, Any]) -> FilterItem | None:
        return item if params["word"] in str(item.fields.get("title", "")) else None


@dataclass
class TextRenderer:
    name: str = "text"

    def render(self, report: ReportView, language: str) -> Mapping[str, bytes]:
        lines = [f"{language} {report.kind.value} {report.seq}"] + [f"{i.change.value} {i.key}" for i in report.items]
        return {"report.txt": "\n".join(lines).encode()}


@dataclass
class RecordingNotifier:
    name: str = "recording"
    sent: list[RoundCounts] = field(default_factory=list)

    def notify(self, counts: RoundCounts) -> None:
        self.sent.append(counts)


@dataclass
class World:
    """An application on a temporary state directory, with fake plugins and clock."""

    app: App
    clock: FakeClock
    collector: FakeCollector
    url_collector: FakeCollector
    notifier: RecordingNotifier


def plugins(collector: FakeCollector, url_collector: FakeCollector) -> Plugins:
    return Plugins(
        collectors={collector.name: collector, url_collector.name: url_collector},
        filters={"keyword": KeywordFilter()},
        renderers={"text": TextRenderer()},
    )


def make_world(state_dir: Path, config: Config | None = None) -> World:
    clock = FakeClock()
    collector = FakeCollector()
    url_collector = FakeCollector(name="fetch", follows_client_urls=True)
    notifier = RecordingNotifier()
    config = config or Config(state_dir=state_dir, public_url="https://veille.example.org")
    app = open_app(config, plugins=plugins(collector, url_collector), clock=clock, notifiers=[notifier])
    return World(app, clock, collector, url_collector, notifier)
