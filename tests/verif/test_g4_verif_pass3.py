# SPDX-License-Identifier: EUPL-1.2
"""Third pass on batch G4: a folder export holds the `state` beside the packages (protocol §6.3, cahier §10)."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from tests.receiver.test_end_to_end import OTHER, UID, Bench, WsgiTransport, _pair, _rotate, _sealed, _two_reports
from tests.server.fakes import make_world
from veilleur.adapters import keys
from veilleur.adapters.renderers import HtmlRenderer, MarkdownRenderer
from veilleur.adapters.sealer import ProtocolSealer
from veilleur.apps.server import cli as server_cli
from veilleur.apps.server.wsgi import Api, RateLimiter
from veilleur.core.ports.plugins import Plugins, Renderer
from veilleur.core.ports.sealer import PackageTooLarge
from veilleur.core.services import pairing
from veilleur_protocol import PairingCode, make_rotation, read_header, seal_package
from veilleur_protocol.envelope import Kind
from veilleur_protocol.package import PackageContent
from veilleur_protocol.signing import SigningKey
from veilleur_receive import store


@pytest.fixture(name="bench")
def _bench(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Bench]:
    world = make_world(tmp_path / "server")
    plugins = world.app.core.plugins
    renderers: dict[str, Renderer] = {"markdown": MarkdownRenderer(), "html": HtmlRenderer()}
    core = replace(world.app.core, plugins=Plugins(plugins.collectors, plugins.filters, renderers))
    created = pairing.create_pairing(core, "desk 1")
    code = PairingCode("https://veille.example.org", created.key_id, created.secret, core.sealer.public_key).encode()
    transport = WsgiTransport(Api(core, limiter=RateLimiter(limit=100_000)))
    result = Bench(world, core, created, code, transport, tmp_path / "receiver", tmp_path / "reports")
    assert _pair(result, monkeypatch) == 0
    monkeypatch.setattr(world.app.store, "close", lambda: None)
    yield result
    world.app.close()


def _admin(bench: Bench, *argv: str, lang: str = "en") -> int:
    state_dir = str(bench.world.app.config.state_dir)
    return server_cli.main(["--lang", lang, "--state-dir", state_dir, *argv], opener=lambda config: bench.world.app)


def _export(bench: Bench, target: Path, uid: str = UID, *options: str, lang: str = "en") -> int:
    return _admin(bench, "export", uid, "--folder", str(target), *options, lang=lang)


def _read(bench: Bench, source: Path) -> int:
    return bench.receive("pull", "--folder", str(bench.folder), "--from", str(source))


def _names(folder: Path) -> list[str]:
    return sorted(path.name for path in folder.iterdir())


def _stored(bench: Bench, uid: str = UID) -> dict[str, bytes]:
    """What the server keeps, under the name of an export."""
    found: dict[str, bytes] = {}
    for info in bench.world.app.store.list_packages(bench.pairing.key_id, uid, 0):
        data = bench.world.app.store.get_package(bench.pairing.key_id, uid, info.seq)
        assert data is not None
        found[f"{uid}-{info.seq:08d}-{info.kind.value}.veil"] = data
    return found


def _report(bench: Bench, *letters: str, topic: str = "news") -> None:
    bench.world.collector.set(topic, *((letter, {"title": letter.upper()}) for letter in letters))
    bench.round()


def _three_keys(bench: Bench) -> None:
    """Packages 1, 2 and 3 of UID, signed by the keys A, B and C."""
    bench.subscribe()
    _report(bench, "a")
    bench.core = _rotate(bench)
    _report(bench, "a", "b")
    bench.core = _rotate(bench)
    _report(bench, "a", "b", "c")


def _forged(bench: Bench, seq: int, kind: Kind, key: SigningKey, rotation: Any = None, uid: str = UID) -> bytes:
    moment = bench.world.clock.now()
    content = PackageContent(uid, seq, kind, moment, moment, None, b"", rotation=rotation)
    return seal_package(bench.pairing.secret, key, content)


# --- The decision on R1: the `state` comes in addition to the packages, under a name of its own -------------------


def test_the_state_does_not_overwrite_a_stored_state_of_the_same_number(bench: Bench, tmp_path: Path) -> None:
    bench.subscribe()
    _report(bench, "a")
    stored = _stored(bench)
    bench.core = _rotate(bench)
    assert _export(bench, tmp_path / "usb") == 0
    rebuilt = f"{UID}-00000001-state-rebuilt.veil"
    assert _names(tmp_path / "usb") == sorted([*stored, rebuilt])
    for name, data in stored.items():
        assert (tmp_path / "usb" / name).read_bytes() == data
    written = (tmp_path / "usb" / rebuilt).read_bytes()
    assert written not in stored.values()
    header = read_header(written[:70])
    assert (header.uid, header.seq, header.kind) == (UID, 1, Kind.STATE)


def test_every_stored_package_is_written_beside_the_state(bench: Bench, tmp_path: Path) -> None:
    _three_keys(bench)
    stored = _stored(bench)
    assert _export(bench, tmp_path / "usb") == 0
    assert _names(tmp_path / "usb") == sorted([*stored, f"{UID}-00000003-state-rebuilt.veil"])
    for name, data in stored.items():
        assert (tmp_path / "usb" / name).read_bytes() == data


def test_the_export_changes_nothing_on_the_server(bench: Bench, tmp_path: Path) -> None:
    _three_keys(bench)
    before = _stored(bench)
    assert _export(bench, tmp_path / "usb") == 0
    assert _stored(bench) == before
    _report(bench, "a", "b", "c", "d")
    assert bench.core.store.package_bounds(bench.pairing.key_id, UID).last == 4


def test_a_member_on_the_first_key_walks_three_rotations(bench: Bench, tmp_path: Path) -> None:
    _three_keys(bench)
    bench.core = _rotate(bench)
    _report(bench, "a", "b", "c", "d")
    assert _export(bench, tmp_path / "usb") == 0
    assert _read(bench, tmp_path / "usb") == 0
    state = store.load(bench.state_dir)
    assert bench.last() == 4 and state.trusted_keys == [bench.core.sealer.public_key]


def test_a_member_on_the_middle_key_reads_the_whole_export(bench: Bench, tmp_path: Path) -> None:
    bench.subscribe(UID, "news")
    bench.subscribe(OTHER, "other")
    bench.world.collector.set("other", ("x", {"title": "X"}))
    _report(bench, "a")
    bench.core = _rotate(bench)
    _report(bench, "a", "b")
    assert _export(bench, tmp_path / "first", UID) == 0
    assert _read(bench, tmp_path / "first") == 0, "the member is now on the second key"
    bench.core = _rotate(bench)
    bench.world.collector.set("other", ("x", {"title": "X"}), ("y", {"title": "Y"}))
    bench.round()
    assert _export(bench, tmp_path / "second", OTHER) == 0
    assert _read(bench, tmp_path / "second") == 0
    assert bench.last(OTHER) == 2
    assert store.load(bench.state_dir).trusted_keys == [bench.core.sealer.public_key]


def test_a_member_on_the_last_key_gets_past_the_packages_of_all_the_older_ones(bench: Bench, tmp_path: Path) -> None:
    bench.subscribe(UID, "news")
    bench.subscribe(OTHER, "other")
    bench.world.collector.set("other", ("x", {"title": "X"}))
    _report(bench, "a")
    bench.core = _rotate(bench)
    bench.world.collector.set("other", ("x", {"title": "X"}), ("y", {"title": "Y"}))
    _report(bench, "a", "b")
    bench.core = _rotate(bench)
    _report(bench, "a", "b", "c")
    assert _export(bench, tmp_path / "first", UID) == 0
    assert _read(bench, tmp_path / "first") == 0
    assert store.load(bench.state_dir).trusted_keys == [bench.core.sealer.public_key]
    assert _export(bench, tmp_path / "second", OTHER) == 0
    assert _read(bench, tmp_path / "second") == 0
    assert bench.last(OTHER) == 2


def test_reading_a_folder_twice_files_nothing_more(bench: Bench, tmp_path: Path) -> None:
    _three_keys(bench)
    assert _export(bench, tmp_path / "usb") == 0
    assert _read(bench, tmp_path / "usb") == 0
    filed = bench.filed()
    assert _read(bench, tmp_path / "usb") == 0
    assert bench.filed() == filed and bench.last() == 3


def test_the_reports_go_on_after_the_state_of_an_export(bench: Bench, tmp_path: Path) -> None:
    _three_keys(bench)
    assert _export(bench, tmp_path / "usb") == 0
    assert _read(bench, tmp_path / "usb") == 0
    _report(bench, "a", "b", "c", "d")
    assert _export(bench, tmp_path / "next", UID, "--after", "3") == 0
    assert _read(bench, tmp_path / "next") == 0
    assert bench.last() == 4 and "00000004-delta" in bench.filed()


def test_successive_exports_into_one_folder_are_read_by_a_member_on_the_first_key(bench: Bench, tmp_path: Path) -> None:
    bench.subscribe()
    _report(bench, "a")
    bench.core = _rotate(bench)
    _report(bench, "a", "b")
    assert _export(bench, tmp_path / "usb") == 0
    bench.core = _rotate(bench)
    _report(bench, "a", "b", "c")
    assert _export(bench, tmp_path / "usb") == 0
    assert _read(bench, tmp_path / "usb") == 0
    assert bench.last() == 3


# --- M1 and M2: an export without a `state` ends cleanly -----------------------------------------------------------


@pytest.mark.parametrize(("lang", "message"), [("en", "No state could be made"), ("fr", "Aucun état n'a pu être")])
def test_a_revoked_pairing_is_exported_without_a_state(
    bench: Bench, tmp_path: Path, capsys: pytest.CaptureFixture[str], lang: str, message: str
) -> None:
    _two_reports(bench)
    stored = _stored(bench)
    bench.core = _rotate(bench)
    assert _admin(bench, "pairing", "revoke", bench.pairing.key_id) == 0
    capsys.readouterr()
    assert _export(bench, tmp_path / "usb", lang=lang) == 0
    assert message in capsys.readouterr().out
    assert _names(tmp_path / "usb") == sorted(stored)


def test_a_state_too_large_leaves_the_stored_packages_exported(
    bench: Bench, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _two_reports(bench)
    stored = _stored(bench)
    bench.core = _rotate(bench)

    def too_large(self: ProtocolSealer, secret: bytes, spec: Any) -> bytes:
        raise PackageTooLarge("state")

    monkeypatch.setattr(ProtocolSealer, "seal_package", too_large)
    assert _export(bench, tmp_path / "usb") == 0
    assert "No state could be made" in capsys.readouterr().out
    assert _names(tmp_path / "usb") == sorted(stored)


def test_a_purged_export_of_a_revoked_pairing_ends_cleanly(bench: Bench, tmp_path: Path) -> None:
    """The other way into the same code: no rotation, packages purged."""
    _two_reports(bench)
    bench.world.clock.advance(days=91)
    bench.round()
    assert _admin(bench, "pairing", "revoke", bench.pairing.key_id) == 0
    assert _export(bench, tmp_path / "usb") == 0
    assert _names(tmp_path / "usb") == []


# --- What the receiver now skips must not open a door --------------------------------------------------------------


def test_a_forged_state_alone_is_reported(bench: Bench, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    source = tmp_path / "usb"
    source.mkdir()
    forged = _sealed(bench, 1, Kind.STATE, key=SigningKey.generate())
    (source / f"{UID}-00000001-state-rebuilt.veil").write_bytes(forged)
    assert _read(bench, source) == 1
    assert "bad_signature" in capsys.readouterr().err and bench.filed() == []


def test_a_forged_statement_beside_a_real_package_gives_no_key_away(bench: Bench, tmp_path: Path) -> None:
    """A stranger signs for itself: the skip must not let its key in."""
    _two_reports(bench)
    trusted = store.load(bench.state_dir).trusted_keys
    stranger, successor = SigningKey.generate(), SigningKey.generate()
    rotation = make_rotation(stranger, successor.public_key, bench.world.clock.now())
    source = tmp_path / "usb"
    assert _export(bench, source) == 0
    forged = _forged(bench, 1, Kind.STATE, successor, rotation)
    (source / f"{UID}-00000001-state-rebuilt.veil").write_bytes(forged)
    assert _read(bench, source) == 0
    assert store.load(bench.state_dir).trusted_keys == trusted and bench.last() == 2


def test_the_key_given_up_does_not_come_back_through_a_skipped_package(bench: Bench, tmp_path: Path) -> None:
    """Protocol §6.3: the stolen key signs a statement for a key of the thief, beside a real `state`."""
    _two_reports(bench)
    assert bench.pull() == 0
    stolen = keys.load_signing_key(bench.world.app.config.state_dir)
    bench.core = _rotate(bench)
    _report(bench, "a", "b", "c")
    assert bench.pull() == 0
    adopted = store.load(bench.state_dir).trusted_keys
    thief = SigningKey.generate()
    rotation = make_rotation(stolen, thief.public_key, bench.world.clock.now())
    source = tmp_path / "usb"
    source.mkdir()
    (source / "1.veil").write_bytes(_forged(bench, 4, Kind.DELTA, thief, rotation))
    (source / "2.veil").write_bytes(_sealed(bench, 5, Kind.STATE))
    assert _read(bench, source) == 0
    assert store.load(bench.state_dir).trusted_keys == adopted and bench.last() == 5
    assert "00000004-delta" not in bench.filed()


def test_a_package_of_the_old_key_is_not_skipped_when_nothing_follows(
    bench: Bench, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _two_reports(bench)
    assert bench.pull() == 0
    stolen = keys.load_signing_key(bench.world.app.config.state_dir)
    bench.core = _rotate(bench)
    _report(bench, "a", "b", "c")
    assert bench.pull() == 0
    source = tmp_path / "usb"
    source.mkdir()
    (source / "1.veil").write_bytes(_sealed(bench, 4, Kind.DELTA, key=stolen))
    (source / "2.veil").write_bytes(_sealed(bench, 4, Kind.DELTA, key=stolen))
    capsys.readouterr()
    assert _read(bench, source) == 1
    assert "bad_signature" in capsys.readouterr().err and bench.last() == 3


# --- Remaining gaps -------------------------------------------------------------------------------------------------


def _absent_member(bench: Bench) -> None:
    """A member at number 1 on key A; package 2 is purged; packages 3 and 4 carry A to B, then B to C."""
    bench.subscribe()
    _report(bench, "a")
    assert bench.pull() == 0
    _report(bench, "a", "b")
    bench.world.clock.advance(days=60)
    bench.core = _rotate(bench)
    _report(bench, "a", "b", "c")
    bench.world.clock.advance(days=20)
    bench.core = _rotate(bench)
    _report(bench, "a", "b", "c", "d")
    bench.world.clock.advance(days=15)
    bench.round()
    assert bench.core.store.package_bounds(bench.pairing.key_id, UID).purged_through == 2


@pytest.mark.xfail(strict=True, reason="accepted limit (cahier §10, protocol §6.3): purged gap and two rotations")
@pytest.mark.parametrize("after", ["0", "1", "2", "3"])
def test_a_member_back_after_a_purge_follows_two_rotations_from_a_folder(
    bench: Bench, tmp_path: Path, after: str
) -> None:
    """Blocking. Cahier §10, ES-05, protocol §6.3: both statements are in their 90 days and in the folder.

    The reader passes over package 3, which holds the statement from A to B, because a later `state` "covers" it; that
    `state` only vouches for C. No selection of packages gets the member through.
    """
    _absent_member(bench)
    assert _export(bench, tmp_path / "usb", UID, "--after", after) == 0
    assert _read(bench, tmp_path / "usb") == 0
    assert bench.last() == 4


def test_the_statement_the_member_needs_is_in_the_folder(bench: Bench, tmp_path: Path) -> None:
    """What makes the previous test a defect of the reader: the export did its part."""
    _absent_member(bench)
    assert _export(bench, tmp_path / "usb", UID, "--after", "1") == 0
    assert _names(tmp_path / "usb") == [
        f"{UID}-00000003-delta.veil",
        f"{UID}-00000004-delta.veil",
        f"{UID}-00000004-state-rebuilt.veil",
    ]


@pytest.mark.xfail(strict=True, reason="accepted limit (cahier §10, protocol §6.3): purged gap and two rotations")
def test_a_member_back_after_a_purge_follows_two_rotations_over_http(bench: Bench) -> None:
    """Blocking, the same defect: the `state` asked for first is signed by a key the member cannot reach yet."""
    _absent_member(bench)
    bench.transport.api = Api(bench.core, limiter=RateLimiter(limit=100_000))
    assert bench.pull() == 0
    assert bench.last() == 4


def test_a_member_back_after_a_purge_follows_one_rotation_from_a_folder(bench: Bench, tmp_path: Path) -> None:
    """The bound of the defect: with one rotation the `state` carries the statement the member needs."""
    bench.subscribe()
    _report(bench, "a")
    assert bench.pull() == 0
    _report(bench, "a", "b")
    bench.world.clock.advance(days=60)
    bench.core = _rotate(bench)
    _report(bench, "a", "b", "c")
    bench.world.clock.advance(days=35)
    bench.round()
    assert bench.core.store.package_bounds(bench.pairing.key_id, UID).purged_through == 2
    assert _export(bench, tmp_path / "usb") == 0
    assert _read(bench, tmp_path / "usb") == 0
    assert bench.last() == 3


@pytest.mark.xfail(strict=True, reason="out of spec: a package carries one statement, the last rotation's only")
def test_two_rotations_without_a_package_between_them_are_followed(bench: Bench, tmp_path: Path) -> None:
    """ES-05 keeps a statement on each package for 90 days; a quiet subscription never carried the first one."""
    bench.subscribe()
    _report(bench, "a")
    bench.core = _rotate(bench)
    bench.core = _rotate(bench)
    _report(bench, "a", "b")
    assert _export(bench, tmp_path / "usb") == 0
    assert _read(bench, tmp_path / "usb") == 0
    assert bench.last() == 2


@pytest.mark.xfail(strict=True, reason="out of spec: a forged package covered by a later `state` is dropped silently")
def test_a_forged_package_is_reported_even_when_a_state_covers_it(
    bench: Bench, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Nothing forged is used, but the member is not told, while the same file is refused over HTTP."""
    source = tmp_path / "usb"
    source.mkdir()
    (source / "1.veil").write_bytes(_sealed(bench, 1, Kind.STATE, key=SigningKey.generate()))
    (source / "2.veil").write_bytes(_sealed(bench, 2, Kind.STATE))
    code = _read(bench, source)
    assert code == 1 or "bad_signature" in capsys.readouterr().err


@pytest.mark.xfail(strict=True, reason="out of spec: the `state` wins over a `delta` of its number the member can read")
def test_a_member_able_to_read_the_last_delta_still_gets_it(bench: Bench, tmp_path: Path) -> None:
    """The changes of the last report (what is gone, what changed) are only in that `delta`."""
    _two_reports(bench)
    assert bench.pull() == 0
    bench.core = _rotate(bench)
    _report(bench, "a")
    assert _export(bench, tmp_path / "usb") == 0
    assert _read(bench, tmp_path / "usb") == 0
    assert "00000003-delta" in bench.filed()


def _window_over(bench: Bench, tmp_path: Path) -> None:
    """A member on the new key; the statement has just expired, OTHER still has a package of the old key."""
    bench.subscribe(UID, "news")
    bench.subscribe(OTHER, "other")
    bench.world.collector.set("other", ("x", {"title": "X"}))
    _report(bench, "a")
    bench.core = _rotate(bench)
    _report(bench, "a", "b")
    assert _export(bench, tmp_path / "first", UID) == 0
    assert _read(bench, tmp_path / "first") == 0
    bench.world.clock.advance(days=91)


@pytest.mark.xfail(strict=True, reason="minor: from the end of the 90 days to the next round, no `state` is written")
def test_an_export_just_after_the_window_with_packages_not_yet_purged(bench: Bench, tmp_path: Path) -> None:
    _window_over(bench, tmp_path)
    assert _export(bench, tmp_path / "second", OTHER) == 0
    assert _read(bench, tmp_path / "second") == 0
    assert bench.last(OTHER) == 1


def test_the_next_round_ends_that_window(bench: Bench, tmp_path: Path) -> None:
    """Why the previous case is minor: the purge of the next round brings the `state` back."""
    _window_over(bench, tmp_path)
    bench.round()
    assert _export(bench, tmp_path / "second", OTHER) == 0
    assert _read(bench, tmp_path / "second") == 0
    assert bench.last(OTHER) == 1
