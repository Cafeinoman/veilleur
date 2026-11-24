# SPDX-License-Identifier: EUPL-1.2
"""Independent check of milestone G2 (core, storage, administration), written from the spec and protocol §9."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest

from tests.server.fakes import START, World, make_world
from veilleur.adapters import keys
from veilleur.adapters.sqlite.store import SqliteStore
from veilleur.apps.server.config import Config
from veilleur.apps.server.context import open_app
from veilleur.core.domain.errors import CollectorError, VeilleurError
from veilleur.core.domain.model import Collected, CollectedItem, Origin
from veilleur.core.ports.plugins import FilterItem
from veilleur.core.services import jobs, pairing, reports, round, subscriptions
from veilleur.core.services.subscriptions import TeamSubscription, sync_team
from veilleur_protocol import Kind, ProtocolError, open_package

UID = "11112222333344445555666677778888"


@pytest.fixture
def world(tmp_path: Path) -> Iterator[World]:
    w = make_world(tmp_path / "state")
    yield w
    w.app.close()


def _doc(topic: str = "news", **extra: Any) -> dict[str, Any]:
    return {"collector": "fake", "params": {"topic": topic}, "frequency": "every_round", **extra}


def _subscribe(world: World, uid: str = UID, label: str = "desk 1", **extra: Any) -> tuple[str, bytes]:
    p = pairing.create_pairing(world.app.core, label)
    subscriptions.put_subscription(world.app.core, p.key_id, uid, 0, _doc(**extra))
    return p.key_id, p.secret


def _open(world: World, key_id: str, uid: str, seq: int, secret: bytes) -> Any:
    data = world.app.store.get_package(key_id, uid, seq)
    assert data is not None
    return open_package(data, secret=secret, uid=uid, trusted_keys=[world.app.core.sealer.public_key], seq=seq)


# --- EF-05: a failing source never stops the round ----------------------------------------------------------------


def _raising() -> Iterator[CollectedItem]:
    yield CollectedItem({"title": "A"}, key="a")
    raise RuntimeError("source broke mid-way with internal detail")


@dataclass
class LazyCollector:
    """Returns a `Collected` whose items are a generator that fails while it is consumed."""

    name: str = "lazy"
    follows_client_urls: bool = False
    schema: dict[str, Any] = field(default_factory=lambda: {"type": "object"})

    def collect(self, params: Any, since: Any, http: Any) -> Collected:
        return Collected(_raising())  # type: ignore[arg-type]


@pytest.mark.xfail(
    reason=(
        "minor: a plugin breaking the Collected contract (lazy items) aborts run_round "
        "(collect.py:_normalise is outside the try)"
    ),
    strict=True,
)
def test_lazy_collected_items_that_fail_do_not_stop_the_round(world: World) -> None:
    """EF-05: a source that fails (here while its items are read) must not stop the round."""
    lazy = LazyCollector()
    world.app.core.plugins.collectors["lazy"] = lazy  # type: ignore[index]
    key_id, _ = _subscribe(world)
    p2 = pairing.create_pairing(world.app.core, "desk 2")
    subscriptions.put_subscription(world.app.core, p2.key_id, UID, 0, {"collector": "lazy", "frequency": "every_round"})
    world.collector.set("news", ("a", {"title": "A"}))
    summary = round.run_round(world.app.core)  # must not raise
    assert summary.collections == 2
    assert world.app.store.package_bounds(key_id, UID).last == 1


@pytest.mark.xfail(
    reason="minor: CollectorError with a non-str code raises TypeError in collect.py:89 and aborts run_round",
    strict=True,
)
def test_collector_error_with_a_non_string_code_does_not_stop_the_round(world: World) -> None:
    """EF-05: a plugin raising `CollectorError` with a malformed code is a failure like any other."""
    _subscribe(world)
    world.collector.fail = 404  # type: ignore[assignment]
    summary = round.run_round(world.app.core)
    assert summary.failed_collections == 1


def test_deeply_nested_item_fields_do_not_stop_the_round(world: World) -> None:
    """EF-05: an item the server cannot hash is an invalid item, not a crash of the round."""
    _subscribe(world)
    nested: dict[str, Any] = {}
    cursor = nested
    for _ in range(5000):
        cursor["x"] = {}
        cursor = cursor["x"]
    world.collector.items["news"] = [CollectedItem({"title": "ok"}, key="ok"), CollectedItem(nested, key="deep")]
    round.run_round(world.app.core)  # must not raise


def test_collector_error_code_is_kept_and_no_detail_leaks(world: World) -> None:
    key_id, secret = _subscribe(world)
    world.collector.fail = "crash"
    round.run_round(world.app.core)
    status = world.app.store.list_sources()[0]
    assert status.error == "collector_failed" and status.last_success is None
    world.collector.fail = None
    world.collector.set("news", ("a", {"title": "A"}))
    world.clock.advance(hours=1)
    round.run_round(world.app.core)
    opened = _open(world, key_id, UID, 1, secret)
    assert opened.manifest["sources"][0]["ok"] is True
    assert "detail" not in repr(opened.manifest)


# --- EF-04: shared collections across pairings and team subscriptions ---------------------------------------------


def test_collections_are_shared_across_pairings_and_team(world: World) -> None:
    core = world.app.core
    _subscribe(world, label="desk 1")
    _subscribe(world, label="desk 2")
    p3 = pairing.create_pairing(core, "desk 3")
    spec = subscriptions.parse_spec({"params": {"topic": "news"}, "collector": "fake"}, core.plugins)
    sync_team(core, [TeamSubscription("team", spec, (p3.key_id,))])
    world.collector.set("news", ("a", {"title": "A"}))
    round.run_round(core)
    assert len(world.collector.calls) == 1


# --- EF-10: team subscriptions -----------------------------------------------------------------------------------


@pytest.mark.xfail(
    reason=(
        "minor: sync_team keys tombstones and live rows by (key_id, name); ordering by "
        "(created_at, uid) lets a tombstone hide the live row within one second"
    ),
    strict=True,
)
def test_team_subscription_removed_then_declared_again_exists_once(world: World) -> None:
    """EF-10: declaring, removing and declaring again a team subscription must leave exactly one live copy per
    pairing, however many times the declaration is synchronised (the clock does not move here)."""
    core = world.app.core
    pairings = [pairing.create_pairing(core, f"desk {i}") for i in range(12)]
    key_ids = tuple(p.key_id for p in pairings)
    spec = subscriptions.parse_spec(_doc(), core.plugins)
    declared = [TeamSubscription("news", spec, key_ids)]
    sync_team(core, declared)
    sync_team(core, [])
    sync_team(core, declared)
    for _ in range(3):
        sync_team(core, declared)
    live = [s for s in core.store.list_subscriptions() if s.origin is Origin.TEAM]
    assert len(live) == len(key_ids)


def test_team_subscription_is_not_served_to_a_revoked_pairing(world: World) -> None:
    core = world.app.core
    p = pairing.create_pairing(core, "desk 1")
    spec = subscriptions.parse_spec(_doc(), core.plugins)
    sync_team(core, [TeamSubscription("news", spec, (p.key_id,))])
    pairing.revoke_pairing(core, "desk 1")
    world.collector.set("news", ("a", {"title": "A"}))
    summary = round.run_round(core)
    assert summary.states == 0 and summary.collections == 0


# --- EF-11, EF-12, EF-13, EF-14 -----------------------------------------------------------------------------------


def test_defaults_of_a_subscription_document(world: World) -> None:
    """EF-13: daily by default, English by default; protocol §9.1 defaults."""
    p = pairing.create_pairing(world.app.core, "desk 1")
    subscriptions.put_subscription(world.app.core, p.key_id, UID, 0, {"collector": "fake", "params": {"topic": "x"}})
    s = world.app.store.get_subscription(p.key_id, UID)
    assert s is not None
    assert s.spec.frequency.value == "daily" and s.spec.language == "en"
    assert s.spec.filters == () and s.spec.renderings == ()


@pytest.mark.parametrize(
    ("document", "code"),
    [
        ({}, "invalid_subscription"),
        ({"collector": 3}, "invalid_subscription"),
        ({"collector": "nope"}, "unknown_collector"),
        ({"collector": "fake", "params": None}, "invalid_subscription"),
        ({"collector": "fake", "params": {}}, "invalid_params"),
        ({"collector": "fake", "params": {"topic": ""}}, "invalid_params"),
        ({"collector": "fake", "params": {"topic": "x", "extra": 1}}, "invalid_params"),
        ({"collector": "fake", "params": {"topic": "x"}, "frequency": "hourly"}, "invalid_subscription"),
        ({"collector": "fake", "params": {"topic": "x"}, "language": "de"}, "invalid_subscription"),
        ({"collector": "fake", "params": {"topic": "x"}, "renderings": ["text", "text"]}, "invalid_subscription"),
        ({"collector": "fake", "params": {"topic": "x"}, "renderings": ["nope"]}, "unknown_renderer"),
        ({"collector": "fake", "params": {"topic": "x"}, "renderings": "text"}, "invalid_subscription"),
        ({"collector": "fake", "params": {"topic": "x"}, "filters": [{"name": "nope"}]}, "unknown_filter"),
        ({"collector": "fake", "params": {"topic": "x"}, "filters": [{"name": "keyword"}]}, "invalid_params"),
        (
            {
                "collector": "fake",
                "params": {"topic": "x"},
                "filters": [{"name": "keyword", "params": {"word": "a"}}] * 17,
            },
            "invalid_subscription",
        ),
        ({"collector": "fake", "params": {"topic": "x"}, "filters": ["keyword"]}, "invalid_subscription"),
    ],
)
def test_documents_are_refused_with_a_stable_code(world: World, document: dict[str, Any], code: str) -> None:
    p = pairing.create_pairing(world.app.core, "desk 1")
    with pytest.raises(VeilleurError) as caught:
        subscriptions.put_subscription(world.app.core, p.key_id, UID, 0, document)
    assert caught.value.code == code
    assert world.app.store.get_subscription(p.key_id, UID) is None


def test_grants_allow_and_deny(world: World) -> None:
    """EF-11: URL-following collectors refused by default; the administrator may allow them, or deny others."""
    core = world.app.core
    p = pairing.create_pairing(core, "desk 1")
    fetch = {"collector": "fetch", "params": {"topic": "x"}}
    with pytest.raises(VeilleurError, match="collector_not_allowed"):
        subscriptions.put_subscription(core, p.key_id, UID, 0, fetch)
    core.store.set_grant(p.key_id, "fetch", True)
    assert subscriptions.put_subscription(core, p.key_id, UID, 0, fetch) == 1
    core.store.set_grant(p.key_id, "fake", False)
    with pytest.raises(VeilleurError, match="collector_not_allowed"):
        subscriptions.put_subscription(core, p.key_id, "f" * 32, 0, _doc())
    core.store.set_grant(p.key_id, "fake", None)
    assert subscriptions.put_subscription(core, p.key_id, "f" * 32, 0, _doc()) == 1
    # Grants are per pairing.
    other = pairing.create_pairing(core, "desk 2")
    with pytest.raises(VeilleurError, match="collector_not_allowed"):
        subscriptions.put_subscription(core, other.key_id, UID, 0, fetch)


def test_versions_keep_growing_across_deletion(world: World) -> None:
    core = world.app.core
    key_id, _ = _subscribe(world)
    assert subscriptions.put_subscription(core, key_id, UID, 1, _doc("b")) == 2
    with pytest.raises(VeilleurError, match="version_conflict"):
        subscriptions.put_subscription(core, key_id, UID, 1, _doc("c"))
    subscriptions.delete_subscription(core, key_id, UID)
    s = core.store.get_subscription(key_id, UID)
    assert s is not None and s.deleted and s.version == 3
    for base in (0, 2, 3):
        with pytest.raises(VeilleurError, match="subscription_deleted"):
            subscriptions.put_subscription(core, key_id, UID, base, _doc())
    subscriptions.delete_subscription(core, key_id, UID)
    assert core.store.get_subscription(key_id, UID).version == 3  # type: ignore[union-attr]


# --- EF-31, EF-32, EF-40, EF-42, EF-44 ----------------------------------------------------------------------------


def test_numbering_has_no_gap_with_states_and_histories_on_request(world: World) -> None:
    """EF-40: a state or history on request carries the last number and does not consume one."""
    core = world.app.core
    key_id, secret = _subscribe(world)
    world.collector.set("news", ("a", {"title": "A"}))
    round.run_round(core)
    s = core.store.get_subscription(key_id, UID)
    assert s is not None
    built = reports.build_state(core, s)
    assert built is not None and built[0] == 1
    world.clock.advance(hours=1)
    world.collector.set("news", ("a", {"title": "A2"}), ("b", {"title": "B"}))
    round.run_round(core)
    assert [p.seq for p in core.store.list_packages(key_id, UID, 0)] == [1, 2]
    opened = _open(world, key_id, UID, 2, secret)
    assert opened.kind is Kind.DELTA
    assert [(i.key, i.change.value) for i in opened.items] == [("a", "changed"), ("b", "new")]
    assert opened.manifest["period"]["from"] == "2026-11-17T06:00:00Z"


def test_items_are_sorted_by_code_point(world: World) -> None:
    key_id, secret = _subscribe(world)
    world.collector.set("news", ("b", {"t": 1}), ("B", {"t": 2}), ("é", {"t": 3}), ("a", {"t": 4}))
    round.run_round(world.app.core)
    assert [i.key for i in _open(world, key_id, UID, 1, secret).items] == ["B", "a", "b", "é"]


def test_partial_then_complete_collection(world: World) -> None:
    core = world.app.core
    key_id, secret = _subscribe(world)
    world.collector.set("news", ("a", {"t": 1}), ("b", {"t": 2}))
    round.run_round(core)
    world.clock.advance(hours=1)
    world.collector.complete = False
    world.collector.set("news", ("a", {"t": 1}))
    round.run_round(core)
    assert core.store.package_bounds(key_id, UID).last == 1
    world.clock.advance(hours=1)
    world.collector.complete = True
    round.run_round(core)
    assert [(i.key, i.change.value) for i in _open(world, key_id, UID, 2, secret).items] == [("b", "gone")]


def test_item_that_comes_back_is_new_again(world: World) -> None:
    core = world.app.core
    key_id, secret = _subscribe(world)
    world.collector.set("news", ("a", {"t": 1}))
    round.run_round(core)
    world.clock.advance(hours=1)
    world.collector.set("news")
    round.run_round(core)
    world.clock.advance(hours=1)
    world.collector.set("news", ("a", {"t": 1}))
    round.run_round(core)
    changes = [[(i.key, i.change.value) for i in _open(world, key_id, UID, n, secret).items] for n in (1, 2, 3)]
    assert changes == [[("a", "new")], [("a", "gone")], [("a", "new")]]


@dataclass
class InPlaceFilter:
    """A filter that transforms an item by changing its fields in place (EF-20: filters may transform)."""

    name: str = "upper"
    schema: dict[str, Any] = field(default_factory=lambda: {"type": "object"})

    def apply(self, item: FilterItem, params: Any) -> FilterItem | None:
        item.fields["title"] = str(item.fields.get("title", "")).upper()
        return item


# Reservation fixed in G3: filtered items are hashed again (reports._current_view).
def test_hash_matches_the_fields_of_a_transformed_item(world: World) -> None:
    """Protocol §7.4: `hash` is computed from the item's fields as reported; EF-21: stored items untouched."""
    from veilleur.core.domain.model import item_hash

    world.app.core.plugins.filters["upper"] = InPlaceFilter()  # type: ignore[index]
    key_id, secret = _subscribe(world, filters=[{"name": "upper"}])
    world.collector.set("news", ("a", {"title": "abc"}))
    round.run_round(world.app.core)
    item = _open(world, key_id, UID, 1, secret).items[0]
    assert item.fields == {"title": "ABC"}
    assert world.app.store.current_items(
        next(iter(s.spec.collection_id for s in world.app.store.list_subscriptions()))
    )["a"].fields == {"title": "abc"}
    assert item.hash == item_hash(item.fields)


# --- EF-45 and jobs -------------------------------------------------------------------------------------------------


def test_purge_keeps_numbers_and_state_after_purge(world: World) -> None:
    core = world.app.core
    key_id, secret = _subscribe(world)
    world.collector.set("news", ("a", {"t": 1}))
    round.run_round(core)
    world.clock.advance(days=89)
    world.collector.set("news", ("a", {"t": 1}), ("b", {"t": 2}))
    round.run_round(core)
    world.clock.advance(days=2)
    round.run_round(core)
    bounds = core.store.package_bounds(key_id, UID)
    assert (bounds.last, bounds.oldest, bounds.purged_through) == (2, 2, 1)
    s = core.store.get_subscription(key_id, UID)
    assert s is not None
    built = reports.build_state(core, s)
    assert built is not None
    opened = open_package(built[1], secret=secret, uid=UID, trusted_keys=[core.sealer.public_key], seq=2)
    assert opened.kind is Kind.STATE and [i.key for i in opened.items] == ["a", "b"]


def test_history_since_a_date(world: World) -> None:
    core = world.app.core
    key_id, secret = _subscribe(world)
    world.collector.set("news", ("a", {"t": 1}), ("b", {"t": 1}))
    round.run_round(core)
    world.clock.advance(days=3)
    world.collector.set("news", ("a", {"t": 2}), ("c", {"t": 1}))
    round.run_round(core)
    job = jobs.request_history(core, key_id, UID, "2026-11-19")
    jobs.run_job(core, job)
    done = core.store.find_job(job.kind, key_id, UID, "2026-11-19")
    assert done is not None and done.result is not None
    opened = open_package(done.result, secret=secret, uid=UID, trusted_keys=[core.sealer.public_key])
    assert opened.kind is Kind.HISTORY and opened.seq == 2
    assert opened.manifest["period"]["from"] == "2026-11-19T00:00:00Z"
    assert [(i.key, i.change.value) for i in opened.items] == [("a", "changed"), ("b", "gone"), ("c", "new")]


def test_pending_jobs_survive_a_restart(tmp_path: Path) -> None:
    """§7.5: jobs left pending by a previous process are taken up at start."""
    w = make_world(tmp_path / "state")
    p = pairing.create_pairing(w.app.core, "desk 1")
    subscriptions.put_subscription(w.app.core, p.key_id, UID, 0, _doc())
    w.app.close()
    w2 = make_world(tmp_path / "state")
    try:
        assert len(w2.app.store.pending_jobs()) == 1
        w2.collector.set("news", ("a", {"t": 1}))
        assert jobs.run_pending(w2.app.core) == 1
        assert w2.app.store.package_bounds(p.key_id, UID).last == 1
    finally:
        w2.app.close()


# --- EF-60 to EF-62 -------------------------------------------------------------------------------------------------


def test_pairing_secret_and_key_id(world: World) -> None:
    p = pairing.create_pairing(world.app.core, "desk 1")
    assert len(p.secret) == 32 and len(p.key_id) == 16 and int(p.key_id, 16) >= 0
    q = pairing.create_pairing(world.app.core, "desk 2")
    assert p.secret != q.secret and p.key_id != q.key_id
    assert "secret" not in repr(p) or p.secret.hex() not in repr(p)


@pytest.mark.parametrize("label", ["desk\t1", "a​b", "x\x00"])
def test_labels_refuse_control_and_format_characters(world: World, label: str) -> None:
    with pytest.raises(VeilleurError, match="invalid_label"):
        pairing.create_pairing(world.app.core, label)


def test_revoked_pairing_pending_first_state_is_not_made(world: World) -> None:
    core = world.app.core
    key_id, _ = _subscribe(world)
    pairing.revoke_pairing(core, key_id)
    world.collector.set("news", ("a", {"t": 1}))
    jobs.run_pending(core)
    round.run_round(core)
    assert core.store.package_bounds(key_id, UID).last == 0


# --- §7.2, EF-72: storage --------------------------------------------------------------------------------------------


def test_wal_mode_and_numbered_migrations(tmp_path: Path) -> None:
    store = SqliteStore(tmp_path / "v.db")
    try:
        assert store._db.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
        assert store._db.execute("PRAGMA user_version").fetchone()[0] >= 1
    finally:
        store.close()
    tables = {r[0] for r in sqlite3.connect(tmp_path / "v.db").execute("SELECT name FROM sqlite_master")}
    for table in (
        "pairing",
        "collector_grant",
        "subscription",
        "source_status",
        "item",
        "reported",
        "package",
        "job",
        "event",
    ):
        assert table in tables


def test_backup_is_a_readable_copy_before_migration(tmp_path: Path) -> None:
    db = tmp_path / "state" / "veilleur.db"
    db.parent.mkdir()
    old = sqlite3.connect(db)
    old.execute("CREATE TABLE marker (x)")
    old.execute("INSERT INTO marker VALUES (42)")
    old.commit()
    old.close()
    store = SqliteStore(db, backup_dir=tmp_path / "state" / "backups", now=START)
    try:
        assert store.backup is not None
        copy = sqlite3.connect(store.backup)
        assert copy.execute("SELECT x FROM marker").fetchone()[0] == 42
        assert copy.execute("PRAGMA user_version").fetchone()[0] == 0
        copy.close()
        assert store.backup.stat().st_mode & 0o777 == 0o600
    finally:
        store.close()


# --- ES-05: key rotation in a process that is already running ---------------------------------------------------------


@pytest.mark.xfail(
    reason=(
        "minor: the running service keeps the signing key loaded at start (context.open_app); a "
        "rotation needs a restart"
    ),
    strict=True,
)
def test_running_service_follows_a_key_rotation(tmp_path: Path) -> None:
    """ES-05 and protocol §6.3: after `veilleur key rotate` (another process), what the running service seals must
    still open for a receiving tool that adopted the new key and stopped trusting the old one."""
    service = make_world(tmp_path / "state")
    try:
        p = pairing.create_pairing(service.app.core, "desk 1")
        old_key = service.app.core.sealer.public_key
        subscriptions.put_subscription(service.app.core, p.key_id, UID, 0, _doc())
        keys.rotate(tmp_path / "state", service.clock.now())  # `veilleur key rotate`, another process
        new_key = keys.load_signing_key(tmp_path / "state").public_key
        assert new_key != old_key
        service.collector.set("news", ("a", {"t": 1}))
        jobs.run_pending(service.app.core)  # the worker of the running service makes the first state
        data = service.app.store.get_package(p.key_id, UID, 1)
        assert data is not None
        open_package(data, secret=p.secret, uid=UID, trusted_keys=[new_key], seq=1)
    finally:
        service.app.close()


@pytest.mark.xfail(
    reason=(
        "minor: a second `key rotate` within 90 days replaces the first statement (keys.rotate); "
        "receivers on the first key are stranded"
    ),
    strict=True,
)
def test_two_rotations_within_90_days_keep_receivers_following(tmp_path: Path) -> None:
    """ES-05: the rotation statement travels with every package for 90 days, so a receiver that still trusts the
    first key can follow without being paired again."""
    state = tmp_path / "state"
    w = make_world(state)
    first_key = w.app.core.sealer.public_key
    p = pairing.create_pairing(w.app.core, "desk 1")
    subscriptions.put_subscription(w.app.core, p.key_id, UID, 0, _doc())
    w.app.close()
    keys.rotate(state, START)
    keys.rotate(state, START + timedelta(days=1))
    w = make_world(state)
    try:
        w.collector.set("news", ("a", {"t": 1}))
        jobs.run_pending(w.app.core)
        data = w.app.store.get_package(p.key_id, UID, 1)
        assert data is not None
        try:
            open_package(data, secret=p.secret, uid=UID, trusted_keys=[first_key], seq=1)
        except ProtocolError as exc:
            pytest.fail(f"receiver trusting the first key refused the package: {exc.code}")
    finally:
        w.app.close()


# --- ES-10 -----------------------------------------------------------------------------------------------------------


def test_state_dir_mode_and_no_secret_in_config(tmp_path: Path) -> None:
    config = Config(state_dir=tmp_path / "state", public_url="https://veille.example.org")
    app = open_app(config, plugins=make_world(tmp_path / "other").app.core.plugins)
    try:
        assert (tmp_path / "state").stat().st_mode & 0o777 == 0o700
        assert (tmp_path / "state" / "signing.key").stat().st_mode & 0o777 == 0o600
    finally:
        app.close()


def test_collector_error_codes_are_checked() -> None:
    assert CollectorError("network_unavailable").code == "network_unavailable"


# --- EF-05: item data from a source must never stop the round (blocking finding) -----------------------------------


@pytest.mark.parametrize("where", ["key", "url"])
def test_lone_surrogate_from_a_source_does_not_stop_the_round(world: World, where: str) -> None:
    """EF-05. A JSON source may hold `"\\ud800"` (valid JSON, decoded by `json.loads` into a lone surrogate); a
    collector that copies it into the item's key or address breaks no contract (`str`). The round must go on for
    every other subscription: the item is invalid (`bad_item`), the collection is partial."""
    import json

    other_key_id, _ = _subscribe(world, uid="c" * 32, label="desk 9", topic="other")
    _subscribe(world)
    bad = json.loads('"\\ud800"')
    item = CollectedItem({"t": 1}, key=bad) if where == "key" else CollectedItem({"t": 1}, key="k", url=bad)
    world.collector.items["news"] = [CollectedItem({"t": 0}, key="ok"), item]
    world.collector.set("other", ("a", {"t": 1}))
    round.run_round(world.app.core)  # raises UnicodeEncodeError from SqliteStore.save_items today
    assert world.app.store.package_bounds(other_key_id, "c" * 32).last == 1
