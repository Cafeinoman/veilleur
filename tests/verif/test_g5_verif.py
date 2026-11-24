# SPDX-License-Identifier: EUPL-1.2
"""Independent checks of batch G5 (deployment), written from spec ENF-01 to ENF-08 and plan.md.

The NixOS modules are evaluated by `nix eval`, offline, when Nix and the locked inputs are available. No test opens a
port or reaches the network.
"""

from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import socket
import sqlite3
import subprocess
from pathlib import Path
from typing import Any

import pytest

from veilleur.apps.server import cli
from veilleur.apps.server.wsgi import MAX_BODY

ROOT = Path(__file__).resolve().parents[2]
DEPLOY = ROOT / "deploy"
SYSTEMD = DEPLOY / "systemd"
MODULE = DEPLOY / "nixos" / "module.nix"
CONTAINER = DEPLOY / "nixos" / "container.nix"
PROBE = Path(__file__).with_name("g5_probe.nix")
GUIDES = {language: ROOT / "docs" / language / "admin-guide.md" for language in ("en", "fr")}
NIX_TIMEOUT = 540


def _nix_eval(attribute: str) -> subprocess.CompletedProcess[str]:
    expression = f'(import {PROBE} {{ root = "{ROOT}"; }}).{attribute}'
    command = ["nix", "eval", "--offline", "--impure", "--json", "--expr", expression]
    return subprocess.run(command, capture_output=True, text=True, timeout=NIX_TIMEOUT, check=False)


@pytest.fixture(name="nix", scope="module")
def _nix() -> None:
    if shutil.which("nix") is None:
        pytest.skip("Nix is not installed")
    locked = subprocess.run(
        ["nix", "flake", "archive", "--offline", "--dry-run", "--no-write-lock-file", f"git+file://{ROOT}"],
        capture_output=True,
        timeout=NIX_TIMEOUT,
        check=False,
    )
    if locked.returncode != 0:
        pytest.skip("the locked flake inputs are not available offline")


@pytest.fixture(name="report", scope="module")
def _report(nix: None) -> dict[str, Any]:
    done = _nix_eval("report")
    assert done.returncode == 0, done.stderr[-3000:]
    loaded: dict[str, Any] = json.loads(done.stdout)
    return loaded


@pytest.fixture(name="sqlite_cli", scope="module")
def _sqlite_cli() -> str:
    found = shutil.which("sqlite3")
    if found is not None:
        return str(Path(found).parent)
    if shutil.which("nix") is None:
        pytest.skip("neither sqlite3 nor Nix is available")
    done = subprocess.run(
        [
            "nix",
            "build",
            "--offline",
            "--no-link",
            "--print-out-paths",
            "--inputs-from",
            str(ROOT),
            "nixpkgs#sqlite.bin",
        ],
        capture_output=True,
        text=True,
        timeout=NIX_TIMEOUT,
        check=False,
    )
    if done.returncode != 0:
        pytest.skip("the sqlite3 command is not available offline")
    return done.stdout.split()[0] + "/bin"


def _fallback_script(state: Path) -> str:
    text = (SYSTEMD / "veilleur-snapshot.sh").read_text("utf-8")
    return text.replace("state=/var/lib/veilleur", f"state={shlex.quote(str(state))}")


def _module_script(state: Path) -> str:
    """The body of the snapshot script of the NixOS module, pointed at a test directory."""
    match = re.search(
        r'writeShellScript "veilleur-snapshot" \'\'\n(.*?)\n  \'\';', MODULE.read_text("utf-8"), re.DOTALL
    )
    assert match is not None
    body = re.sub(r"export PATH=\$\{.*?\n    \}\n", "", match[1], flags=re.DOTALL)
    body = body.replace("${snapshotDir}", f"{state}/snapshot").replace("${stateDir}", str(state))
    return "#!/bin/sh\n" + body


SCRIPTS = {"fallback": _fallback_script, "module": _module_script}


def _run_snapshot(kind: str, state: Path, tools: str) -> subprocess.CompletedProcess[str]:
    script = state.parent / f"snapshot-{kind}.sh"
    script.write_text(SCRIPTS[kind](state), "utf-8")
    script.chmod(0o700)
    environment = {**os.environ, "PATH": f"{tools}:{os.environ['PATH']}"}
    return subprocess.run(
        ["bash", str(script)], capture_output=True, text=True, env=environment, timeout=60, check=False
    )


def _state(tmp_path: Path) -> Path:
    state = tmp_path / "state"
    state.mkdir()
    with sqlite3.connect(state / "veilleur.db") as db:
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("CREATE TABLE pairing (label TEXT)")
        db.execute("INSERT INTO pairing VALUES ('desk 3')")
    db.close()
    (state / "signing.key").write_bytes(b"fictional-key")
    (state / "signing.key").chmod(0o600)
    return state


def _labels(database: Path) -> list[str]:
    db = sqlite3.connect(database)
    try:
        return [row[0] for row in db.execute("SELECT label FROM pairing")]
    finally:
        db.close()


# ENF-08: the consistent copy.


@pytest.mark.parametrize("kind", sorted(SCRIPTS))
def test_the_snapshot_holds_what_is_still_in_the_write_ahead_log(kind: str, tmp_path: Path, sqlite_cli: str) -> None:
    state = _state(tmp_path)
    writer = sqlite3.connect(state / "veilleur.db")
    try:
        writer.execute("PRAGMA wal_autocheckpoint=0")
        writer.execute("INSERT INTO pairing VALUES ('desk 4')")
        writer.commit()
        done = _run_snapshot(kind, state, sqlite_cli)
    finally:
        writer.close()
    assert done.returncode == 0, done.stderr
    assert _labels(state / "snapshot" / "veilleur.db") == ["desk 3", "desk 4"]
    assert (state / "snapshot" / "signing.key").read_bytes() == b"fictional-key"
    assert (state / "snapshot" / "signing.key").stat().st_mode & 0o077 == 0
    assert not list(state.glob(".snapshot.*"))


@pytest.mark.parametrize("kind", sorted(SCRIPTS))
def test_a_corrupt_database_leaves_the_previous_snapshot_in_place(kind: str, tmp_path: Path, sqlite_cli: str) -> None:
    state = _state(tmp_path)
    assert _run_snapshot(kind, state, sqlite_cli).returncode == 0
    for name in ("veilleur.db-wal", "veilleur.db-shm"):
        (state / name).unlink(missing_ok=True)
    (state / "veilleur.db").write_bytes(b"this is not a database" * 400)
    assert _run_snapshot(kind, state, sqlite_cli).returncode != 0
    assert _labels(state / "snapshot" / "veilleur.db") == ["desk 3"]


@pytest.mark.parametrize("kind", sorted(SCRIPTS))
def test_a_missing_database_leaves_the_previous_snapshot_in_place(kind: str, tmp_path: Path, sqlite_cli: str) -> None:
    """BLOCKING: the last good copy is replaced by an empty database, and the unit reports success."""
    state = _state(tmp_path)
    assert _run_snapshot(kind, state, sqlite_cli).returncode == 0
    for name in ("veilleur.db", "veilleur.db-wal", "veilleur.db-shm"):
        (state / name).unlink(missing_ok=True)
    done = _run_snapshot(kind, state, sqlite_cli)
    assert done.returncode != 0, "the snapshot of a missing database reports success"
    assert _labels(state / "snapshot" / "veilleur.db") == ["desk 3"]


# ENF-03, ENF-03b: inert modules, on any machine.


def test_an_inert_host_can_read_the_backup_paths_of_the_container(nix: None) -> None:
    """BLOCKING: the guide wires the backup to this option, and the disabled module aborts the evaluation."""
    done = _nix_eval("inertHostBackupPaths")
    assert done.returncode == 0, done.stderr[-1500:]


# ENF-03b: every declared port conflict.


def test_the_control_conflict_is_reported(report: dict[str, Any]) -> None:
    assert report["conflicts"]["nginx on 443 (control)"]


@pytest.mark.parametrize(
    "case",
    [
        "another NAT forward on 443",
        "another NAT forward on 443, container",
        "an OCI container on 443",
        "another NAT forward on 8443",
        "nginx on the internal port",
    ],
)
def test_a_declared_port_conflict_is_reported(report: dict[str, Any], case: str) -> None:
    """BLOCKING: ENF-03b asks for an assertion on any port conflict declared in the configuration."""
    assert report["conflicts"][case], f"no assertion for: {case}"


# ENF-03b: built-in ntfy and an external front end, in the container.


def test_the_host_proxy_can_reach_the_built_in_ntfy_of_the_container(report: dict[str, Any]) -> None:
    """BLOCKING: ntfy stays on the container's loopback, out of reach of the front end the guide describes."""
    found = report["containerBehindProxy"]
    assert not found["failures"], "this combination is accepted by the modules"
    assert not found["ntfyListen"].startswith("127.") and 2586 in found["openPorts"], found


# ENF-03b: the internal address.


@pytest.mark.parametrize("address", ["0.0.0.0", "::"])
def test_the_usual_wildcards_are_refused(report: dict[str, Any], address: str) -> None:
    assert report["wildcards"][address]


@pytest.mark.xfail(strict=True, reason="minor: other spellings of the wildcard address pass the assertion")
@pytest.mark.parametrize("address", ["0", "::0", "0:0:0:0:0:0:0:0"])
def test_other_spellings_of_the_wildcard_are_refused(report: dict[str, Any], address: str) -> None:
    assert report["wildcards"][address]


def test_the_short_spelling_really_is_the_wildcard_address() -> None:
    family, _, _, _, address = socket.getaddrinfo("0", 8470, socket.AF_INET, socket.SOCK_STREAM)[0]
    assert family == socket.AF_INET
    assert address[0] == "0.0.0.0"


# ENF-01, ENF-03b: the public address.


@pytest.mark.parametrize("host", ["watch.example.org", "192.0.2.10"])
def test_a_name_or_an_address_is_accepted(report: dict[str, Any], host: str) -> None:
    assert not report["publicHosts"][host]


@pytest.mark.xfail(strict=True, reason="minor: publicHost takes forms that produce an unusable address")
@pytest.mark.parametrize("host", ["2001:db8::1", "watch.example.org:8443", "user@watch.example.org"])
def test_a_public_host_that_is_not_a_host_is_refused(report: dict[str, Any], host: str) -> None:
    assert report["publicHosts"][host]


# ENF-03: the documented ways of loading a locked version.


@pytest.mark.xfail(strict=True, reason="minor: without `rev`, Nix refuses this reference in pure evaluation")
def test_the_documented_get_flake_reference_is_locked(nix: None) -> None:
    guide = GUIDES["en"].read_text("utf-8")
    assert 'builtins.getFlake "github:Cafeinoman/veilleur/<tag>?narHash=<hash>"' in guide
    reference = "github:Cafeinoman/veilleur/v0.1.0?narHash=sha256-AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA="
    expression = f'builtins.getFlake "{reference}"'
    command = ["nix", "eval", "--offline", "--option", "pure-eval", "true", "--expr", expression]
    done = subprocess.run(command, capture_output=True, text=True, timeout=120, check=False)
    assert "unlocked flake reference" not in done.stderr


# ENF-04: hardening, as evaluated.


@pytest.mark.parametrize("unit", ["veilleur", "veilleur-round", "veilleur-snapshot"])
def test_a_unit_of_the_module_is_hardened(report: dict[str, Any], unit: str) -> None:
    found = report["hardening"][unit]
    assert found["User"] == "veilleur"
    assert found["UMask"] == "0077"
    assert found["CapabilityBoundingSet"] == ""
    assert found["AmbientCapabilities"] == ""
    assert found["NoNewPrivileges"] is True
    assert found["ProtectSystem"] == "strict"
    assert found["PrivateTmp"] is True and found["PrivateDevices"] is True and found["PrivateUsers"] is True
    assert found["RestrictNamespaces"] is True
    assert "@system-service" in found["SystemCallFilter"]
    assert found["RestrictAddressFamilies"]


@pytest.mark.xfail(strict=True, reason="outside the specification: the unit drawing ntfy's tokens runs as plain root")
def test_the_unit_that_draws_the_tokens_is_hardened(report: dict[str, Any]) -> None:
    assert {"ProtectSystem", "NoNewPrivileges", "PrivateNetwork"} <= set(report["secretsUnit"])


# ENF-01, ENF-07, ES-09, ES-10: what the module writes.


def test_the_round_runs_daily_by_default(report: dict[str, Any]) -> None:
    assert report["roundTimer"] == "daily"


def test_the_generated_configuration_holds_paths_and_no_token(report: dict[str, Any]) -> None:
    text = report["configText"]
    assert 'token_file = "/var/lib/veilleur-ntfy/publish.token"' in text
    assert "tk_" not in text


def test_no_site_of_caddy_keeps_an_access_log(report: dict[str, Any]) -> None:
    assert report["accessLogs"]
    assert set(report["accessLogs"].values()) == {None}


def test_the_built_in_ntfy_refuses_anonymous_clients(report: dict[str, Any]) -> None:
    assert report["ntfyDefaultAccess"] == "deny-all"


@pytest.mark.xfail(strict=True, reason="outside the specification: a disabled module still lists paths to back up")
def test_a_disabled_service_lists_nothing_to_back_up(report: dict[str, Any]) -> None:
    assert report["disabledServiceBackupPaths"] == []


# ENF-01: the outbound firewall of the container.


def _firewall() -> str:
    return CONTAINER.read_text("utf-8")


@pytest.mark.parametrize(
    "network",
    ["10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "100.64.0.0/10", "127.0.0.0/8", "169.254.0.0/16"],
)
def test_the_firewall_blocks_a_private_network(network: str) -> None:
    assert f'"{network}"' in _firewall()


def test_the_firewall_closes_the_host_port_25_and_ipv6() -> None:
    text = _firewall()
    forward = text[text.index("chain forward") : text.index("chain input")]
    established = forward.index("ct state established,related accept")
    for rule in ("meta nfproto ipv6 drop", "ip daddr @blocked_ipv4 drop", "tcp dport 25 drop"):
        assert established < forward.index(rule)
    assert 'iifname "${interface}" drop' in text[text.index("chain input") :]


# ENF-05, ENF-08: the administration guide.


def _code_blocks(language: str) -> list[str]:
    return re.findall(r"^```\w*\n(.*?)^```", GUIDES[language].read_text("utf-8"), re.MULTILINE | re.DOTALL)


def test_both_guides_have_the_same_structure() -> None:
    titles = {k: re.findall(r"^#+ ", v.read_text("utf-8"), re.MULTILINE) for k, v in GUIDES.items()}
    assert titles["en"] == titles["fr"]
    assert len(_code_blocks("en")) == len(_code_blocks("fr"))


@pytest.mark.parametrize("language", sorted(GUIDES))
def test_the_commands_of_the_guide_exist(language: str) -> None:
    parser = cli.build_parser()
    commands = [
        line.split("#")[0].strip()
        for block in _code_blocks(language)
        for line in block.splitlines()
        if line.startswith("veilleur-admin ")
    ]
    assert len(commands) >= 6
    for command in commands:
        parser.parse_args(shlex.split(command)[1:])


@pytest.mark.parametrize("language", sorted(GUIDES))
def test_the_nginx_block_lets_the_largest_request_through(language: str) -> None:
    match = re.search(r"client_max_body_size (\d+)m;", GUIDES[language].read_text("utf-8"))
    assert match is not None
    assert int(match[1]) * 1_000_000 >= MAX_BODY


@pytest.mark.parametrize("language", sorted(GUIDES))
@pytest.mark.parametrize("subject", ["veilleur-snapshot.service", "backupPaths", "AAAA", "--rollback"])
def test_the_guide_covers(language: str, subject: str) -> None:
    assert subject in GUIDES[language].read_text("utf-8")
