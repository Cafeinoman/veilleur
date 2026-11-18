# SPDX-License-Identifier: EUPL-1.2
"""Deployment files: what the virtual machine tests cannot see, or would only see for one of the two installations."""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
DEPLOY = ROOT / "deploy"
SYSTEMD = DEPLOY / "systemd"
UNITS = ("veilleur.service", "veilleur-round.service", "veilleur-snapshot.service")
# Set apart in the NixOS module, or specific to one unit.
NOT_HARDENING = {"ExecStart", "Restart", "RestartSec", "Type", "PrivateNetwork"}


def _directives(unit: str) -> dict[str, list[str]]:
    found: dict[str, list[str]] = {}
    section = ""
    for line in (SYSTEMD / unit).read_text("utf-8").splitlines():
        if line.startswith("["):
            section = line
        elif section == "[Service]" and "=" in line and not line.startswith("#"):
            name, value = line.split("=", 1)
            found.setdefault(name, []).append(value)
    return found


def _module_hardening() -> set[str]:
    text = (DEPLOY / "nixos" / "module.nix").read_text("utf-8")
    match = re.search(r"^  hardening = \{\n(.*?)^  \};", text, re.MULTILINE | re.DOTALL)
    assert match is not None
    return set(re.findall(r"^    (\w+) =", match[1], re.MULTILINE))


@pytest.mark.parametrize("unit", UNITS)
def test_the_fallback_units_are_hardened_like_the_nixos_module(unit: str) -> None:
    assert set(_directives(unit)) - NOT_HARDENING == _module_hardening()


@pytest.mark.parametrize("unit", UNITS)
def test_a_fallback_unit_keeps_no_capability_and_a_private_umask(unit: str) -> None:
    directives = _directives(unit)
    assert directives["CapabilityBoundingSet"] == [""]
    assert directives["AmbientCapabilities"] == [""]
    assert directives["UMask"] == ["0077"]
    assert directives["User"] == ["veilleur"]
    assert directives["ProtectSystem"] == ["strict"]


def test_the_snapshot_unit_has_no_network() -> None:
    directives = _directives("veilleur-snapshot.service")
    assert directives["PrivateNetwork"] == ["yes"]
    assert directives["RestrictAddressFamilies"] == ["none"]


def test_the_caddyfile_keeps_no_access_log() -> None:
    lines = [line.strip() for line in (SYSTEMD / "Caddyfile").read_text("utf-8").splitlines()]
    assert not [line for line in lines if line.split(" ")[0] == "log"]


def test_the_ntfy_excerpt_refuses_anonymous_clients() -> None:
    text = (SYSTEMD / "ntfy-server.yml").read_text("utf-8")
    assert 'auth-default-access: "deny-all"' in text
    assert 'log-level: "error"' in text


def test_the_example_configuration_is_valid_and_holds_no_secret() -> None:
    from veilleur.apps.server import config

    data = tomllib.loads((SYSTEMD / "config.toml").read_text("utf-8"))
    parsed = config.parse(data)
    assert parsed.ntfy is not None and parsed.ntfy.token_file is not None
    assert "tk_" not in (SYSTEMD / "config.toml").read_text("utf-8")


def test_every_nix_file_has_the_licence_header() -> None:
    files = [ROOT / "flake.nix", *DEPLOY.rglob("*.nix")]
    spdx = "# SPDX-License-Identifier: EUPL-1.2"
    missing = [str(p.relative_to(ROOT)) for p in files if not p.read_text("utf-8").startswith(spdx)]
    assert not missing


def test_the_flake_exposes_both_modules() -> None:
    text = (ROOT / "flake.nix").read_text("utf-8")
    assert re.search(r"nixosModules = \{\s+default = serviceModule;\s+container = containerModule;", text)
