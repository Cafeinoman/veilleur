# SPDX-License-Identifier: EUPL-1.2
"""Second check of milestone G2: the fix of B1 (EF-05, a source's data never stops the round) and its neighbours."""

from __future__ import annotations

import json
from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, cast

import pytest

from tests.server.fakes import World, make_world
from veilleur.core.domain import errors
from veilleur.core.domain.model import CollectedItem
from veilleur.core.ports.plugins import FilterItem
from veilleur.core.services import pairing, round, subscriptions

UID = "11112222333344445555666677778888"
OTHER = "c" * 32
BAD = json.loads('"\\ud800"')


@pytest.fixture
def world(tmp_path: Path) -> Iterator[World]:
    w = make_world(tmp_path / "state")
    yield w
    w.app.close()


def _subscribe(world: World, uid: str, label: str, topic: str, **extra: Any) -> str:
    p = pairing.create_pairing(world.app.core, label)
    document = {"collector": "fake", "params": {"topic": topic}, "frequency": "every_round", **extra}
    subscriptions.put_subscription(world.app.core, p.key_id, uid, 0, document)
    return p.key_id


@pytest.mark.parametrize(
    "bad_item",
    [
        CollectedItem({"t": 1}, key=BAD),
        CollectedItem({"t": 1}, key="k", url=BAD),
        CollectedItem({"t": 1}, key="", url=BAD),  # the address becomes the key
        CollectedItem({"t": 1}, key=None, url=BAD),
        CollectedItem({BAD: 1}, key="k"),  # member name
        CollectedItem({"t": [BAD]}, key="k"),  # nested value
        CollectedItem({"t": 1}, key="x" + BAD + "y"),
        CollectedItem({"t": 1}, key="k", url="https://example.org/" + "\udfff"),
    ],
    ids=["key", "url", "empty-key-url", "no-key-url", "member", "nested", "key-inside", "low-surrogate-url"],
)
def test_unencodable_item_is_invalid_and_the_round_goes_on(world: World, bad_item: CollectedItem) -> None:
    """EF-05: the other subscriptions are served, the bad item is left out, the source records bad_item and,
    the collection being partial, no previously seen item is declared gone (EF-31)."""
    other = _subscribe(world, OTHER, "desk 9", "other")
    mine = _subscribe(world, UID, "desk 1", "news")
    world.collector.items["news"] = [CollectedItem({"t": 0}, key="ok"), CollectedItem({"t": 0}, key="old")]
    round.run_round(world.app.core)
    world.collector.items["news"] = [CollectedItem({"t": 0}, key="ok"), bad_item]
    world.collector.set("other", ("a", {"t": 1}))
    round.run_round(world.app.core)
    assert world.app.store.package_bounds(other, OTHER).last == 2
    current = world.app.store.current_items(
        world.app.store.get_subscription(mine, UID).spec.collection_id  # type: ignore[union-attr]
    )
    assert set(current) == {"ok", "old"}
    assert all(i.gone_at is None for i in current.values())
    statuses = {s.collection_id: s.error for s in world.app.store.list_sources()}
    assert errors.BAD_ITEM in statuses.values()


@dataclass
class UrlRewriter:
    """A filter that transforms the address of an item (EF-20: filters may transform)."""

    name: str = "rewrite"
    schema: dict[str, Any] = field(default_factory=lambda: {"type": "object"})
    url: Any = BAD

    def apply(self, item: FilterItem, params: Mapping[str, Any]) -> FilterItem | None:
        return replace(item, url=self.url)


def _add_filter(world: World, plugin: UrlRewriter) -> None:
    cast(dict[str, Any], world.app.core.plugins.filters)[plugin.name] = plugin


@pytest.mark.parametrize("url", [BAD, 42], ids=["surrogate", "int"])
def test_filter_returning_a_bad_address_does_not_stop_the_round(world: World, url: Any) -> None:
    """EF-05 / EF-20: a filter that breaks an item skips its subscription only; the others are served."""
    _add_filter(world, UrlRewriter(url=url))
    mine = _subscribe(world, UID, "desk 1", "news", filters=[{"name": "rewrite", "params": {}}])
    other = _subscribe(world, OTHER, "desk 9", "other")
    world.collector.set("news", ("a", {"t": 1}))
    world.collector.set("other", ("b", {"t": 1}))
    round.run_round(world.app.core)
    assert world.app.store.package_bounds(other, OTHER).last == 1
    assert world.app.store.package_bounds(mine, UID).last == 0


@pytest.mark.xfail(
    reason=(
        "hors specification: adapters/sealer.py:73 maps every ValueError to PackageTooLarge, so a filter that "
        "returns a bad address is counted as package_too_large instead of filter_failed"
    ),
    strict=True,
)
def test_filter_returning_a_bad_address_is_counted_as_a_filter_failure(world: World) -> None:
    _add_filter(world, UrlRewriter(url=BAD))
    _subscribe(world, UID, "desk 1", "news", filters=[{"name": "rewrite", "params": {}}])
    world.collector.set("news", ("a", {"t": 1}))
    summary = round.run_round(world.app.core)
    assert summary.skipped == {"filter_failed": 1}


@pytest.mark.parametrize("depth", [1000, 2000, 9000])
def test_deep_but_decodable_json_from_a_source_does_not_stop_the_round(world: World, depth: int) -> None:
    """EF-05, same mechanism as B1. `json.loads` accepts this document (the precondition is asserted), so a JSON
    collector that copies the value into a field respects its contract; `canonical_json` then raises
    RecursionError, which `_normalise` does not treat as an invalid item."""
    document = '{"x":' * depth + "1" + "}" * depth
    value = json.loads(document)  # valid JSON, decoded without error
    other = _subscribe(world, OTHER, "desk 9", "other")
    _subscribe(world, UID, "desk 1", "news")
    world.collector.items["news"] = [CollectedItem({"t": 0}, key="ok"), CollectedItem({"v": value}, key="deep")]
    world.collector.set("other", ("a", {"t": 1}))
    round.run_round(world.app.core)
    assert world.app.store.package_bounds(other, OTHER).last == 1
