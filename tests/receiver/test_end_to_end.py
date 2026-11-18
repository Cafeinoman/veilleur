# SPDX-License-Identifier: EUPL-1.2
"""Milestone G4: from the server to the reference receiver, through the WSGI application and through a folder."""

from __future__ import annotations

import io
import json
import stat
from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

import pytest

from tests.server.fakes import World, make_world
from veilleur.adapters import keys
from veilleur.adapters.renderers import HtmlRenderer, MarkdownRenderer
from veilleur.adapters.sealer import ProtocolSealer
from veilleur.apps.server import cli as server_cli
from veilleur.apps.server.config import Config
from veilleur.apps.server.context import App
from veilleur.apps.server.wsgi import Api, RateLimiter
from veilleur.core.domain.model import Pairing
from veilleur.core.ports.plugins import Plugins, Renderer
from veilleur.core.services import jobs, pairing, round, subscriptions
from veilleur.core.services.context import Core
from veilleur_protocol import PairingCode, seal_package
from veilleur_protocol.envelope import Kind
from veilleur_protocol.package import PackageContent
from veilleur_protocol.signing import SigningKey
from veilleur_receive import cli, store
from veilleur_receive.transport import Reply

UID = "0123456789abcdef0123456789abcdef"
OTHER = "fedcba9876543210fedcba9876543210"


@dataclass
class WsgiTransport:
    """The receiver's network: the server's WSGI application, called directly. Answers can be replaced."""

    api: Api
    requests: list[str] = field(default_factory=list)
    replies: dict[str, Reply] = field(default_factory=dict)

    def get(self, target: str, headers: Mapping[str, str]) -> Reply:
        self.requests.append(target)
        if target in self.replies:
            return self.replies[target]
        environ: dict[str, Any] = {
            "REQUEST_METHOD": "GET",
            "REQUEST_URI": target,
            "CONTENT_LENGTH": "0",
            "wsgi.input": io.BytesIO(),
            "HTTP_AUTHORIZATION": headers["Authorization"],
            "HTTP_X_VEILLEUR_DATE": headers["X-Veilleur-Date"],
        }
        status: list[str] = []
        body = b"".join(self.api(environ, lambda s, h: status.append(s)))
        return Reply(int(status[0].split()[0]), body)


@dataclass
class Bench:
    world: World
    core: Core
    pairing: Pairing
    code: str
    transport: WsgiTransport
    state_dir: Path
    folder: Path

    def receive(self, *argv: str) -> int:
        return cli.main(
            ["--lang", "en", "--state-dir", str(self.state_dir), *argv],
            transport=self.transport,
            clock=self.world.clock.now,
        )

    def pull(self) -> int:
        return self.receive("pull", "--folder", str(self.folder))

    def subscribe(self, uid: str = UID, topic: str = "news", **document: Any) -> None:
        spec = {"collector": "fake", "params": {"topic": topic}, "frequency": "every_round", **document}
        subscriptions.put_subscription(self.core, self.pairing.key_id, uid, 0, spec)

    def round(self) -> None:
        self.world.clock.advance(hours=1)
        round.run_round(self.core)
        jobs.run_pending(self.core)

    def filed(self, uid: str = UID) -> list[str]:
        base = self.folder / uid
        return sorted(p.name for p in base.iterdir()) if base.exists() else []

    def last(self, uid: str = UID) -> int:
        return store.load(self.state_dir).last.get(uid, 0)


def _pair(bench: Bench, monkeypatch: pytest.MonkeyPatch, code: str | None = None) -> int:
    monkeypatch.setattr("sys.stdin", io.StringIO((code or bench.code) + "\n"))
    return bench.receive("pair")


@pytest.fixture
def bench(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Bench]:
    world = make_world(tmp_path / "server")
    plugins = world.app.core.plugins
    renderers: dict[str, Renderer] = {"markdown": MarkdownRenderer(), "html": HtmlRenderer()}
    core = replace(world.app.core, plugins=Plugins(plugins.collectors, plugins.filters, renderers))
    created = pairing.create_pairing(core, "desk 1")
    code = PairingCode("https://veille.example.org", created.key_id, created.secret, core.sealer.public_key).encode()
    transport = WsgiTransport(Api(core, limiter=RateLimiter(limit=100_000)))
    result = Bench(world, core, created, code, transport, tmp_path / "receiver", tmp_path / "reports")
    assert _pair(result, monkeypatch) == 0
    yield result
    world.app.close()


def test_over_http_from_the_server_to_filed_reports(bench: Bench, capsys: pytest.CaptureFixture[str]) -> None:
    """The milestone: pair, pull, check, file; then only what is new."""
    bench.world.collector.set("news", ("a", {"title": "Élément A"}))
    bench.subscribe(language="fr", renderings=["markdown", "html"])
    bench.round()
    capsys.readouterr()
    assert bench.pull() == 0
    assert "1 report filed" in capsys.readouterr().out
    assert bench.filed() == ["00000001-state"]
    report = bench.folder / UID / "00000001-state"
    assert sorted(p.name for p in report.iterdir()) == ["items.jsonl", "manifest.json", "report.html", "report.md"]
    assert json.loads((report / "items.jsonl").read_text("utf-8"))["key"] == "a"
    assert json.loads((report / "manifest.json").read_text("utf-8"))["uid"] == UID
    assert "Rapport 1" in (report / "report.md").read_text("utf-8")
    assert "Élément A" in (report / "report.html").read_text("utf-8")

    bench.world.collector.set("news", ("a", {"title": "Élément A"}), ("b", {"title": "B"}))
    bench.round()
    assert bench.pull() == 0
    assert bench.filed() == ["00000001-state", "00000002-delta"]
    assert bench.last() == 2
    bench.transport.requests.clear()
    assert bench.pull() == 0
    assert not [r for r in bench.transport.requests if "/reports/" in r], "nothing is fetched twice"


def test_through_a_folder_written_by_the_export_command(
    bench: Bench, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The milestone, by folder (EF-51): `veilleur export` on one side, `pull --from` on the other."""
    bench.world.collector.set("news", ("a", {"title": "A"}))
    bench.subscribe()
    bench.round()
    bench.world.collector.set("news", ("a", {"title": "A"}), ("b", {"title": "B"}))
    bench.round()
    export = tmp_path / "usb"

    def opener(config: Config) -> App:
        return bench.world.app

    monkeypatch.setattr(bench.world.app.store, "close", lambda: None)
    argv = ["--lang", "en", "--state-dir", str(tmp_path / "server"), "export", UID, "--folder", str(export)]
    assert server_cli.main(argv, opener=opener) == 0
    assert len(list(export.iterdir())) == 2
    bench.transport.requests.clear()
    assert bench.receive("pull", "--folder", str(bench.folder), "--from", str(export)) == 0
    assert bench.transport.requests == [], "reading a folder uses no network"
    assert bench.filed() == ["00000001-state", "00000002-delta"]
    assert bench.receive("pull", "--folder", str(bench.folder), "--from", str(export)) == 0
    assert "0 reports filed" in capsys.readouterr().out.splitlines()[-1]


def _sealed(bench: Bench, seq: int, kind: Kind, uid: str = UID, key: SigningKey | None = None) -> bytes:
    moment = bench.world.clock.now()
    content = PackageContent(uid, seq, kind, moment, moment, None, b"")
    return seal_package(bench.pairing.secret, key or _server_key(bench), content)


def _server_key(bench: Bench) -> SigningKey:
    return keys.load_signing_key(bench.world.app.config.state_dir)


def _export(folder: Path, name: str, data: bytes) -> None:
    folder.mkdir(exist_ok=True)
    (folder / name).write_bytes(data)


def test_a_folder_with_a_missing_package_stops_at_the_gap(
    bench: Bench, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    source = tmp_path / "usb"
    _export(source, "1.veil", _sealed(bench, 1, Kind.STATE))
    _export(source, "3.veil", _sealed(bench, 3, Kind.DELTA))
    assert bench.receive("pull", "--folder", str(bench.folder), "--from", str(source)) == 1
    assert bench.filed() == ["00000001-state"] and bench.last() == 1
    assert "missing_package" in capsys.readouterr().err


def test_a_state_in_a_folder_covers_the_gap_before_it(bench: Bench, tmp_path: Path) -> None:
    source = tmp_path / "usb"
    _export(source, "2.veil", _sealed(bench, 2, Kind.DELTA))
    _export(source, "5.veil", _sealed(bench, 5, Kind.STATE))
    _export(source, "6.veil", _sealed(bench, 6, Kind.DELTA))
    assert bench.receive("pull", "--folder", str(bench.folder), "--from", str(source)) == 0
    assert bench.filed() == ["00000005-state", "00000006-delta"] and bench.last() == 6


def test_a_folder_never_goes_back(bench: Bench, tmp_path: Path) -> None:
    source = tmp_path / "usb"
    _export(source, "4.veil", _sealed(bench, 4, Kind.STATE))
    assert bench.receive("pull", "--folder", str(bench.folder), "--from", str(source)) == 0
    (source / "4.veil").unlink()
    _export(source, "2.veil", _sealed(bench, 2, Kind.STATE))
    assert bench.receive("pull", "--folder", str(bench.folder), "--from", str(source)) == 0
    assert bench.filed() == ["00000004-state"] and bench.last() == 4


def test_a_folder_with_altered_or_foreign_files_is_refused(
    bench: Bench, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    source = tmp_path / "usb"
    altered = bytearray(_sealed(bench, 1, Kind.STATE))
    altered[-1] ^= 1
    _export(source, "altered.veil", bytes(altered))
    _export(source, "garbage.veil", b"not a package")
    moment = bench.world.clock.now()
    content = PackageContent(OTHER, 1, Kind.STATE, moment, moment, None, b"")
    foreign = seal_package(bytes(32), _server_key(bench), content)
    _export(source, "foreign.veil", foreign)
    _export(source, "ignored.txt", b"anything")
    assert bench.receive("pull", "--folder", str(bench.folder), "--from", str(source)) == 1
    err = capsys.readouterr().err
    assert "decryption_failed" in err and "bad_envelope" in err and "garbage.veil" in err
    assert bench.filed() == [] and bench.filed(OTHER) == [] and bench.last() == 0


def test_a_package_signed_by_an_unknown_key_is_refused(
    bench: Bench, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    source = tmp_path / "usb"
    _export(source, "1.veil", _sealed(bench, 1, Kind.STATE, key=SigningKey.generate()))
    assert bench.receive("pull", "--folder", str(bench.folder), "--from", str(source)) == 1
    assert "bad_signature" in capsys.readouterr().err and bench.filed() == []


def test_a_history_file_is_not_filed(bench: Bench, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    source = tmp_path / "usb"
    _export(source, "1.veil", _sealed(bench, 1, Kind.HISTORY))
    assert bench.receive("pull", "--folder", str(bench.folder), "--from", str(source)) == 1
    assert "kind_mismatch" in capsys.readouterr().err and bench.filed() == []


def test_a_missing_source_folder_is_an_error(bench: Bench, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert bench.receive("pull", "--folder", str(bench.folder), "--from", str(tmp_path / "nowhere")) == 1
    assert "does not exist" in capsys.readouterr().err


def _two_reports(bench: Bench) -> None:
    bench.world.collector.set("news", ("a", {"title": "A"}))
    bench.subscribe()
    bench.round()
    bench.world.collector.set("news", ("a", {"title": "A"}), ("b", {"title": "B"}))
    bench.round()


def test_purged_packages_are_replaced_by_a_state(bench: Bench) -> None:
    _two_reports(bench)
    bench.world.clock.advance(days=91)
    bench.round()
    bench.world.collector.set("news", ("a", {"title": "A"}), ("c", {"title": "C"}))
    bench.round()
    assert bench.pull() == 0
    names = bench.filed()
    assert any(name.endswith("-state") for name in names) and bench.last() >= 2


def test_a_package_answered_410_is_replaced_by_a_state(bench: Bench) -> None:
    _two_reports(bench)
    bench.transport.replies[f"/v1/subscriptions/{UID}/reports/1"] = Reply(410, b'{"code":"purged"}')
    assert bench.pull() == 0
    assert bench.filed() == ["00000002-state"] and bench.last() == 2


def test_a_state_still_in_preparation_is_retried_later(bench: Bench, capsys: pytest.CaptureFixture[str]) -> None:
    _two_reports(bench)
    bench.transport.replies[f"/v1/subscriptions/{UID}/reports/1"] = Reply(410)
    bench.transport.replies[f"/v1/subscriptions/{UID}/state"] = Reply(202)
    assert bench.pull() == 0
    assert "pull again later" in capsys.readouterr().out and bench.last() == 0


def test_a_new_subscription_without_report_is_nothing_to_do(bench: Bench) -> None:
    bench.subscribe()
    assert bench.pull() == 0 and bench.filed() == []


def test_an_altered_package_stops_its_subscription_and_keeps_what_came_before(
    bench: Bench, capsys: pytest.CaptureFixture[str]
) -> None:
    _two_reports(bench)
    target = f"/v1/subscriptions/{UID}/reports/2"
    bench.transport.replies[target] = Reply(200, b"tampered")
    assert bench.pull() == 1
    assert "listing_mismatch" in capsys.readouterr().err
    assert bench.filed() == ["00000001-state"] and bench.last() == 1
    del bench.transport.replies[target]
    assert bench.pull() == 0 and bench.last() == 2


def test_a_failing_subscription_does_not_stop_the_others(bench: Bench) -> None:
    bench.world.collector.set("news", ("a", {"title": "A"}))
    bench.world.collector.set("other", ("b", {"title": "B"}))
    bench.subscribe()
    bench.subscribe(OTHER, "other")
    bench.round()
    bench.transport.replies[f"/v1/subscriptions/{UID}/reports/1"] = Reply(500, b"{}")
    assert bench.pull() == 1
    assert bench.filed(OTHER) == ["00000001-state"] and bench.filed() == []


def test_a_server_that_went_back_is_reported(bench: Bench, capsys: pytest.CaptureFixture[str]) -> None:
    _two_reports(bench)
    assert bench.pull() == 0
    body = json.dumps({"packages": [], "oldest": None, "last": 1}).encode()
    bench.transport.replies[f"/v1/subscriptions/{UID}/reports?after=2"] = Reply(200, body)
    assert bench.pull() == 1
    assert "server_behind" in capsys.readouterr().err and bench.last() == 2


@pytest.mark.parametrize(
    "body",
    [
        b"not json",
        b"[]",
        b'{"subscriptions": [{"uid": "../../outside"}]}',
        b'{"subscriptions": [{"uid": "0123456789ABCDEF0123456789ABCDEF"}]}',
        b'{"subscriptions": [{"uid": 3}]}',
    ],
)
def test_a_malformed_list_of_subscriptions_is_refused(
    bench: Bench, body: bytes, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    bench.transport.replies["/v1/subscriptions"] = Reply(200, body)
    assert bench.pull() == 1
    assert "bad_response" in capsys.readouterr().err
    assert not (tmp_path / "outside").exists() and not bench.folder.exists()


@pytest.mark.parametrize(
    "body",
    [
        b"not json",
        b"{}",
        b'{"packages": [{"seq": -1, "size": 1, "sha256": "x"}], "oldest": null, "last": 1}',
        b'{"packages": [], "oldest": null, "last": true}',
        b'{"packages": [], "oldest": null, "last": -1}',
    ],
)
def test_a_malformed_listing_is_refused(bench: Bench, body: bytes, capsys: pytest.CaptureFixture[str]) -> None:
    bench.subscribe()
    bench.transport.replies[f"/v1/subscriptions/{UID}/reports?after=0"] = Reply(200, body)
    assert bench.pull() == 1
    assert "bad_response" in capsys.readouterr().err


def test_a_revoked_pairing_is_reported_with_the_server_code(bench: Bench, capsys: pytest.CaptureFixture[str]) -> None:
    pairing.revoke_pairing(bench.core, bench.pairing.key_id)
    assert bench.pull() == 1
    assert "revoked" in capsys.readouterr().err


def test_a_refusal_without_a_readable_code_is_reported_by_its_status(
    bench: Bench, capsys: pytest.CaptureFixture[str]
) -> None:
    bench.transport.replies["/v1/subscriptions"] = Reply(502, b"<html>bad gateway</html>")
    assert bench.pull() == 1
    assert "http_502" in capsys.readouterr().err


def _rotate(bench: Bench) -> Core:
    """Rotate the server's key; the new sealer signs with the incoming key and joins the statement."""
    state_dir, now = bench.world.app.config.state_dir, bench.world.clock.now()
    keys.rotate(state_dir, now)
    signing = keys.load_signing_key(state_dir)
    return replace(bench.core, sealer=ProtocolSealer(signing, keys.current_rotation(state_dir, signing, now)))


def test_a_key_rotation_is_followed_and_the_old_key_given_up(
    bench: Bench, capsys: pytest.CaptureFixture[str]
) -> None:
    _two_reports(bench)
    assert bench.pull() == 0
    old_key = bench.core.sealer.public_key
    rotated = _rotate(bench)
    bench.core = rotated
    bench.transport.api = Api(rotated, limiter=RateLimiter(limit=100_000))
    bench.world.collector.set("news", ("c", {"title": "C"}))
    bench.round()
    capsys.readouterr()
    assert bench.pull() == 0
    assert "new key is now trusted" in capsys.readouterr().out
    state = store.load(bench.state_dir)
    assert state.trusted_keys == [rotated.sealer.public_key] and old_key not in state.trusted_keys and state.rotated


def test_after_a_rotation_an_old_package_of_another_subscription_gives_way_to_a_state(bench: Bench) -> None:
    """Protocol §6.3: the old key is given up, so a package it signed can only be replaced by a fresh `state`."""
    bench.world.collector.set("other", ("x", {"title": "X"}))
    bench.subscribe(OTHER, "other")
    bench.world.collector.set("news", ("a", {"title": "A"}))
    bench.round()  # package 1 of OTHER is signed by the old key and stays unread
    rotated = _rotate(bench)
    bench.core = rotated
    bench.transport.api = Api(rotated, limiter=RateLimiter(limit=100_000))
    bench.subscribe(UID, "news")  # sorted first: this subscription adopts the new key
    bench.round()
    assert UID < OTHER
    assert bench.pull() == 0
    assert bench.filed() == ["00000001-state"]
    assert bench.filed(OTHER) == ["00000001-state"]
    state = store.load(bench.state_dir)
    assert state.last == {UID: 1, OTHER: 1}


def test_files_are_private(bench: Bench) -> None:
    _two_reports(bench)
    assert bench.pull() == 0
    assert stat.S_IMODE(bench.state_dir.stat().st_mode) == 0o700
    assert stat.S_IMODE((bench.state_dir / store.STATE_FILE).stat().st_mode) == 0o600
    report = bench.folder / UID / "00000001-state"
    assert stat.S_IMODE((bench.folder / UID).stat().st_mode) == 0o700
    assert stat.S_IMODE(report.stat().st_mode) == 0o700
    assert all(stat.S_IMODE(p.stat().st_mode) == 0o600 for p in report.iterdir())
    assert not [p for p in (bench.folder / UID).iterdir() if p.name.startswith(".incoming")]


def test_pair_never_prints_the_secret_and_refuses_a_second_pairing(
    bench: Bench, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    assert _pair(bench, monkeypatch) == 1
    captured = capsys.readouterr()
    assert "already paired" in captured.err and bench.code not in captured.out + captured.err


def test_a_bad_pairing_code_leaves_nothing_behind(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr("sys.stdin", io.StringIO("VEIL1:nonsense\n"))
    assert cli.main(["--lang", "en", "--state-dir", str(tmp_path / "s"), "pair"]) == 1
    assert "not valid" in capsys.readouterr().err and not (tmp_path / "s" / store.STATE_FILE).exists()


def test_pulling_before_pairing_is_explained(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code = cli.main(["--lang", "fr", "--state-dir", str(tmp_path / "s"), "pull", "--folder", str(tmp_path / "r")])
    assert code == 1 and "pas encore jumelé" in capsys.readouterr().err
    assert not (tmp_path / "s").exists()


def test_a_state_file_others_can_read_is_refused(bench: Bench, capsys: pytest.CaptureFixture[str]) -> None:
    (bench.state_dir / store.STATE_FILE).chmod(0o644)
    assert bench.pull() == 1
    assert "not private" in capsys.readouterr().err


def test_a_corrupt_state_file_is_refused(bench: Bench, capsys: pytest.CaptureFixture[str]) -> None:
    (bench.state_dir / store.STATE_FILE).write_text("{}")
    assert bench.pull() == 1
    assert "cannot be read" in capsys.readouterr().err


def test_a_folder_pairing_needs_a_folder_to_read(
    tmp_path: Path, bench: Bench, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    code = PairingCode("folder:", bench.pairing.key_id, bench.pairing.secret, bench.core.sealer.public_key).encode()
    monkeypatch.setattr("sys.stdin", io.StringIO(code))
    state = tmp_path / "folder-state"
    assert cli.main(["--lang", "en", "--state-dir", str(state), "pair"]) == 0
    assert "delivery by folder" in capsys.readouterr().out
    assert cli.main(["--lang", "en", "--state-dir", str(state), "pull", "--folder", str(tmp_path / "r")]) == 1
    assert "--from" in capsys.readouterr().err


def test_two_commands_cannot_run_on_the_same_state(bench: Bench, capsys: pytest.CaptureFixture[str]) -> None:
    with store.locked(bench.state_dir):
        assert bench.pull() == 1
    assert "Another veilleur-receive command" in capsys.readouterr().err


def test_messages_are_translated(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit):
        cli.main(["--lang", "fr", "--help"])
    out = capsys.readouterr().out
    assert "utilisation :" in out and "Récepteur de référence" in out and "afficher la version" in out
    assert cli.main(["--lang", "fr", "version"]) == 0


def test_a_symbolic_link_in_the_destination_is_refused(
    bench: Bench, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _two_reports(bench)
    outside = tmp_path / "outside"
    outside.mkdir()
    bench.folder.mkdir()
    (bench.folder / UID).symlink_to(outside)
    assert bench.pull() == 1
    assert "cannot be used safely" in capsys.readouterr().err
    assert list(outside.iterdir()) == [] and bench.last() == 0


def test_a_report_filed_before_a_crash_is_filed_again_whole(bench: Bench) -> None:
    _two_reports(bench)
    partial = bench.folder / UID / "00000001-state"
    partial.mkdir(parents=True)
    (partial / "leftover").write_text("from an earlier attempt")
    assert bench.pull() == 0
    assert sorted(p.name for p in partial.iterdir()) == ["items.jsonl", "manifest.json"]


def _export_command(bench: Bench, monkeypatch: pytest.MonkeyPatch, target: Path, uid: str, *options: str) -> None:
    monkeypatch.setattr(bench.world.app.store, "close", lambda: None)
    state_dir = str(bench.world.app.config.state_dir)
    argv = ["--lang", "en", "--state-dir", state_dir, "export", uid, "--folder", str(target), *options]
    assert server_cli.main(argv, opener=lambda config: bench.world.app) == 0


def test_an_export_replaces_the_packages_of_the_old_key_by_a_state(
    bench: Bench, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A folder cannot ask for a `state` (protocol §6.3): a member who adopted the new key still gets past it."""
    bench.world.collector.set("news", ("a", {"title": "A"}))
    bench.world.collector.set("other", ("x", {"title": "X"}))
    bench.subscribe(UID, "news")
    bench.subscribe(OTHER, "other")
    bench.round()
    bench.core = _rotate(bench)
    bench.world.collector.set("news", ("a", {"title": "A"}), ("b", {"title": "B"}))
    bench.round()
    _export_command(bench, monkeypatch, tmp_path / "first", UID)
    assert bench.receive("pull", "--folder", str(bench.folder), "--from", str(tmp_path / "first")) == 0
    _export_command(bench, monkeypatch, tmp_path / "second", OTHER)
    assert [path.name for path in (tmp_path / "second").iterdir()] == [f"{OTHER}-00000001-state.veil"]
    assert bench.receive("pull", "--folder", str(bench.folder), "--from", str(tmp_path / "second")) == 0
    assert bench.last(OTHER) == 1


def test_an_export_of_packages_newer_than_the_rotation_is_left_as_it_is(
    bench: Bench, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _two_reports(bench)
    bench.core = _rotate(bench)
    bench.world.clock.advance(days=1)
    bench.world.collector.set("news", ("z", {"title": "Z"}))
    bench.round()
    _export_command(bench, monkeypatch, tmp_path / "usb", UID, "--after", "2")
    assert [path.name for path in (tmp_path / "usb").iterdir()] == [f"{UID}-00000003-delta.veil"]


def test_a_package_of_the_old_key_is_skipped_only_when_a_later_state_covers_it(
    bench: Bench, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _two_reports(bench)
    assert bench.pull() == 0
    old = _server_key(bench)
    bench.core = _rotate(bench)
    bench.world.collector.set("news", ("z", {"title": "Z"}))
    bench.round()
    assert bench.pull() == 0, "the new key is adopted"
    source = tmp_path / "usb"
    _export(source, "1.veil", _sealed(bench, 1, Kind.STATE, uid=OTHER, key=old))
    assert bench.receive("pull", "--folder", str(bench.folder), "--from", str(source)) == 1
    assert "bad_signature" in capsys.readouterr().err and bench.last(OTHER) == 0
    _export(source, "2.veil", _sealed(bench, 2, Kind.STATE, uid=OTHER, key=_server_key(bench)))
    assert bench.receive("pull", "--folder", str(bench.folder), "--from", str(source)) == 0
    assert bench.filed(OTHER) == ["00000002-state"]
