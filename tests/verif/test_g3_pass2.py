# SPDX-License-Identifier: EUPL-1.2
"""Independent check of milestone G3, second pass: the whole request is capped (ES-08, §10 of 2026-11-18: 30 s) and
the `regex` filter refuses patterns that backtrack catastrophically (§10 of 2026-11-18).

No network: the socket transport is fed through a `socket.socketpair()` (no port is opened). Regular expressions are
run in a child process killed after a few seconds, so that a catastrophic one cannot hang the test session.
"""

from __future__ import annotations

import contextlib
import socket
import subprocess
import sys
import threading
import time
from collections.abc import Callable, Iterator
from typing import Any

import pytest

from tests.server.http_fakes import PUBLIC
from veilleur.adapters.filters import compile_pattern
from veilleur.adapters.http.transport import SocketTransport

# --- ES-08 / §10: the whole request is capped --------------------------------------------------------------------


def _serve(
    monkeypatch: pytest.MonkeyPatch, behaviour: Callable[[socket.socket, threading.Event], None]
) -> Iterator[None]:
    server, near = socket.socketpair()
    stop = threading.Event()

    def fake_connect(address: Any, timeout: float | None = None, *args: Any, **kwargs: Any) -> socket.socket:
        near.settimeout(timeout)
        return near

    def run() -> None:
        with contextlib.suppress(OSError):
            behaviour(server, stop)

    monkeypatch.setattr(socket, "create_connection", fake_connect)
    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    yield
    stop.set()
    server.close()
    thread.join(2)


def _drip(server: socket.socket, stop: threading.Event, seconds: float = 6.0) -> None:
    end = time.monotonic() + seconds
    while time.monotonic() < end and not stop.is_set():
        server.sendall(b"x")
        time.sleep(0.2)


def _request(scheme: str, timeout: float = 1.0) -> tuple[float, BaseException | None]:
    started = time.monotonic()
    try:
        SocketTransport().request(
            scheme=scheme, address=PUBLIC, host="slow.example.org", port=443 if scheme == "https" else 80,
            target="/", headers={"Host": "slow.example.org"}, timeout=timeout, max_bytes=100_000,
        )  # fmt: skip
    except BaseException as exc:  # the kind of error is what is checked
        return time.monotonic() - started, exc
    return time.monotonic() - started, None


def test_dripped_tls_handshake_is_cut_at_the_cap(monkeypatch: pytest.MonkeyPatch) -> None:
    """A source that answers the ClientHello with a TLS record announced long and sent one byte at a time."""

    def behaviour(server: socket.socket, stop: threading.Event) -> None:
        server.recv(65536)  # ClientHello
        server.sendall(b"\x16\x03\x03\x40\x00")  # handshake record of 16 KiB
        _drip(server, stop)

    serving = _serve(monkeypatch, behaviour)
    next(serving)
    elapsed, error = _request("https")
    next(serving, None)
    assert elapsed < 3.0, f"a 1 s request lasted {elapsed:.1f} s"
    assert isinstance(error, TimeoutError), repr(error)


def test_dripped_headers_raise_a_timeout_not_a_network_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """The client maps `TimeoutError` to the stable code `timeout`, other `OSError`s to `network_error`."""

    def behaviour(server: socket.socket, stop: threading.Event) -> None:
        server.recv(65536)
        server.sendall(b"HTTP/1.1 200 OK\r\nContent-Type: text/plain\r\nX-Slow: ")
        _drip(server, stop)

    serving = _serve(monkeypatch, behaviour)
    next(serving)
    elapsed, error = _request("http")
    next(serving, None)
    assert elapsed < 3.0, f"a 1 s request lasted {elapsed:.1f} s"
    assert isinstance(error, TimeoutError), repr(error)


def test_dripped_body_is_still_cut_at_the_cap(monkeypatch: pytest.MonkeyPatch) -> None:
    def behaviour(server: socket.socket, stop: threading.Event) -> None:
        server.recv(65536)
        server.sendall(b"HTTP/1.1 200 OK\r\nContent-Type: text/plain\r\nContent-Length: 1000\r\n\r\n")
        _drip(server, stop)

    serving = _serve(monkeypatch, behaviour)
    next(serving)
    elapsed, error = _request("http")
    next(serving, None)
    assert elapsed < 3.0, f"a 1 s request lasted {elapsed:.1f} s"
    assert isinstance(error, TimeoutError), repr(error)


def test_a_prompt_answer_still_succeeds_and_leaves_no_watchdog(monkeypatch: pytest.MonkeyPatch) -> None:
    def behaviour(server: socket.socket, stop: threading.Event) -> None:
        server.recv(65536)
        server.sendall(b"HTTP/1.1 200 OK\r\nContent-Type: text/plain\r\nContent-Length: 2\r\n\r\nok")

    before = {t.ident for t in threading.enumerate()}
    serving = _serve(monkeypatch, behaviour)
    next(serving)
    response = SocketTransport().request(
        scheme="http", address=PUBLIC, host="ok.example.org", port=80, target="/",
        headers={"Host": "ok.example.org"}, timeout=5.0, max_bytes=1000,
    )  # fmt: skip
    next(serving, None)
    assert (response.status, response.body, response.headers["content-type"]) == (200, b"ok", "text/plain")
    time.sleep(0.2)
    timers = [t for t in threading.enumerate() if isinstance(t, threading.Timer) and t.ident not in before]
    assert not timers, "the watchdog of a finished request is still alive"


# --- §10: the regex filter refuses patterns that backtrack catastrophically --------------------------------------

_PROBE = """
import sys, time
from veilleur.adapters.filters import compile_pattern
try:
    rx = compile_pattern(sys.argv[1], case=False)
except ValueError:
    print("refused"); sys.exit(0)
rx.search(sys.argv[2] * int(sys.argv[3]))
print("fast")
"""


def _fate(pattern: str, unit: str, count: int, limit: float = 5.0) -> str:
    """'refused', 'fast' (accepted and searched within `limit`) or 'slow' (accepted, and still searching)."""
    try:
        done = subprocess.run(
            [sys.executable, "-c", _PROBE, pattern, unit, str(count)],
            capture_output=True, text=True, timeout=limit, check=True,
        )  # fmt: skip
    except subprocess.TimeoutExpired:
        return "slow"
    return done.stdout.strip()


@pytest.mark.parametrize(
    ("pattern", "unit", "count"),
    [
        (r".*.*.*.*=", "a", 400),  # B2 of the first pass
        (r"a*a*a*a*b", "a", 400),
        (r".{0,100}.{0,100}.{0,100}.{0,100}=", "a", 400),  # successive bounded repetitions
        (r"(?:.{0,50}){4}=", "a", 400),  # nested bounded repetitions
        ("[\u0430-\u044f]+" * 4 + "=", "\u0436", 300),  # Cyrillic range: outside the sample of characters
        ("[\u03b1-\u03c9]+" * 3 + "=", "\u03bb", 1500),  # Greek range: outside the sample of characters
    ],
)
def test_no_accepted_pattern_backtracks_catastrophically(pattern: str, unit: str, count: int) -> None:
    """Either the pattern is refused, or a search on a few hundred characters ends within 5 s."""
    assert _fate(pattern, unit, count) != "slow", f"{pattern!r} accepted, and still searching after 5 s"


@pytest.mark.parametrize(
    "pattern", [r"\d+-\d+", r"\w+\s+\w+", r"[^,]+,[^,]+", r"foo.*bar", r"https?://\S+\.pdf", r"\w+\.\w+"]
)
def test_usual_patterns_stay_accepted(pattern: str) -> None:
    compile_pattern(pattern, case=False)


def test_usual_email_pattern_is_accepted() -> None:
    """Refused by the static analysis of pass 2; accepted since the RE2 engine (pass 3)."""
    compile_pattern(r"[\w.-]+@[\w.-]+\.\w+", case=False)
