# SPDX-License-Identifier: EUPL-1.2
"""Third pass over batch G5: the internal port against the public ports of Caddy, and the scope of section 10.

The NixOS modules are evaluated by `nix eval`, offline. No test opens a port or reaches the network.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[2]
PROBE = Path(__file__).with_name("g5_pass3_probe.nix")
NIX_TIMEOUT = 580
CADDY_MESSAGE = "public ports of Caddy"

REFUSED_PORTS = [
    "service: 80",
    "service: 443",
    "service: 8443",
    "service, ntfy with its own name: 80",
    "service, ntfy with its own name: 443",
    "service, no ntfy: 80",
    "service, no ntfy: 443",
    "service, external ntfy: 443",
    "container: 80",
    "container: 443",
    "container: 8443",
    "container, ntfy with its own name: 443",
    "container, no ntfy: 80",
]
ACCEPTED_PORTS = [
    "service, ntfy with its own name: 8443",
    "service, no ntfy: 8443",
    "service, external ntfy: 8443",
    "service, external proxy: 80",
    "service, external proxy: 443",
    "service, external proxy: 8443",
    "service, external proxy and built-in ntfy: 8443",
    "service: 79",
    "service: 81",
    "service: 442",
    "service: 444",
    "service: 8442",
    "service: 8444",
    "container, ntfy with its own name: 8443",
    "container, no ntfy: 8443",
    "container, external proxy: 443",
    "container, external proxy: 8443",
]
REPORTED_FORMS = [
    "sshd on 80",
    "sshd on 443",
    "sshd on 8443",
    "sshd on the second of its ports",
    "sshd on the internal port",
    "sshd on the port of the built-in ntfy",
    "container: sshd on 443",
    "container: sshd on 8443",
    "nginx default port on the internal port",
    "nginx default port on the port of the built-in ntfy",
    "nginx default port on the internal address",
    "nginx default port on IPv6 wildcard only",
]
ACCEPTED_FORMS = [
    "sshd on its usual port",
    "sshd disabled on 443",
    "sshd on 443 behind an external proxy",
    "sshd on 8443, ntfy with its own name",
    "sshd on 8443, no ntfy",
    "container: sshd on its usual port",
    "container: sshd on 443 behind an external proxy",
    "nginx in front on its usual ports",
    "nginx in front, built-in ntfy",
    "nginx default port on another address of the site",
    "nginx default port replaced by an explicit entry",
    "nginx default port without any site",
    "nginx disabled on the internal port",
]


def _nix_eval(attribute: str) -> subprocess.CompletedProcess[str]:
    expression = f'(import {PROBE} {{ root = "{ROOT}"; }}).{attribute}'
    command = ["nix", "eval", "--offline", "--impure", "--json", "--expr", expression]
    return subprocess.run(command, capture_output=True, text=True, timeout=NIX_TIMEOUT, check=False)


@pytest.fixture(name="nix", scope="module")
def _nix() -> None:
    if shutil.which("nix") is None:
        pytest.skip("Nix is not installed")


@pytest.fixture(name="probe", scope="module")
def _probe(nix: None) -> dict[str, Any]:
    wanted = "{ inherit (probe) refusedPort acceptedPort reportedForm acceptedForm outside sshdElsewhere; }"
    expression = f'let probe = import {PROBE} {{ root = "{ROOT}"; }}; in {wanted}'
    command = ["nix", "eval", "--offline", "--impure", "--json", "--expr", expression]
    done = subprocess.run(command, capture_output=True, text=True, timeout=NIX_TIMEOUT, check=False)
    assert done.returncode == 0, done.stderr[-3000:]
    loaded: dict[str, Any] = json.loads(done.stdout)
    return loaded


@pytest.mark.parametrize("case", REFUSED_PORTS)
def test_the_internal_port_is_refused_on_a_port_caddy_takes(probe: dict[str, Any], case: str) -> None:
    assert any(CADDY_MESSAGE in message for message in probe["refusedPort"][case]), probe["refusedPort"][case]


@pytest.mark.parametrize("case", ACCEPTED_PORTS)
def test_the_internal_port_is_accepted_where_caddy_does_not_take_it(probe: dict[str, Any], case: str) -> None:
    assert probe["acceptedPort"][case] == []


@pytest.mark.parametrize("case", REPORTED_FORMS)
def test_a_form_listed_in_section_10_is_reported(probe: dict[str, Any], case: str) -> None:
    assert probe["reportedForm"][case], f"no assertion for: {case}"


@pytest.mark.parametrize("case", ACCEPTED_FORMS)
def test_a_form_without_conflict_stays_accepted(probe: dict[str, Any], case: str) -> None:
    assert probe["acceptedForm"][case] == []


@pytest.mark.parametrize("target", ["service", "container"])
def test_the_build_of_the_host_stops_on_the_internal_port(nix: None, target: str) -> None:
    """The container's assertion lives in the inner system: it has to stop the build of the host too."""
    done = _nix_eval(f"hostBuild.{target}")
    assert done.returncode != 0, "the host was built with services.veilleur.port = 8443"
    assert CADDY_MESSAGE in done.stderr, done.stderr[-3000:]


@pytest.mark.xfail(strict=True, reason="minor: port 2019 is accepted, and Caddy's admin endpoint then fails to bind")
def test_the_internal_port_is_not_the_admin_port_of_caddy(probe: dict[str, Any]) -> None:
    assert probe["outside"]["caddy admin port"]


@pytest.mark.xfail(strict=True, reason="outside the specification: section 10 names defaultHTTPListenPort only")
def test_the_tls_default_port_of_nginx_is_reported(probe: dict[str, Any]) -> None:
    assert probe["outside"]["nginx TLS default port"]


@pytest.mark.xfail(strict=True, reason="outside the specification: section 10 names services.openssh.ports only")
def test_a_port_given_in_the_listen_addresses_of_sshd_is_reported(probe: dict[str, Any]) -> None:
    assert probe["outside"]["sshd listenAddresses port"]


@pytest.mark.xfail(strict=True, reason="outside the specification: the address sshd is bound to is not compared")
def test_sshd_bound_to_another_address_is_accepted(probe: dict[str, Any]) -> None:
    assert probe["sshdElsewhere"] == []
