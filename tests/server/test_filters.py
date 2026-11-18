# SPDX-License-Identifier: EUPL-1.2
"""Filters `keywords`, `regex` and `dedup` (cahier EF-20, EF-21), alone and in a round."""

from __future__ import annotations

import time
from typing import Any

import pytest

from veilleur.adapters.filters import DedupFilter, KeywordsFilter, RegexFilter, compile_pattern
from veilleur.core.domain.errors import VeilleurError
from veilleur.core.domain.model import CollectedItem
from veilleur.core.ports.plugins import FilterItem, Plugins
from veilleur.core.services import round
from veilleur.core.services.pairing import create_pairing
from veilleur.core.services.subscriptions import parse_spec, put_subscription

from .fakes import World

ITEM = FilterItem("k", {"title": "Élection du Conseil", "body": "Le budget est voté", "tags": ["Café", "x"]}, None)


def _kw(**params: Any) -> bool:
    return KeywordsFilter().apply(ITEM, params) is not None


def _re(**params: Any) -> bool:
    return RegexFilter().apply(ITEM, params) is not None


def test_keywords() -> None:
    assert _kw(words=["conseil"])
    assert not _kw(words=["conseil"], case_sensitive=True)
    assert not _kw(words=["election"])
    assert _kw(words=["election"], accent_sensitive=False)
    assert _kw(words=["cafe"], accent_sensitive=False)  # inside a list
    assert not _kw(words=["budget"], fields=["title"])
    assert _kw(words=["budget", "absent"])
    assert not _kw(words=["budget", "absent"], match="all")
    assert not _kw(words=["budget"], exclude=True)
    assert _kw(words=["absent"], exclude=True)


def test_regex() -> None:
    assert _re(pattern=r"\bconseil\b")
    assert not _re(pattern=r"conseil", case_sensitive=True)
    assert _re(pattern=r"^election", accent_sensitive=False)
    assert not _re(pattern=r"vot[ée]", fields=["title"])
    assert not _re(pattern=r"budget", exclude=True)


@pytest.mark.parametrize(
    "pattern",
    [
        r"(a+)+$",
        r"(a*)*b",
        r"(a|a)*c",
        r"(a|ab)+",
        r"(\w+\s?)+$",
        r"(.*a){20}",
        r"(a)\1",
        r"(?P<x>a)(?P=x)",
        "(",
        "x" * 501,
    ],
)
def test_risky_or_malformed_patterns_are_refused(pattern: str) -> None:
    with pytest.raises(ValueError):
        compile_pattern(pattern, case=False)
    assert RegexFilter().check_params({"pattern": pattern}) == "/pattern"


@pytest.mark.parametrize(
    "pattern", [r"\bbudget\b", r"[ab]+c", r"^\d{4}-\d{2}$", r"foo|bar", r"(?:é|e)lection", r"a{2,5}"]
)
def test_usual_patterns_are_accepted(pattern: str) -> None:
    compile_pattern(pattern, case=False)
    assert RegexFilter().check_params({"pattern": pattern}) is None


def test_long_text_is_cut() -> None:
    item = FilterItem("k", {"t": "a" * 1_000_000 + "needle"}, None)
    start = time.monotonic()
    assert RegexFilter().apply(item, {"pattern": "needle"}) is None
    assert time.monotonic() - start < 1


def test_dedup() -> None:
    items = [
        FilterItem("1", {"title": "Same  Title"}, "https://example.org/a"),
        FilterItem("2", {"title": "same title"}, "https://example.org/b"),
        FilterItem("3", {"title": "Other"}, "https://example.org/a"),
        FilterItem("4", {"other": 1}, None),
        FilterItem("5", {"other": 2}, None),
    ]
    assert [i.key for i in DedupFilter().select(items, {"fields": ["title"]})] == ["1", "3", "4", "5"]
    assert [i.key for i in DedupFilter().select(items, {"by_url": True})] == ["1", "2", "4", "5"]
    assert DedupFilter().check_params({}) == "/fields"


def test_filter_parameters_are_checked_on_reception(world: World) -> None:
    plugins = Plugins(world.app.core.plugins.collectors, {"regex": RegexFilter(), "dedup": DedupFilter()}, {})
    document = {
        "collector": "fake",
        "params": {"topic": "t"},
        "filters": [{"name": "regex", "params": {"pattern": "(a+)+"}}],
    }
    with pytest.raises(VeilleurError) as caught:
        parse_spec(document, plugins)
    assert caught.value.code == "invalid_params"
    assert caught.value.params == {"path": "filters/0/params/pattern", "keyword": "check"}
    with pytest.raises(VeilleurError):
        parse_spec({**document, "filters": [{"name": "dedup", "params": {}}]}, plugins)


def test_filters_in_a_round(world: World) -> None:
    """EF-21: filters apply to what is reported, never to stored items; dedup works across the whole collection."""
    core = world.app.core
    plugins = Plugins(
        core.plugins.collectors,
        {"keywords": KeywordsFilter(), "dedup": DedupFilter()},
        core.plugins.renderers,
    )
    object.__setattr__(core, "plugins", plugins)
    pairing = create_pairing(core, "desk")
    filters = [
        {"name": "keywords", "params": {"words": ["budget"], "accent_sensitive": False}},
        {"name": "dedup", "params": {"fields": ["title"]}},
    ]
    document = {"collector": "fake", "params": {"topic": "t"}, "filters": filters, "frequency": "every_round"}
    put_subscription(core, pairing.key_id, "0" * 32, 0, document)
    world.collector.items["t"] = [
        CollectedItem({"title": "Budget vote"}, key="a"),
        CollectedItem({"title": "Weather"}, key="b"),
    ]
    round.run_round(core)
    reported = world.app.store.reported_items(pairing.key_id, "0" * 32)
    assert set(reported) == {"a"}
    world.clock.advance(hours=1)
    world.collector.items["t"].append(CollectedItem({"title": "BUDGET  vote"}, key="c"))  # same entry, new key
    assert round.run_round(core).reports == 0
    assert len(world.app.store.current_items(world.app.store.list_subscriptions()[0].spec.collection_id)) == 3
