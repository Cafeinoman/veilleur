# SPDX-License-Identifier: EUPL-1.2
"""Second pass over batch G5: the fixes of the port assertion, of the snapshot and of ntfy behind the host's proxy.

The NixOS modules are evaluated by `nix eval`, offline. No test opens a port or reaches the network.
"""

from __future__ import annotations

import json
import shlex
import shutil
import sqlite3
import subprocess
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[2]
PROBE = Path(__file__).with_name("g5_pass2_probe.nix")
SNAPSHOT = ROOT / "deploy" / "systemd" / "veilleur-snapshot.sh"
NIX_TIMEOUT = 540

REPORTED = [
    "NAT range over 443",
    "NAT on 443/udp (HTTP/3)",
    "NAT on 80",
    "nspawn container on 443",
    "OCI on loopback IPv6",
    "OCI on 443/udp",
    "OCI range over 443",
    "OCI on the internal port",
    "OCI on the internal port, any address",
    "Apache on the internal port",
    "nginx on the port of the built-in ntfy",
    "container: NAT on 8443",
    "container: OCI on 443",
    "container: nspawn container on 80",
]
ACCEPTED = [
    "service alone",
    "external proxy, NAT on 443",
    "external proxy, OCI on 443",
    "external proxy, nspawn on 443",
    "ntfy with its own name, OCI on 8443",
    "ntfy none, OCI on 2586",
    "OCI on a drawn host port",
    "OCI on the container's port only",
    "OCI on 443 of the container",
    "NAT next to the public ports",
    "OCI on the internal port of another address",
    "a disabled nginx",
    "container alone",
    "container behind the host's proxy",
    "container behind the host's proxy, NAT on 443",
    "container, ntfy with its own name, OCI on 8443",
]


@pytest.fixture(name="probe", scope="module")
def _probe() -> dict[str, Any]:
    if shutil.which("nix") is None:
        pytest.skip("Nix is not installed")
    expression = f'import {PROBE} {{ root = "{ROOT}"; }}'
    command = ["nix", "eval", "--offline", "--impure", "--json", "--expr", expression]
    done = subprocess.run(command, capture_output=True, text=True, timeout=NIX_TIMEOUT, check=False)
    assert done.returncode == 0, done.stderr[-3000:]
    loaded: dict[str, Any] = json.loads(done.stdout)
    return loaded


@pytest.mark.parametrize("case", REPORTED)
def test_a_declared_conflict_is_reported(probe: dict[str, Any], case: str) -> None:
    assert probe["reported"][case], f"no assertion for: {case}"


@pytest.mark.parametrize("case", ACCEPTED)
def test_a_configuration_without_conflict_is_accepted(probe: dict[str, Any], case: str) -> None:
    assert probe["accepted"][case] == []


@pytest.mark.parametrize(
    "case",
    [
        "service: port 8443",
        "service: port 443",
        "service: port 80",
        "container: port 8443",
        "container: port 443",
    ],
)
def test_the_internal_port_cannot_be_a_public_port_of_caddy(probe: dict[str, Any], case: str) -> None:
    """ENF-03b: both sides of this conflict are options of Veilleur's own module."""
    assert probe["ownPorts"][case], f"no assertion for: {case}"


@pytest.mark.parametrize("case", ["sshd on 443", "nginx default port on the internal port"])
def test_other_declared_forms_are_reported(probe: dict[str, Any], case: str) -> None:
    """Spec section 10 lists both forms since the decision of 18/11/2026."""
    assert probe["otherForms"][case], f"no assertion for: {case}"


@pytest.mark.xfail(
    strict=True,
    reason="outside the specification: spec section 10 leaves ports opened by arbitrary units out of the assertion",
)
def test_a_socket_unit_is_reported(probe: dict[str, Any]) -> None:
    assert probe["otherForms"]["socket unit on 443"], "no assertion for: socket unit on 443"


@pytest.mark.xfail(strict=True, reason="minor: an IPv6 address gives ntfy a listen address it cannot parse")
def test_an_ipv6_address_for_ntfy_is_refused_or_bracketed(probe: dict[str, Any]) -> None:
    found = probe["ntfyOnIpv6"]
    assert found["failures"] or found["listen"] == "[::1]:2586"


def test_veilleur_publishes_where_ntfy_listens_behind_the_host_proxy(probe: dict[str, Any]) -> None:
    found = probe["behindProxy"]
    assert found["listen"] == "10.233.50.2:2586"
    assert 'url = "http://10.233.50.2:2586"' in found["config"]


# ENF-08: the last good copy.


@pytest.fixture(name="sqlite_tools", scope="module")
def _sqlite_tools() -> str:
    found = shutil.which("sqlite3")
    if found is not None:
        return str(Path(found).parent)
    command = ["nix", "build", "--offline", "--no-link", "--print-out-paths", "--inputs-from", str(ROOT)]
    done = subprocess.run([*command, "nixpkgs#sqlite.bin"], capture_output=True, text=True, timeout=300, check=False)
    if done.returncode != 0:
        pytest.skip("the sqlite3 command is not available offline")
    return done.stdout.split()[0] + "/bin"


def _snapshot(state: Path, tools: str) -> subprocess.CompletedProcess[str]:
    script = state.parent / "snapshot.sh"
    text = SNAPSHOT.read_text("utf-8").replace("state=/var/lib/veilleur", f"state={shlex.quote(str(state))}")
    script.write_text(text, "utf-8")
    environment = {"PATH": f"{tools}:/run/current-system/sw/bin:/usr/bin:/bin"}
    return subprocess.run(
        ["bash", str(script)], capture_output=True, text=True, env=environment, timeout=60, check=False
    )


def _good_state(tmp_path: Path) -> Path:
    state = tmp_path / "state"
    state.mkdir()
    db = sqlite3.connect(state / "veilleur.db")
    with db:
        db.execute("CREATE TABLE pairing (label TEXT)")
        db.execute("INSERT INTO pairing VALUES ('desk 3')")
    db.close()
    return state


def _labels(database: Path) -> list[str]:
    db = sqlite3.connect(database)
    try:
        return [row[0] for row in db.execute("SELECT label FROM pairing")]
    finally:
        db.close()


def test_an_empty_database_file_leaves_the_previous_snapshot_in_place(tmp_path: Path, sqlite_tools: str) -> None:
    state = _good_state(tmp_path)
    assert _snapshot(state, sqlite_tools).returncode == 0
    (state / "veilleur.db").write_bytes(b"")
    assert _snapshot(state, sqlite_tools).returncode != 0
    assert _labels(state / "snapshot" / "veilleur.db") == ["desk 3"]


def test_a_dangling_database_link_leaves_the_previous_snapshot_in_place(tmp_path: Path, sqlite_tools: str) -> None:
    state = _good_state(tmp_path)
    assert _snapshot(state, sqlite_tools).returncode == 0
    (state / "veilleur.db").unlink()
    (state / "veilleur.db").symlink_to(tmp_path / "gone.db")
    assert _snapshot(state, sqlite_tools).returncode != 0
    assert _labels(state / "snapshot" / "veilleur.db") == ["desk 3"]
    assert not (tmp_path / "gone.db").exists()


def test_a_refused_snapshot_says_why_and_leaves_no_work_directory(tmp_path: Path, sqlite_tools: str) -> None:
    state = _good_state(tmp_path)
    (state / "veilleur.db").unlink()
    done = _snapshot(state, sqlite_tools)
    assert done.returncode != 0
    assert "no database" in done.stderr
    assert not list(state.glob(".snapshot.*"))
    assert not (state / "veilleur.db").exists()
