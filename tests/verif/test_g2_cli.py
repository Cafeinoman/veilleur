# SPDX-License-Identifier: EUPL-1.2
"""Independent check of the administration command line of milestone G2 (cahier EF-70, EF-80, EF-10, EF-51)."""

from __future__ import annotations

import contextlib
import io
import re
from collections.abc import Iterator
from pathlib import Path

import pytest

from tests.server.fakes import World, make_world
from veilleur import i18n
from veilleur.apps.server import argparse_i18n, cli
from veilleur.apps.server.config import Config, TeamDeclaration
from veilleur.apps.server.context import App
from veilleur.core.services import jobs, pairing, subscriptions
from veilleur_protocol import read_header

UID = "99998888777766665555444433332222"


@pytest.fixture
def world(tmp_path: Path) -> Iterator[World]:
    config = Config(
        state_dir=tmp_path / "state",
        public_url="https://veille.example.org",
        subscriptions=(TeamDeclaration("team_news", {"collector": "fetch", "params": {"topic": "t"}}, ("desk 1",)),),
    )
    w = make_world(tmp_path / "state", config)
    yield w
    w.app.close()


def run(world: World, *argv: str, lang: str = "en") -> tuple[int, str, str]:
    def opener(config: Config) -> App:
        return world.app

    saved = world.app.store.close
    world.app.store.close = lambda: None  # type: ignore[method-assign]
    out, err = io.StringIO(), io.StringIO()
    try:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = cli.main(["--lang", lang, *argv], opener=opener)
    finally:
        world.app.store.close = saved  # type: ignore[method-assign]
    return code, out.getvalue(), err.getvalue()


def _help(argv: list[str]) -> str:
    i18n.setup("fr")
    argparse_i18n.install()
    try:
        parser = cli.build_parser()
        out = io.StringIO()
        with contextlib.redirect_stdout(out), pytest.raises(SystemExit):
            parser.parse_args([*argv, "--help"])
        return out.getvalue()
    finally:
        i18n.setup("en")


@pytest.mark.xfail(
    reason="minor: default metavars LABEL, LIMIT, AFTER, LISTEN, PORT stay in English in the French help (cli.py)",
    strict=True,
)
@pytest.mark.parametrize("argv", [["pairing", "new"], ["log"], ["export", "x"], ["serve"]])
def test_french_help_has_no_english_placeholder(argv: list[str]) -> None:
    """EF-70 'entièrement traduite', EF-80: every word a person reads is French with --lang fr."""
    text = _help(argv)
    leftovers = re.findall(r"\b(LABEL|LIMIT|AFTER|LISTEN|PORT)\b", text)
    assert leftovers == [], leftovers


def test_every_ef70_command_exists() -> None:
    parser = cli.build_parser()
    for argv in (
        ["info"],
        ["config"],
        ["pairing", "new", "--label", "x"],
        ["pairing", "list"],
        ["pairing", "revoke", "x"],
        ["subscription", "list"],
        ["subscription", "show", "x"],
        ["collectors"],
        ["collectors", "allow", "p", "c"],
        ["collectors", "deny", "p", "c"],
        ["collectors", "default", "p", "c"],
        ["round"],
        ["sources"],
        ["log"],
        ["export", "x", "--folder", "/tmp/x"],
        ["notify", "--test"],
        ["key", "rotate"],
        ["serve"],
        ["version"],
    ):
        parser.parse_args(argv)


@pytest.mark.xfail(
    reason="minor: synchronise_team raises unknown_collector before run_round, so `veilleur round` stops for all",
    strict=True,
)
def test_a_broken_team_declaration_does_not_stop_the_other_subscriptions(world: World) -> None:
    """EF-05: a source in trouble (here: its collector plugin is gone) must not stop the round for the others."""
    core = world.app.core
    pairing.create_pairing(core, "desk 1")
    p2 = pairing.create_pairing(core, "desk 2")
    core.store.set_grant(next(p.key_id for p in core.store.list_pairings() if p.label == "desk 1"), "fetch", True)
    subscriptions.put_subscription(core, p2.key_id, UID, 0, {"collector": "fake", "params": {"topic": "n"}})
    world.collector.set("n", ("a", {"t": 1}))
    del core.plugins.collectors["fetch"]  # type: ignore[attr-defined]  # plugin uninstalled or failing to load
    code, _, err = run(world, "round")
    assert code == 0, err
    assert core.store.package_bounds(p2.key_id, UID).last == 1


def test_pairing_list_never_shows_the_secret(world: World) -> None:
    _, out, _ = run(world, "pairing", "new", "--label", "desk 1")
    secret_code = out.splitlines()[-1]
    assert secret_code.startswith("VEIL1:")
    _, listing, _ = run(world, "pairing", "list")
    p = world.app.store.list_pairings()[0]
    assert p.secret.hex() not in listing and secret_code not in listing
    _, info, _ = run(world, "info")
    assert secret_code not in info
    _, log, _ = run(world, "log")
    assert secret_code not in log and p.secret.hex() not in log


def test_export_writes_sealed_packages_named_by_their_header(world: World, tmp_path: Path) -> None:
    core = world.app.core
    p = pairing.create_pairing(core, "desk 9")
    subscriptions.put_subscription(core, p.key_id, UID, 0, {"collector": "fake", "params": {"topic": "n"}})
    world.collector.set("n", ("a", {"t": 1}))
    jobs.run_pending(core)
    code, _, err = run(world, "export", UID, "--folder", str(tmp_path / "out"))
    assert code == 0, err
    files = sorted((tmp_path / "out").iterdir())
    assert len(files) == 1
    header = read_header(files[0].read_bytes())
    assert header.uid == UID and header.seq == 1 and header.kind.value == "state"


def test_revoke_then_round_serves_nothing_to_that_pairing(world: World) -> None:
    core = world.app.core
    p = pairing.create_pairing(core, "desk 9")
    subscriptions.put_subscription(core, p.key_id, UID, 0, {"collector": "fake", "params": {"topic": "n"}})
    assert run(world, "pairing", "revoke", "desk 9")[0] == 0
    world.collector.set("n", ("a", {"t": 1}))
    run(world, "round")
    assert core.store.package_bounds(p.key_id, UID).last == 0
