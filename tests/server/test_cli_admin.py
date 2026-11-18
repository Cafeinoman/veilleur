# SPDX-License-Identifier: EUPL-1.2
"""Administration command line (EF-70), in both languages, and the end-to-end round of milestone G2."""

from __future__ import annotations

import io
import json
import logging
import re
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from veilleur.apps.server import cli
from veilleur.apps.server.config import Config, TeamDeclaration
from veilleur.apps.server.context import App
from veilleur.apps.server.wsgi import Api
from veilleur.core.ports.plugins import RoundCounts
from veilleur.core.services import jobs
from veilleur_protocol import (
    PairingCode,
    decode_pairing_code,
    open_package,
    read_header,
    seal_subscription,
    sign_request,
)

from .fakes import World, make_world


@pytest.fixture
def world(tmp_path: Path) -> Iterator[World]:
    """A world whose application the command line reuses instead of opening its own."""
    config = Config(
        state_dir=tmp_path / "state",
        public_url="https://veille.example.org",
        subscriptions=(
            TeamDeclaration("team_news", {"collector": "fake", "params": {"topic": "team"}}, ("desk 1", "nobody")),
        ),
    )
    w = make_world(tmp_path / "state", config)
    yield w
    w.app.close()


def run(world: World, capsys: pytest.CaptureFixture[str], *argv: str) -> tuple[int, str, str]:
    """Run the command line on the world's application (left open: `close` is neutralised)."""

    def opener(config: Config) -> App:
        return world.app

    world.app.store.close, saved = (lambda: None), world.app.store.close  # type: ignore[method-assign]
    try:
        code = cli.main(["--lang", "en", "--state-dir", str(world.app.config.state_dir), *argv], opener=opener)
    finally:
        world.app.store.close = saved  # type: ignore[method-assign]
    out = capsys.readouterr()
    return code, out.out, out.err


def _new_pairing(world: World, capsys: pytest.CaptureFixture[str], label: str) -> PairingCode:
    code, out, _ = run(world, capsys, "pairing", "new", "--label", label)
    assert code == 0
    return decode_pairing_code(out.splitlines()[-1])


def test_end_to_end_without_network(world: World, capsys: pytest.CaptureFixture[str]) -> None:
    """Milestone G2: from the pairing to a package fetched through the API, on a fake collector."""
    pairing_code = _new_pairing(world, capsys, "desk 3")
    assert pairing_code.server == "https://veille.example.org"
    assert pairing_code.sign_key == world.app.core.sealer.public_key
    world.collector.set("news", ("a", {"title": "A"}))
    api = Api(world.app.core)
    uid = "fedcba9876543210fedcba9876543210"

    def call(method: str, target: str, body: bytes = b"") -> tuple[str, bytes]:
        signed = sign_request(pairing_code.secret, pairing_code.key_id, method, target, body, world.clock.now())
        environ: dict[str, Any] = {
            "REQUEST_METHOD": method,
            "REQUEST_URI": target,
            "CONTENT_LENGTH": str(len(body)),
            "wsgi.input": io.BytesIO(body),
            "HTTP_AUTHORIZATION": signed.authorization,
            "HTTP_X_VEILLEUR_DATE": signed.date,
        }
        status: list[str] = []
        data = b"".join(api(environ, lambda s, h: status.append(s)))
        return status[0], data

    document = {"collector": "fake", "params": {"topic": "news"}, "frequency": "every_round", "language": "fr"}
    status, body = call("PUT", f"/v1/subscriptions/{uid}", seal_subscription(pairing_code.secret, uid, 0, document))
    assert status == "200 OK" and json.loads(body) == {"version": 1}
    assert run(world, capsys, "round")[0] == 0
    world.clock.advance(hours=1)
    world.collector.set("news", ("a", {"title": "A"}), ("b", {"title": "B"}))
    _, out, _ = run(world, capsys, "round")
    assert "1 report produced" in out and "1 new item" in out
    status, body = call("GET", f"/v1/subscriptions/{uid}/reports?after=0")
    assert [p["seq"] for p in json.loads(body)["packages"]] == [1, 2]
    trusted = [pairing_code.sign_key]
    for seq, kind, keys in ((1, "state", ["a"]), (2, "delta", ["b"])):
        status, package = call("GET", f"/v1/subscriptions/{uid}/reports/{seq}")
        opened = open_package(package, secret=pairing_code.secret, uid=uid, trusted_keys=trusted, seq=seq)
        assert opened.kind.value == kind and [i.key for i in opened.items] == keys


def test_pairing_commands(world: World, capsys: pytest.CaptureFixture[str]) -> None:
    first = _new_pairing(world, capsys, "desk 1")
    _new_pairing(world, capsys, "desk 2")
    code, out, _ = run(world, capsys, "pairing", "list")
    assert code == 0 and "desk 1" in out and "desk 2" in out and first.key_id in out
    assert first.secret.hex() not in out
    code, out, _ = run(world, capsys, "pairing", "revoke", "desk 1")
    assert code == 0 and f"Pairing {first.key_id} revoked." in out
    code, _, err = run(world, capsys, "pairing", "revoke", "desk 9")
    assert code == 1 and err == "error: No pairing matches desk 9.\n"
    code, _, err = run(world, capsys, "pairing", "new", "--label", " ")
    assert code == 1 and "never a name" in err


def test_pairing_code_for_folder_delivery(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    w = make_world(tmp_path / "state", Config(state_dir=tmp_path / "state"))
    try:
        assert _new_pairing(w, capsys, "desk 1").server == "folder:"
    finally:
        w.app.close()


def test_invalid_public_url_creates_no_pairing(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    w = make_world(tmp_path / "state", Config(state_dir=tmp_path / "state", public_url="https://bad host"))
    try:
        code, _, err = run(w, capsys, "pairing", "new", "--label", "desk 1")
        assert code == 1 and "public_url" in err
        assert w.app.store.list_pairings() == []
    finally:
        w.app.close()


def test_team_subscriptions_subscription_commands_and_log(world: World, capsys: pytest.CaptureFixture[str]) -> None:
    _new_pairing(world, capsys, "desk 1")
    world.collector.set("team", ("x", {"title": "X"}))
    assert run(world, capsys, "round")[0] == 0
    code, out, _ = run(world, capsys, "subscription", "list")
    assert code == 0 and "team_news" in out
    uid = re.search(r"\b([0-9a-f]{32})\b", out).group(1)  # type: ignore[union-attr]
    code, out, _ = run(world, capsys, "subscription", "show", uid)
    assert "Origin: team_news" in out and "Packages: last 1, oldest kept 1" in out
    code, _, err = run(world, capsys, "subscription", "show", "0" * 32)
    assert code == 1 and "No subscription matches" in err
    code, out, _ = run(world, capsys, "log")
    assert "team subscription team_news: no pairing matches nobody" in out
    assert "team subscriptions: 1 created, 0 updated, 0 deleted" in out
    assert re.search(r"round: 1 collections \(0 failed\), 1 reports, 1 new items", out)


def test_collectors_command(world: World, capsys: pytest.CaptureFixture[str]) -> None:
    _new_pairing(world, capsys, "desk 1")
    code, out, _ = run(world, capsys, "collectors")
    assert re.search(r"fake\s+no\s+yes", out) and re.search(r"fetch\s+yes\s+no", out)
    assert run(world, capsys, "collectors", "allow", "desk 1", "fetch")[1] == "Done.\n"
    code, out, _ = run(world, capsys, "collectors", "--pairing", "desk 1")
    assert re.search(r"fetch\s+yes\s+yes", out)
    run(world, capsys, "collectors", "default", "desk 1", "fetch")
    code, out, _ = run(world, capsys, "collectors", "--pairing", "desk 1")
    assert re.search(r"fetch\s+yes\s+no", out)
    code, _, err = run(world, capsys, "collectors", "allow", "desk 1", "nope")
    assert code == 1 and "Unknown collector: nope." in err


def test_sources_info_config_notify(world: World, capsys: pytest.CaptureFixture[str]) -> None:
    _new_pairing(world, capsys, "desk 1")
    world.collector.fail = "network_unavailable"
    run(world, capsys, "round")
    code, out, _ = run(world, capsys, "sources")
    assert code == 0 and "the network is unavailable" in out
    code, out, _ = run(world, capsys, "info")
    assert "Pairings: 1 active, 0 revoked" in out and "Last round: 2026-11-17 06:00:00Z" in out
    code, out, _ = run(world, capsys, "config")
    assert "Public address: https://veille.example.org" in out and "Team subscription team_news" in out
    code, out, _ = run(world, capsys, "notify", "--test")
    assert code == 0 and out == "Test notification: 1 of 1 sendings succeeded.\n"
    assert [counts for _target, counts in world.notifier.sent] == [RoundCounts(0, 0, 0)]
    code, out, _ = run(world, capsys, "notify", "--test", "--pairing", "desk 1")
    assert code == 0 and world.notifier.sent[-1][0].topic == world.app.store.list_pairings()[0].topic


def test_export_to_a_folder(world: World, capsys: pytest.CaptureFixture[str], tmp_path: Path) -> None:
    code = _new_pairing(world, capsys, "desk 1")
    world.collector.set("team", ("x", {"title": "X"}))
    run(world, capsys, "round")
    uid = world.app.store.list_subscriptions()[0].uid
    folder = tmp_path / "out"
    _, out, _ = run(world, capsys, "export", uid, "--folder", str(folder))
    assert out == "1 package written\n"
    (path,) = folder.iterdir()
    header = read_header(path.read_bytes())
    assert (header.uid, header.seq, header.kind.value) == (uid, 1, "state")
    open_package(path.read_bytes(), secret=code.secret, uid=uid, trusted_keys=[code.sign_key])
    world.clock.advance(days=91)
    run(world, capsys, "round")
    _, out, _ = run(world, capsys, "export", uid, "--folder", str(tmp_path / "later"))
    assert "a state was written instead" in out and "1 package written" in out


def test_key_rotation_is_followed_by_receivers(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    w = make_world(tmp_path / "state")
    pairing_code = _new_pairing(w, capsys, "desk 1")
    w.app.close()
    _, out, _ = run_fresh(tmp_path, capsys, "key", "rotate")
    assert "rotation statement" in out
    w = make_world(tmp_path / "state")
    try:
        assert w.app.core.sealer.public_key != pairing_code.sign_key
        uid = "ab" * 16
        from veilleur.core.services import subscriptions

        subscriptions.put_subscription(
            w.app.core, pairing_code.key_id, uid, 0, {"collector": "fake", "params": {"topic": "t"}}
        )
        jobs.run_pending(w.app.core)
        data = w.app.store.get_package(pairing_code.key_id, uid, 1)
        opened = open_package(data or b"", secret=pairing_code.secret, uid=uid, trusted_keys=[pairing_code.sign_key])
        assert opened.rotation is not None and opened.rotation.new_key == w.app.core.sealer.public_key
    finally:
        w.app.close()


def run_fresh(tmp_path: Path, capsys: pytest.CaptureFixture[str], *argv: str) -> tuple[int, str, str]:
    """The command line with its own wiring (installed plugins, system clock)."""
    code = cli.main(["--lang", "en", "--state-dir", str(tmp_path / "state"), *argv])
    out = capsys.readouterr()
    return code, out.out, out.err


def test_french_output(world: World, capsys: pytest.CaptureFixture[str]) -> None:
    def opener(config: Config) -> App:
        return world.app

    world.app.store.close = lambda: None  # type: ignore[method-assign]
    assert cli.main(["--lang", "fr", "pairing", "new", "--label", "poste 1"], opener=opener) == 0
    out = capsys.readouterr().out
    assert "Remettez ce code à l'outil de réception" in out
    assert cli.main(["--lang", "fr", "pairing", "revoke", "poste 9"], opener=opener) == 1
    assert capsys.readouterr().err == "erreur : Aucun jumelage ne correspond à poste 9.\n"


def test_state_directory_and_secrets_are_private(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert run_fresh(tmp_path, capsys, "info")[0] == 0
    state = tmp_path / "state"
    assert state.stat().st_mode & 0o777 == 0o700
    assert (state / "signing.key").stat().st_mode & 0o777 == 0o600


def test_logs_carry_no_secret_nor_parameter(
    world: World, capsys: pytest.CaptureFixture[str], caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    code = _new_pairing(world, capsys, "desk 1")
    world.collector.fail = "crash"
    run(world, capsys, "round")
    _, out, _ = run(world, capsys, "log")
    text = caplog.text + out
    assert "internal detail" not in text and code.secret.hex() not in text and "team" not in caplog.text
    assert "RuntimeError" in caplog.text
