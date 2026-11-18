# SPDX-License-Identifier: EUPL-1.2
"""Second pass on batch G4: the corrections of B1 (export after a rotation) and B2 (addresses), and their effects."""

from __future__ import annotations

import json
from collections.abc import Iterator
from dataclasses import replace
from datetime import UTC, datetime, timedelta
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
from veilleur.core.domain.model import Change, CollectedItem, ItemChange, Kind
from veilleur.core.ports.plugins import Plugins, Renderer, ReportView
from veilleur.core.ports.sealer import PackageTooLarge
from veilleur.core.services import pairing
from veilleur_protocol import PairingCode
from veilleur_protocol.envelope import Kind as EnvelopeKind
from veilleur_receive import store

NOW = datetime(2026, 11, 17, 6, 0, tzinfo=UTC)


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


def _admin(bench: Bench, *argv: str) -> int:
    state_dir = str(bench.world.app.config.state_dir)
    return server_cli.main(["--lang", "en", "--state-dir", state_dir, *argv], opener=lambda config: bench.world.app)


def _export(bench: Bench, target: Path, uid: str = UID, *options: str) -> int:
    return _admin(bench, "export", uid, "--folder", str(target), *options)


def _read(bench: Bench, source: Path) -> int:
    return bench.receive("pull", "--folder", str(bench.folder), "--from", str(source))


def _rotate_by_command(bench: Bench) -> None:
    """`veilleur key rotate`, then the sealer a new process would load."""
    assert _admin(bench, "key", "rotate") == 0
    state_dir, now = bench.world.app.config.state_dir, bench.world.clock.now()
    signing = keys.load_signing_key(state_dir)
    bench.core = replace(bench.core, sealer=ProtocolSealer(signing, keys.current_rotation(state_dir, signing, now)))


def _view(url: str) -> ReportView:
    item = ItemChange("k", Change.NEW, "0" * 64, {"title": "T"}, NOW, url)
    return ReportView("ab" * 16, 7, Kind.DELTA, NOW, NOW - timedelta(days=1), NOW, (item,), ())


def _md(url: str) -> str:
    return MarkdownRenderer().render(_view(url), "en")["report.md"].decode("utf-8")


def _html(url: str) -> str:
    return HtmlRenderer().render(_view(url), "en")["report.html"].decode("utf-8")


# --- B1: delivery by folder after a rotation ----------------------------------------------------------------------


def test_the_real_command_takes_a_member_on_the_old_key_past_the_rotation(bench: Bench, tmp_path: Path) -> None:
    """ES-05 through `veilleur key rotate`, then a report that follows the `state` of the export."""
    _two_reports(bench)
    old_key = bench.core.sealer.public_key
    _rotate_by_command(bench)
    assert _export(bench, tmp_path / "usb1") == 0
    assert sorted(path.name for path in (tmp_path / "usb1").iterdir()) == [
        f"{UID}-00000001-state.veil",
        f"{UID}-00000002-delta.veil",
        f"{UID}-00000002-state-rebuilt.veil",
    ]
    assert _read(bench, tmp_path / "usb1") == 0
    state = store.load(bench.state_dir)
    assert state.rotated and old_key not in state.trusted_keys and bench.last() == 2

    bench.world.collector.set("news", ("z", {"title": "Z"}))
    bench.round()
    assert _export(bench, tmp_path / "usb2", UID, "--after", "2") == 0
    assert _read(bench, tmp_path / "usb2") == 0
    assert bench.filed() == ["00000001-state", "00000002-state", "00000003-delta"]


def test_a_member_already_up_to_date_loses_nothing_to_the_replacing_state(bench: Bench, tmp_path: Path) -> None:
    _two_reports(bench)
    assert bench.pull() == 0
    _rotate_by_command(bench)
    assert _export(bench, tmp_path / "usb") == 0
    assert _read(bench, tmp_path / "usb") == 0
    assert bench.filed() == ["00000001-state", "00000002-delta"] and bench.last() == 2


def test_a_new_export_into_the_folder_of_an_old_one_gets_past_the_rotation(bench: Bench, tmp_path: Path) -> None:
    """The old packages are still in the folder: the `state` of the new export must win over them."""
    bench.world.collector.set("news", ("a", {"title": "A"}))
    bench.world.collector.set("other", ("x", {"title": "X"}))
    bench.subscribe(UID, "news")
    bench.subscribe(OTHER, "other")
    bench.round()
    bench.world.collector.set("other", ("x", {"title": "X"}), ("y", {"title": "Y"}))
    bench.round()
    usb = tmp_path / "usb"
    assert _export(bench, usb, OTHER) == 0
    bench.core = _rotate(bench)
    bench.world.collector.set("news", ("a", {"title": "A"}), ("b", {"title": "B"}))
    bench.round()
    assert _export(bench, tmp_path / "first", UID) == 0
    assert _read(bench, tmp_path / "first") == 0
    assert _read(bench, usb) == 1, "the packages of the old key alone are refused"
    assert _export(bench, usb, OTHER) == 0
    assert _read(bench, usb) == 0
    assert bench.filed(OTHER) == ["00000002-state"]


def test_a_forged_later_state_does_not_get_a_package_of_the_old_key_accepted(
    bench: Bench, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The skip relies on an unverified header: the `state` it counts on must still be checked and reported."""
    _two_reports(bench)
    assert bench.pull() == 0
    old = keys.load_signing_key(bench.world.app.config.state_dir)
    bench.core = _rotate(bench)
    bench.world.collector.set("news", ("z", {"title": "Z"}))
    bench.round()
    assert bench.pull() == 0
    source = tmp_path / "usb"
    source.mkdir()
    (source / "1.veil").write_bytes(_sealed(bench, 1, EnvelopeKind.STATE, uid=OTHER, key=old))
    (source / "2.veil").write_bytes(_sealed(bench, 9, EnvelopeKind.STATE, uid=OTHER, key=old))
    capsys.readouterr()
    assert _read(bench, source) == 1
    assert "bad_signature" in capsys.readouterr().err
    assert bench.last(OTHER) == 0 and bench.filed(OTHER) == []


def test_an_export_of_a_revoked_pairing_after_a_rotation_ends_cleanly(bench: Bench, tmp_path: Path) -> None:
    """Without a rotation the same command writes the packages: so it does when no `state` can be built."""
    _two_reports(bench)
    bench.core = _rotate(bench)
    assert _admin(bench, "pairing", "revoke", bench.pairing.key_id) == 0
    assert _export(bench, tmp_path / "usb") == 0
    assert len(list((tmp_path / "usb").iterdir())) == 2


def test_an_export_whose_state_is_too_large_ends_cleanly(
    bench: Bench, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Each `delta` fits, the sum of them may not: the stored packages are still written."""
    _two_reports(bench)
    bench.core = _rotate(bench)

    def too_large(self: ProtocolSealer, secret: bytes, spec: Any) -> bytes:
        raise PackageTooLarge("state")

    monkeypatch.setattr(ProtocolSealer, "seal_package", too_large)
    assert _export(bench, tmp_path / "usb") == 0
    assert len(list((tmp_path / "usb").iterdir())) == 2


@pytest.mark.xfail(strict=True, reason="minor: a package is judged by its date, not by the key that signed it")
def test_a_package_signed_by_the_old_key_just_after_the_rotation_is_replaced_too(bench: Bench, tmp_path: Path) -> None:
    """A round already running when `key rotate` is launched keeps the key it loaded when it started."""
    bench.world.collector.set("news", ("a", {"title": "A"}))
    bench.world.collector.set("other", ("x", {"title": "X"}))
    bench.subscribe(UID, "news")
    bench.subscribe(OTHER, "other")
    bench.round()
    assert bench.pull() == 0
    running = bench.core  # the round in progress, on the old key
    rotated = _rotate(bench)
    bench.world.collector.set("other", ("x", {"title": "X"}), ("y", {"title": "Y"}))
    bench.round()  # package 2 of OTHER: dated after the rotation, signed by the old key
    assert bench.core is running
    bench.core = rotated
    bench.world.collector.set("news", ("a", {"title": "A"}), ("b", {"title": "B"}))
    bench.round()
    assert _export(bench, tmp_path / "first", UID, "--after", "1") == 0
    assert _read(bench, tmp_path / "first") == 0, "the new key is adopted"
    assert _export(bench, tmp_path / "second", OTHER, "--after", "1") == 0
    assert _read(bench, tmp_path / "second") == 0
    assert bench.last(OTHER) == 2


def test_a_full_export_recovers_from_a_package_signed_by_the_old_key_after_the_rotation(
    bench: Bench, tmp_path: Path
) -> None:
    """The way out of the previous case: without `--after`, the older packages make the export write a `state`."""
    bench.world.collector.set("news", ("a", {"title": "A"}))
    bench.world.collector.set("other", ("x", {"title": "X"}))
    bench.subscribe(UID, "news")
    bench.subscribe(OTHER, "other")
    bench.round()
    assert bench.pull() == 0
    rotated = _rotate(bench)
    bench.world.collector.set("other", ("x", {"title": "X"}), ("y", {"title": "Y"}))
    bench.round()  # package 2 of OTHER: dated after the rotation, signed by the old key
    bench.core = rotated
    bench.world.collector.set("news", ("a", {"title": "A"}), ("b", {"title": "B"}))
    bench.round()
    assert _export(bench, tmp_path / "first", UID, "--after", "1") == 0
    assert _read(bench, tmp_path / "first") == 0, "the new key is adopted"
    assert _export(bench, tmp_path / "second", OTHER) == 0
    assert _read(bench, tmp_path / "second") == 0
    assert bench.last(OTHER) == 2


def test_the_packages_a_former_export_wrote_let_a_member_follow_two_rotations(bench: Bench, tmp_path: Path) -> None:
    """What the export wrote before the correction: the stored packages, each with its own statement."""
    bench.world.collector.set("news", ("a", {"title": "A"}))
    bench.subscribe()
    bench.round()
    bench.core = _rotate(bench)
    bench.world.collector.set("news", ("a", {"title": "A"}), ("b", {"title": "B"}))
    bench.round()
    bench.core = _rotate(bench)
    bench.world.collector.set("news", ("a", {"title": "A"}), ("b", {"title": "B"}), ("c", {"title": "C"}))
    bench.round()
    source = tmp_path / "usb"
    source.mkdir()
    for info in bench.world.app.store.list_packages(bench.pairing.key_id, UID, 0):
        data = bench.world.app.store.get_package(bench.pairing.key_id, UID, info.seq)
        assert data is not None
        (source / f"{UID}-{info.seq:08d}-{info.kind.value}.veil").write_bytes(data)
    assert _read(bench, source) == 0
    assert bench.last() == 3


@pytest.mark.parametrize("after", [0, 1, 2])
def test_an_export_after_the_number_of_a_member_takes_it_past_two_rotations(
    bench: Bench, tmp_path: Path, after: int
) -> None:
    """`--after` names what the member holds: from each number of the chain, the rest of the chain is in the folder."""
    bench.world.collector.set("news", ("a", {"title": "A"}))
    bench.subscribe()
    bench.round()
    bench.core = _rotate(bench)
    bench.world.collector.set("news", ("a", {"title": "A"}), ("b", {"title": "B"}))
    bench.round()
    if after:
        assert _export(bench, tmp_path / "held", UID) == 0
        for path in sorted((tmp_path / "held").iterdir()):
            if int(path.name.split("-")[1]) > after or "rebuilt" in path.name:
                path.unlink()
        assert _read(bench, tmp_path / "held") == 0
        assert bench.last() == after
    bench.core = _rotate(bench)
    bench.world.collector.set("news", ("a", {"title": "A"}), ("b", {"title": "B"}), ("c", {"title": "C"}))
    bench.round()
    assert _export(bench, tmp_path / "usb", UID, "--after", str(after)) == 0
    assert _read(bench, tmp_path / "usb") == 0
    assert bench.last() == 3


def test_two_rotations_are_followed_from_a_folder(bench: Bench, tmp_path: Path) -> None:
    """ES-05: each package carries its statement, so a member on the first key can walk the chain, as over HTTP."""
    bench.world.collector.set("news", ("a", {"title": "A"}))
    bench.subscribe()
    bench.round()
    bench.core = _rotate(bench)
    bench.world.collector.set("news", ("a", {"title": "A"}), ("b", {"title": "B"}))
    bench.round()
    bench.core = _rotate(bench)
    bench.world.collector.set("news", ("a", {"title": "A"}), ("b", {"title": "B"}), ("c", {"title": "C"}))
    bench.round()
    assert _export(bench, tmp_path / "usb") == 0
    assert _read(bench, tmp_path / "usb") == 0
    assert bench.last() == 3


def test_two_rotations_are_followed_over_http(bench: Bench) -> None:
    """The reference for the previous test: the same history, read over HTTP."""
    bench.world.collector.set("news", ("a", {"title": "A"}))
    bench.subscribe()
    bench.round()
    bench.core = _rotate(bench)
    bench.world.collector.set("news", ("a", {"title": "A"}), ("b", {"title": "B"}))
    bench.round()
    bench.core = _rotate(bench)
    bench.world.collector.set("news", ("a", {"title": "A"}), ("b", {"title": "B"}), ("c", {"title": "C"}))
    bench.round()
    bench.transport.api = Api(bench.core, limiter=RateLimiter(limit=100_000))
    assert bench.pull() == 0
    assert bench.last() == 3


# --- B2: addresses ------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "mark",
    ["\u202a", "\u202b", "\u202c", "\u202d", "\u202e", "\u2066", "\u2067", "\u2068", "\u2069", "\u200e", "\u200f"],
)
def test_an_address_with_a_direction_mark_is_shown_clean_and_not_linked(mark: str) -> None:
    url = f"https://example.org/{mark}gnp.exe"
    assert mark not in _md(url) and mark not in _html(url)
    assert "<a " not in _html(url) and "](<" not in _md(url)
    assert "gnp.exe" in _html(url)


@pytest.mark.parametrize("mark", ["\x00", "\x01", "\x1b", "\x7f", "\x85", "\x90", "\x9b", "\ud800"])
def test_an_address_with_a_control_character_or_a_lone_surrogate_is_rendered(mark: str) -> None:
    url = f"https://example.org/{mark}a"
    assert mark not in _md(url) and mark not in _html(url)
    assert "<a " not in _html(url) and "](<" not in _md(url)


@pytest.mark.parametrize("url", ["https://example.org/a?b=c&d=e#f", "http://example.net/é/ü", "HTTPS://EXAMPLE.ORG/"])
def test_a_clean_address_stays_a_link(url: str) -> None:
    assert "<a " in _html(url) and "](<" in _md(url)


@pytest.mark.xfail(strict=True, reason="minor: U+061C (arabic letter mark) stays in an address, which stays a link")
def test_an_address_with_the_arabic_letter_mark_is_not_a_link() -> None:
    url = "https://example.org/\u061cgnp.exe"
    assert "\u061c" not in _html(url) and "\u061c" not in _md(url)


def test_only_the_renderings_of_a_real_package_are_cleaned(bench: Bench) -> None:
    """`items.jsonl` keeps the authoritative value (EF-43): only the renderings lose the character."""
    url = "https://example.org/\u202egnp.exe"
    bench.world.collector.items["news"] = [CollectedItem({"title": "T"}, key="k", url=url)]
    bench.subscribe(renderings=["markdown", "html"])
    bench.round()
    assert bench.pull() == 0
    report = bench.folder / UID / "00000001-state"
    assert "\u202e" not in (report / "report.html").read_text("utf-8")
    assert "\u202e" not in (report / "report.md").read_text("utf-8")
    assert json.loads((report / "items.jsonl").read_text("utf-8"))["url"] == url
