# SPDX-License-Identifier: EUPL-1.2
"""Independent check of lot J8-L3 (R04, R08; SPEC ES-06, ES-10, ES-11; protocol §8).

The WSGI application is called directly: no port is opened.
"""

from __future__ import annotations

import io
import json
import os
import sqlite3
import stat
import threading
from collections.abc import Iterator
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest

from tests.server.fakes import World, make_world
from veilleur.adapters.sqlite.store import SqliteStore
from veilleur.apps.server.wsgi import MAX_BODY, Api
from veilleur.core.domain.model import Pairing
from veilleur.core.services import pairing
from veilleur_protocol import sign_request

UID = "0123456789abcdef0123456789abcdef"


class Untouchable(io.RawIOBase):
    """A request body that records any attempt to read it, and fails it."""

    def __init__(self) -> None:
        self.touched = False

    def _fail(self, *args: Any, **kwargs: Any) -> bytes:
        self.touched = True
        raise AssertionError("the request body was read")

    read = readline = readlines = readinto = readall = _fail  # type: ignore[assignment]

    def __iter__(self) -> Iterator[bytes]:
        self._fail()
        return iter(())


@pytest.fixture
def world(tmp_path: Path) -> Iterator[World]:
    w = make_world(tmp_path / "state")
    yield w
    w.app.close()


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def _api(world: World) -> tuple[Api, Clock]:
    """The default application, as `serve` builds it, with its monotonic clocks replaced."""
    api = Api(world.app.core)
    clock = Clock()
    api.refusals._clock = clock
    api.limiter._clock = clock
    return api, clock


def _call(
    api: Api,
    world: World,
    p: Pairing | None,
    method: str,
    target: str,
    body: bytes = b"",
    *,
    headers: dict[str, str] | None = None,
    stream: Any = None,
    length: str | None = None,
    at_offset: timedelta = timedelta(0),
) -> tuple[int, dict[str, str], bytes]:
    env: dict[str, Any] = {
        "REQUEST_METHOD": method,
        "REQUEST_URI": target,
        "CONTENT_LENGTH": length if length is not None else str(len(body)),
        "wsgi.input": stream if stream is not None else io.BytesIO(body),
    }
    if p is not None:
        signed = sign_request(p.secret, p.key_id, method, target, body, world.clock.now() + at_offset)
        env["HTTP_AUTHORIZATION"] = signed.authorization
        env["HTTP_X_VEILLEUR_DATE"] = signed.date
    for name, value in (headers or {}).items():
        env["HTTP_" + name.upper().replace("-", "_")] = value
    captured: dict[str, Any] = {}

    def start_response(status: str, response_headers: list[tuple[str, str]]) -> None:
        captured["status"], captured["headers"] = status, dict(response_headers)

    data = b"".join(api(env, start_response))
    return int(captured["status"].split()[0]), captured["headers"], data


def _code(reply: tuple[int, dict[str, str], bytes]) -> tuple[int, str]:
    return reply[0], json.loads(reply[2])["code"]


# --- Criterion 1: refused before the body is read ---------------------------------------------------------------


def _date(world: World, offset: timedelta = timedelta(0)) -> str:
    return sign_request(b"\0" * 32, "0" * 16, "GET", "/", b"", world.clock.now() + offset).date


@pytest.mark.parametrize(
    "case",
    ["no_header", "malformed_header", "short_mac", "no_date", "bad_date", "stale_past", "stale_future", "bad_uid"],
)
def test_requests_refused_by_header_or_date_never_read_the_body(world: World, case: str) -> None:
    api, _ = _api(world)
    p = pairing.create_pairing(world.app.core, "desk 1")
    good = sign_request(p.secret, p.key_id, "PUT", f"/v1/subscriptions/{UID}", b"x" * 10, world.clock.now())
    headers: dict[str, str] = {"X-Veilleur-Date": good.date, "Authorization": good.authorization}
    target = f"/v1/subscriptions/{UID}"
    expected = "bad_authorization"
    if case == "no_header":
        del headers["Authorization"]
    elif case == "malformed_header":
        headers["Authorization"] = "Bearer abc"
    elif case == "short_mac":
        headers["Authorization"] = f"Veilleur {p.key_id}:AAAA"
    elif case == "no_date":
        del headers["X-Veilleur-Date"]
        expected = "bad_date"
    elif case == "bad_date":
        headers["X-Veilleur-Date"] = "yesterday"
        expected = "bad_date"
    elif case == "stale_past":
        headers["X-Veilleur-Date"] = _date(world, -timedelta(minutes=6))
        expected = "stale_date"
    elif case == "stale_future":
        headers["X-Veilleur-Date"] = _date(world, timedelta(minutes=6))
        expected = "stale_date"
    elif case == "bad_uid":
        target = "/v1/subscriptions/NOT-A-UID"
    stream = Untouchable()
    reply = _call(api, world, None, "PUT", target, headers=headers, stream=stream, length="10")
    assert _code(reply) == (401, expected)
    assert not stream.touched


def test_an_unknown_key_id_never_reads_the_body(world: World) -> None:
    api, _ = _api(world)
    stranger = Pairing("f" * 16, "nobody", os.urandom(32), world.clock.now())
    stream = Untouchable()
    reply = _call(api, world, stranger, "PUT", f"/v1/subscriptions/{UID}", b"0123456789", stream=stream)
    assert _code(reply) == (401, "bad_authorization")
    assert not stream.touched


def test_an_unauthenticated_huge_body_is_a_401_not_a_413(world: World) -> None:
    api, _ = _api(world)
    stream = Untouchable()
    reply = _call(api, world, None, "PUT", f"/v1/subscriptions/{UID}", stream=stream, length=str(10 * MAX_BODY))
    assert _code(reply) == (401, "bad_authorization")
    assert not stream.touched


def test_a_known_key_id_still_gets_its_body_checked(world: World) -> None:
    """Order of §8 kept: the MAC, over the body's hash, is checked last; 413 for an authenticated oversized body."""
    api, _ = _api(world)
    p = pairing.create_pairing(world.app.core, "desk 1")
    body = b"{}"
    signed = sign_request(p.secret, p.key_id, "PUT", f"/v1/subscriptions/{UID}", b"other", world.clock.now())
    headers = {"Authorization": signed.authorization, "X-Veilleur-Date": signed.date}
    assert _code(_call(api, world, None, "PUT", f"/v1/subscriptions/{UID}", body, headers=headers)) == (
        401,
        "bad_authorization",
    )
    big = _call(api, world, p, "PUT", f"/v1/subscriptions/{UID}", length=str(MAX_BODY + 1))
    assert _code(big) == (413, "body_too_large")


# --- Criterion 2: 300 `401` per minute, then `429` ---------------------------------------------------------------


def test_the_301st_unauthenticated_request_in_a_minute_gets_429_without_reading_the_body(world: World) -> None:
    api, clock = _api(world)
    p = pairing.create_pairing(world.app.core, "desk 1")
    for i in range(300):
        clock.now = 1000.0 + i * 0.19  # all within 57 seconds
        assert _call(api, world, None, "GET", "/v1/collectors")[0] == 401
    clock.now = 1059.5
    stream = Untouchable()
    reply = _call(api, world, None, "PUT", f"/v1/subscriptions/{UID}", stream=stream, length="10")
    assert _code(reply) == (429, "rate_limited")
    assert not stream.touched
    # a valid authenticated request sent next gets its normal answer
    assert _call(api, world, p, "GET", "/v1/collectors")[0] == 200
    assert _call(api, world, p, "GET", "/v1/subscriptions")[0] == 200


def test_authenticated_requests_are_not_counted(world: World) -> None:
    api, _ = _api(world)
    p = pairing.create_pairing(world.app.core, "desk 1")
    for _ in range(299):
        assert _call(api, world, None, "GET", "/v1/collectors")[0] == 401
    for _ in range(100):
        assert _call(api, world, p, "GET", "/v1/collectors")[0] == 200
    assert _call(api, world, None, "GET", "/v1/collectors")[0] == 401  # 300th
    assert _call(api, world, None, "GET", "/v1/collectors")[0] == 429  # 301st


def test_refusals_beyond_the_limit_do_not_extend_the_window(world: World) -> None:
    """A `429` is not a `401`: a flood past the limit must not keep the process locked forever."""
    api, clock = _api(world)
    for _ in range(300):
        assert _call(api, world, None, "GET", "/v1/collectors")[0] == 401
    for second in range(1, 60):
        clock.now = 1000.0 + second
        assert _call(api, world, None, "GET", "/v1/collectors")[0] == 429
    clock.now = 1060.0
    assert _call(api, world, None, "GET", "/v1/collectors")[0] == 401


def test_a_bad_mac_with_a_known_key_id_counts_and_does_not_eat_the_pairing_quota(world: World) -> None:
    api, _ = _api(world)
    p = pairing.create_pairing(world.app.core, "desk 1")
    signed = sign_request(p.secret, p.key_id, "GET", "/v1/subscriptions", b"", world.clock.now())
    forged = {"Authorization": signed.authorization, "X-Veilleur-Date": signed.date}
    for _ in range(300):
        assert _call(api, world, None, "GET", "/v1/collectors", headers=forged)[0] == 401
    assert _code(_call(api, world, None, "GET", "/v1/collectors", headers=forged)) == (429, "rate_limited")
    # the pairing's own limit (120 per minute) is untouched by the forged requests
    for _ in range(120):
        assert _call(api, world, p, "GET", "/v1/collectors")[0] == 200


def test_the_limit_is_shared_by_threads(world: World) -> None:
    api, _ = _api(world)
    codes: list[int] = []
    lock = threading.Lock()

    def worker() -> None:
        for _ in range(40):
            code = _call(api, world, None, "GET", "/v1/collectors")[0]
            with lock:
                codes.append(code)

    threads = [threading.Thread(target=worker) for _ in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert codes.count(401) == 300
    assert codes.count(429) == 100


# --- Criterion 3: database private whatever the umask -------------------------------------------------------------


def _mode(path: Path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


@pytest.mark.parametrize("mask", [0o022, 0o002, 0o000])
def test_the_service_database_is_created_private(tmp_path: Path, mask: int) -> None:
    previous = os.umask(mask)
    try:
        w = make_world(tmp_path / "state")
        pairing.create_pairing(w.app.core, "desk 1")
        db = Path(w.app.config.database)
        files = [db, Path(f"{db}-wal"), Path(f"{db}-shm")]
        present = [f for f in files if f.exists()]
        assert db in present and len(present) == 3
        assert {f.name: _mode(f) for f in present} == {f.name: 0o600 for f in present}
        w.app.close()
    finally:
        os.umask(previous)


def test_an_older_database_and_its_wal_files_are_tightened(tmp_path: Path) -> None:
    previous = os.umask(0o022)
    try:
        path = tmp_path / "veilleur.db"
        raw = sqlite3.connect(path)
        raw.execute("PRAGMA journal_mode = WAL")
        raw.execute("CREATE TABLE t (x)")
        raw.execute("INSERT INTO t VALUES (1)")
        raw.commit()
        # keep the connection open so that -wal and -shm stay on disk
        for f in (path, Path(f"{path}-wal"), Path(f"{path}-shm")):
            f.chmod(0o666)
        SqliteStore(path).close()
        raw.close()
        for f in (path, Path(f"{path}-wal"), Path(f"{path}-shm")):
            if f.exists():
                assert _mode(f) == 0o600, f.name
    finally:
        os.umask(previous)


def test_the_migration_backup_is_private_whatever_the_umask(tmp_path: Path) -> None:
    """The backup copies every pairing secret; it is checked like the database (ES-10)."""
    previous = os.umask(0o022)
    try:
        path = tmp_path / "veilleur.db"
        raw = sqlite3.connect(path)
        raw.execute("CREATE TABLE legacy (x)")
        raw.close()
        store = SqliteStore(path, backup_dir=tmp_path / "backups")
        assert store.backup is not None
        assert _mode(store.backup) == 0o600
        store.close()
    finally:
        os.umask(previous)
