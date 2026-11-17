# SPDX-License-Identifier: EUPL-1.2
"""Core services: collection, change detection, reports, frequencies, filters, purge, versions, team subscriptions."""

from __future__ import annotations

from typing import Any

import pytest

from veilleur.core.domain import errors
from veilleur.core.domain.errors import VeilleurError
from veilleur.core.domain.model import Change, Frequency, Kind, Origin, SubscriptionSpec, item_hash
from veilleur.core.services import jobs, pairing, reports, round, subscriptions
from veilleur.core.services.collect import collect
from veilleur.core.services.subscriptions import TeamSubscription, sync_team
from veilleur_protocol import Item, open_package

from .fakes import World


def _doc(topic: str = "news", **extra: Any) -> dict[str, Any]:
    return {"collector": "fake", "params": {"topic": topic}, "frequency": "every_round", **extra}


def _subscribe(world: World, document: dict[str, Any] | None = None, uid: str = "a" * 32) -> tuple[str, str]:
    p = pairing.create_pairing(world.app.core, "desk 3")
    subscriptions.put_subscription(world.app.core, p.key_id, uid, 0, document or _doc())
    return p.key_id, uid


def _open(world: World, key_id: str, uid: str, seq: int) -> list[Item]:
    data = world.app.store.get_package(key_id, uid, seq)
    assert data is not None
    secret = world.app.store.get_pairing(key_id).secret  # type: ignore[union-attr]
    opened = open_package(data, secret=secret, uid=uid, trusted_keys=[world.app.core.sealer.public_key], seq=seq)
    return opened.items


def _changes(items: list[Item]) -> list[tuple[str, str]]:
    return [(i.key, i.change.value) for i in items]


def test_new_changed_gone_across_rounds(world: World) -> None:
    key_id, uid = _subscribe(world)
    world.collector.set("news", ("a", {"title": "A"}), ("b", {"title": "B"}))
    summary = round.run_round(world.app.core)
    assert summary.states == 1 and summary.new_items == 2
    assert _changes(_open(world, key_id, uid, 1)) == [("a", "new"), ("b", "new")]
    world.clock.advance(hours=1)
    world.collector.set("news", ("a", {"title": "A2"}), ("c", {"title": "C"}))
    round.run_round(world.app.core)
    items = _open(world, key_id, uid, 2)
    assert _changes(items) == [("a", "changed"), ("b", "gone"), ("c", "new")]
    assert items[0].hash == item_hash({"title": "A2"})
    assert items[1].fields == {"title": "B"}
    info = world.app.store.last_package(key_id, uid)
    assert info is not None and info.kind is Kind.DELTA


def test_empty_report_is_not_produced(world: World) -> None:
    key_id, uid = _subscribe(world)
    world.collector.set("news", ("a", {"title": "A"}))
    round.run_round(world.app.core)
    world.clock.advance(hours=1)
    assert round.run_round(world.app.core).reports == 0
    assert world.app.store.package_bounds(key_id, uid).last == 1


def test_first_state_even_without_item(world: World) -> None:
    key_id, uid = _subscribe(world)
    round.run_round(world.app.core)
    assert _open(world, key_id, uid, 1) == []
    assert world.app.store.last_package(key_id, uid).kind is Kind.STATE  # type: ignore[union-attr]


def test_failed_or_partial_collection_never_makes_items_gone(world: World) -> None:
    key_id, uid = _subscribe(world)
    world.collector.set("news", ("a", {"title": "A"}), ("b", {"title": "B"}))
    round.run_round(world.app.core)
    world.collector.set("news", ("a", {"title": "A"}))
    world.collector.fail = "network_unavailable"
    world.clock.advance(hours=1)
    round.run_round(world.app.core)
    status = world.app.store.get_source(world.app.store.get_subscription(key_id, uid).spec.collection_id)  # type: ignore[union-attr]
    assert status is not None and status.error == "network_unavailable" and not status.ok
    world.collector.fail = None
    world.collector.complete = False
    world.clock.advance(hours=1)
    round.run_round(world.app.core)
    assert world.app.store.package_bounds(key_id, uid).last == 1
    world.collector.complete = True
    world.clock.advance(hours=1)
    round.run_round(world.app.core)
    assert _changes(_open(world, key_id, uid, 2)) == [("b", "gone")]


def test_collector_crash_is_reported_without_detail(world: World) -> None:
    key_id, uid = _subscribe(world)
    world.collector.fail = "crash"
    summary = round.run_round(world.app.core)
    assert summary.failed_collections == 1
    assert world.app.store.list_sources()[0].error == errors.COLLECTOR_FAILED
    assert world.app.store.package_bounds(key_id, uid).last == 0  # no state before a successful collection
    world.collector.fail = None
    round.run_round(world.app.core)
    assert world.app.store.package_bounds(key_id, uid).last == 1


def test_invalid_items_make_the_collection_partial(world: World) -> None:
    from veilleur.core.domain.model import CollectedItem

    key_id, uid = _subscribe(world)
    world.collector.set("news", ("a", {"title": "A"}), ("b", {"title": "B"}))
    round.run_round(world.app.core)
    world.collector.items["news"] = [CollectedItem({"x": float("nan")}, key="c")]
    world.clock.advance(hours=1)
    round.run_round(world.app.core)
    assert world.app.store.list_sources()[0].error == errors.BAD_ITEM
    assert world.app.store.package_bounds(key_id, uid).last == 1  # nothing gone


@pytest.mark.parametrize("where", ["key", "url", "fields"])
def test_lone_surrogate_makes_the_item_invalid(world: World, where: str) -> None:
    """EF-05: valid JSON may decode into a lone surrogate, which cannot be stored; the round goes on."""
    from veilleur.core.domain.model import CollectedItem

    key_id, uid = _subscribe(world)
    bad = "\ud800"
    item = {
        "key": CollectedItem({"n": 1}, key=bad),
        "url": CollectedItem({"n": 1}, key="k", url=bad),
        "fields": CollectedItem({"n": bad}, key="k"),
    }[where]
    world.collector.items["news"] = [CollectedItem({"n": 0}, key="ok"), item]
    round.run_round(world.app.core)
    assert world.app.store.list_sources()[0].error == errors.BAD_ITEM
    assert [i.key for i in _open(world, key_id, uid, 1)] == ["ok"]


def test_too_deep_item_is_invalid(world: World) -> None:
    """EF-05: json.loads decodes about 10,000 levels, more than the item hash can walk; the round goes on."""
    import json

    from veilleur.core.domain.model import CollectedItem

    key_id, uid = _subscribe(world)
    depth = 3000
    deep = json.loads('{"x":' * depth + "0" + "}" * depth)
    world.collector.items["news"] = [CollectedItem({"n": 0}, key="ok"), CollectedItem(deep, key="deep")]
    round.run_round(world.app.core)
    assert world.app.store.list_sources()[0].error == errors.BAD_ITEM
    assert [i.key for i in _open(world, key_id, uid, 1)] == ["ok"]


def test_item_key_falls_back_to_url_then_hash(world: World) -> None:
    from veilleur.core.domain.model import CollectedItem

    key_id, uid = _subscribe(world)
    world.collector.items["news"] = [
        CollectedItem({"n": 1}, url="https://example.org/1"),
        CollectedItem({"n": 2}),
    ]
    round.run_round(world.app.core)
    keys = [i.key for i in _open(world, key_id, uid, 1)]
    assert sorted(keys) == sorted(["https://example.org/1", item_hash({"n": 2})])


def test_collections_are_shared(world: World) -> None:
    p1 = pairing.create_pairing(world.app.core, "desk 1")
    p2 = pairing.create_pairing(world.app.core, "desk 2")
    subscriptions.put_subscription(world.app.core, p1.key_id, "a" * 32, 0, _doc())
    subscriptions.put_subscription(world.app.core, p2.key_id, "b" * 32, 0, _doc(frequency="daily"))
    subscriptions.put_subscription(world.app.core, p2.key_id, "c" * 32, 0, _doc("other"))
    summary = round.run_round(world.app.core)
    assert summary.collections == 2
    assert sorted(c[0]["topic"] for c in world.collector.calls) == ["news", "other"]


def test_since_is_the_last_successful_collection(world: World) -> None:
    _subscribe(world)
    round.run_round(world.app.core)
    first = world.clock.now()
    world.clock.advance(hours=1)
    round.run_round(world.app.core)
    assert [c[1] for c in world.collector.calls] == [None, first]


def test_daily_frequency_accumulates_changes(world: World) -> None:
    key_id, uid = _subscribe(world, _doc(frequency="daily"))
    world.collector.set("news", ("a", {"title": "A"}))
    round.run_round(world.app.core)
    for hour in range(1, 23):
        world.clock.advance(hours=1)
        world.collector.set("news", ("a", {"title": "A"}), ("b", {"title": f"B{hour}"}))
        round.run_round(world.app.core)
    assert world.app.store.package_bounds(key_id, uid).last == 1
    world.clock.advance(hours=1)
    world.collector.set("news", ("b", {"title": "B"}))
    round.run_round(world.app.core)
    assert _changes(_open(world, key_id, uid, 2)) == [("a", "gone"), ("b", "new")]


def test_weekly_frequency(world: World) -> None:
    key_id, uid = _subscribe(world, _doc(frequency="weekly"))
    round.run_round(world.app.core)
    world.collector.set("news", ("a", {"title": "A"}))
    world.clock.advance(days=6)
    round.run_round(world.app.core)
    assert world.app.store.package_bounds(key_id, uid).last == 1
    world.clock.advance(days=1)
    round.run_round(world.app.core)
    assert world.app.store.package_bounds(key_id, uid).last == 2


def test_filters_select_without_touching_stored_items(world: World) -> None:
    key_id, uid = _subscribe(world, _doc(filters=[{"name": "keyword", "params": {"word": "vote"}}]))
    world.collector.set("news", ("a", {"title": "vote today"}), ("b", {"title": "weather"}))
    round.run_round(world.app.core)
    assert _changes(_open(world, key_id, uid, 1)) == [("a", "new")]
    spec = world.app.store.get_subscription(key_id, uid).spec  # type: ignore[union-attr]
    assert set(world.app.store.current_items(spec.collection_id)) == {"a", "b"}
    world.clock.advance(hours=1)
    world.collector.set("news", ("a", {"title": "rain"}), ("b", {"title": "vote tomorrow"}))
    round.run_round(world.app.core)
    assert _changes(_open(world, key_id, uid, 2)) == [("a", "gone"), ("b", "new")]


def test_renderings_are_added(world: World) -> None:
    key_id, uid = _subscribe(world, _doc(renderings=["text"], language="fr"))
    world.collector.set("news", ("a", {"title": "A"}))
    round.run_round(world.app.core)
    data = world.app.store.get_package(key_id, uid, 1)
    secret = world.app.store.get_pairing(key_id).secret  # type: ignore[union-attr]
    opened = open_package(data or b"", secret=secret, uid=uid, trusted_keys=[world.app.core.sealer.public_key])
    assert opened.renderings == {"report.txt": b"fr state 1\nnew a"}
    assert opened.manifest["sources"][0]["ok"] is True


def test_state_and_history_on_request(world: World) -> None:
    key_id, uid = _subscribe(world)
    sub = world.app.store.get_subscription(key_id, uid)
    assert sub is not None
    assert reports.build_state(world.app.core, sub) is None
    world.collector.set("news", ("a", {"title": "A"}), ("b", {"title": "B"}))
    round.run_round(world.app.core)
    world.clock.advance(days=3)
    world.collector.set("news", ("b", {"title": "B2"}), ("c", {"title": "C"}))
    round.run_round(world.app.core)
    built = reports.build_state(world.app.core, sub)
    assert built is not None and built[0] == 2
    secret = world.app.store.get_pairing(key_id).secret  # type: ignore[union-attr]
    state = open_package(built[1], secret=secret, uid=uid, trusted_keys=[world.app.core.sealer.public_key], seq=2)
    assert state.kind.value == "state" and _changes(state.items) == [("b", "new"), ("c", "new")]
    history = reports.build_history(world.app.core, sub, jobs.parse_since("2026-11-18"))
    assert history is not None
    opened = open_package(history[1], secret=secret, uid=uid, trusted_keys=[world.app.core.sealer.public_key])
    assert opened.kind.value == "history"
    assert _changes(opened.items) == [("a", "gone"), ("b", "changed"), ("c", "new")]
    assert opened.manifest["period"]["from"] == "2026-11-18T00:00:00Z"


def test_purge_after_90_days(world: World) -> None:
    key_id, uid = _subscribe(world)
    world.collector.set("news", ("a", {"title": "A"}))
    round.run_round(world.app.core)
    world.clock.advance(days=1)
    world.collector.set("news")
    round.run_round(world.app.core)
    world.clock.advance(days=90)
    assert round.run_round(world.app.core).purged["packages"] == 1  # kept 90 days, not less
    world.clock.advance(seconds=1)
    summary = round.run_round(world.app.core)
    assert summary.purged["packages"] == 1 and summary.purged["items"] == 1
    bounds = world.app.store.package_bounds(key_id, uid)
    assert (bounds.last, bounds.oldest, bounds.purged_through) == (2, None, 2)
    assert world.app.store.get_package(key_id, uid, 1) is None


def test_failing_sources_are_counted_after_two_days(world: World) -> None:
    _subscribe(world)
    round.run_round(world.app.core)
    world.collector.fail = "network_unavailable"
    world.clock.advance(days=1)
    assert round.run_round(world.app.core).failing_sources == 0  # failing since now
    world.clock.advance(days=1)
    assert round.run_round(world.app.core).failing_sources == 0
    world.clock.advance(days=1)
    assert round.run_round(world.app.core).failing_sources == 1
    world.collector.fail = None
    world.clock.advance(days=1)
    assert round.run_round(world.app.core).failing_sources == 0


def test_notification_carries_counts_only_after_reports(world: World) -> None:
    _subscribe(world)
    world.collector.set("news", ("a", {"title": "A"}))
    round.run_round(world.app.core)
    world.clock.advance(hours=1)
    round.run_round(world.app.core)
    assert [(c.reports, c.new_items, c.failing_sources) for c in world.notifier.sent] == [(1, 1, 0)]


def test_revoked_pairing_is_not_served(world: World) -> None:
    key_id, uid = _subscribe(world)
    pairing.revoke_pairing(world.app.core, key_id)
    assert round.run_round(world.app.core).collections == 0
    assert world.app.store.package_bounds(key_id, uid).last == 0


# --- Subscriptions and versions --------------------------------------------------------------------------------


def test_versions_and_conflicts(world: World) -> None:
    key_id, uid = _subscribe(world)
    core = world.app.core
    with pytest.raises(VeilleurError) as conflict:
        subscriptions.put_subscription(core, key_id, uid, 0, _doc())
    assert conflict.value.code == errors.VERSION_CONFLICT and conflict.value.params == {"version": 1}
    assert subscriptions.put_subscription(core, key_id, uid, 1, _doc("other")) == 2
    with pytest.raises(VeilleurError, match="version_conflict"):
        subscriptions.put_subscription(core, key_id, uid, 1, _doc())


def test_deleted_uid_is_never_reused_and_deleting_again_changes_nothing(world: World) -> None:
    key_id, uid = _subscribe(world)
    core = world.app.core
    subscriptions.delete_subscription(core, key_id, uid)
    deleted = core.store.get_subscription(key_id, uid)
    assert deleted is not None and deleted.deleted and deleted.version == 2
    subscriptions.delete_subscription(core, key_id, uid)  # replayed DELETE
    assert core.store.get_subscription(key_id, uid).version == 2  # type: ignore[union-attr]
    for base in (0, 1, 2):  # replayed creation, or any later change
        with pytest.raises(VeilleurError) as refused:
            subscriptions.put_subscription(core, key_id, uid, base, _doc())
        assert refused.value.code == errors.SUBSCRIPTION_DELETED
    with pytest.raises(VeilleurError, match="not_found"):
        subscriptions.delete_subscription(core, key_id, "b" * 32)


def test_pairings_have_separate_uid_spaces(world: World) -> None:
    key_id, uid = _subscribe(world)
    other = pairing.create_pairing(world.app.core, "desk 4")
    assert subscriptions.put_subscription(world.app.core, other.key_id, uid, 0, _doc("x")) == 1
    assert world.app.store.get_subscription(key_id, uid).spec.params == {"topic": "news"}  # type: ignore[union-attr]


@pytest.mark.parametrize(
    ("document", "code"),
    [
        ({"params": {"topic": "x"}}, errors.INVALID_SUBSCRIPTION),
        ({"collector": "nope"}, errors.UNKNOWN_COLLECTOR),
        ({"collector": "fake", "params": {}}, errors.INVALID_PARAMS),
        ({"collector": "fake", "params": {"topic": "x", "more": 1}}, errors.INVALID_PARAMS),
        ({"collector": "fake", "params": []}, errors.INVALID_SUBSCRIPTION),
        ({"collector": "fake", "params": {"topic": "x"}, "frequency": "hourly"}, errors.INVALID_SUBSCRIPTION),
        ({"collector": "fake", "params": {"topic": "x"}, "language": "de"}, errors.INVALID_SUBSCRIPTION),
        ({"collector": "fake", "params": {"topic": "x"}, "renderings": ["pdf"]}, errors.UNKNOWN_RENDERER),
        ({"collector": "fake", "params": {"topic": "x"}, "renderings": ["text", "text"]}, errors.INVALID_SUBSCRIPTION),
        ({"collector": "fake", "params": {"topic": "x"}, "filters": [{"name": "nope"}]}, errors.UNKNOWN_FILTER),
        ({"collector": "fake", "params": {"topic": "x"}, "filters": [{"name": "keyword"}]}, errors.INVALID_PARAMS),
        ({"collector": "fake", "params": {"topic": "x"}, "filters": "keyword"}, errors.INVALID_SUBSCRIPTION),
    ],
)
def test_documents_are_validated(world: World, document: dict[str, Any], code: str) -> None:
    with pytest.raises(VeilleurError) as refused:
        subscriptions.parse_spec(document, world.app.core.plugins)
    assert refused.value.code == code


def test_document_defaults_and_unknown_members(world: World) -> None:
    spec = subscriptions.parse_spec(
        {"collector": "fake", "params": {"topic": "x"}, "future": 1}, world.app.core.plugins
    )
    assert spec == SubscriptionSpec("fake", {"topic": "x"}, (), Frequency.DAILY, "en", ())


def test_collectors_following_client_urls_need_a_grant(world: World) -> None:
    p = pairing.create_pairing(world.app.core, "desk 3")
    core = world.app.core
    doc = {"collector": "fetch", "params": {"topic": "x"}}
    assert [c.name for c in subscriptions.allowed_collectors(core, p.key_id)] == ["fake"]
    with pytest.raises(VeilleurError, match="collector_not_allowed"):
        subscriptions.put_subscription(core, p.key_id, "a" * 32, 0, doc)
    core.store.set_grant(p.key_id, "fetch", True)
    core.store.set_grant(p.key_id, "fake", False)
    assert [c.name for c in subscriptions.allowed_collectors(core, p.key_id)] == ["fetch"]
    assert subscriptions.put_subscription(core, p.key_id, "a" * 32, 0, doc) == 1
    with pytest.raises(VeilleurError, match="collector_not_allowed"):
        subscriptions.put_subscription(core, p.key_id, "b" * 32, 0, _doc())


def test_team_subscriptions_are_synchronised(world: World) -> None:
    core = world.app.core
    p1 = pairing.create_pairing(core, "desk 1")
    p2 = pairing.create_pairing(core, "desk 2")
    spec = subscriptions.parse_spec(_doc(), core.plugins)
    assert sync_team(core, [TeamSubscription("news", spec, (p1.key_id, p2.key_id))]) == {
        "created": 2,
        "updated": 0,
        "deleted": 0,
    }
    team = [s for s in core.store.list_subscriptions() if s.origin is Origin.TEAM]
    assert len(team) == 2 and len({s.uid for s in team}) == 2
    assert sync_team(core, [TeamSubscription("news", spec, (p1.key_id, p2.key_id))])["created"] == 0
    other = subscriptions.parse_spec(_doc("other"), core.plugins)
    assert sync_team(core, [TeamSubscription("news", other, (p1.key_id,))]) == {
        "created": 0,
        "updated": 1,
        "deleted": 1,
    }
    uid = next(s.uid for s in core.store.list_subscriptions() if s.key_id == p1.key_id)
    with pytest.raises(VeilleurError, match="team_subscription"):
        subscriptions.put_subscription(core, p1.key_id, uid, 2, _doc())
    with pytest.raises(VeilleurError, match="team_subscription"):
        subscriptions.delete_subscription(core, p1.key_id, uid)


def test_first_state_job(world: World) -> None:
    key_id, uid = _subscribe(world)
    world.collector.set("news", ("a", {"title": "A"}))
    assert jobs.run_pending(world.app.core) == 1
    assert _changes(_open(world, key_id, uid, 1)) == [("a", "new")]
    assert jobs.run_pending(world.app.core) == 0


def test_pairing_labels(world: World) -> None:
    for label in ("", " ", "x" * 65, "desk\n3"):
        with pytest.raises(VeilleurError, match="invalid_label"):
            pairing.create_pairing(world.app.core, label)
    pairing.create_pairing(world.app.core, "desk 3")
    pairing.create_pairing(world.app.core, "desk 3")
    with pytest.raises(VeilleurError, match="ambiguous_pairing"):
        pairing.find_pairing(world.app.core, "desk 3")
    with pytest.raises(VeilleurError, match="unknown_pairing"):
        pairing.find_pairing(world.app.core, "desk 9")


def test_change_detection_hashes_canonical_fields(world: World) -> None:
    key_id, uid = _subscribe(world)
    world.collector.set("news", ("a", {"x": 1, "y": "é"}))
    round.run_round(world.app.core)
    world.clock.advance(hours=1)
    world.collector.set("news", ("a", {"y": "é", "x": 1}))
    round.run_round(world.app.core)
    assert world.app.store.package_bounds(key_id, uid).last == 1
    spec = world.app.store.get_subscription(key_id, uid).spec  # type: ignore[union-attr]
    assert collect(world.app.core, spec).changed == 0
    assert Change.NEW.value == "new"
