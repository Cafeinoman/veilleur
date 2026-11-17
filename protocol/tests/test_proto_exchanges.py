# SPDX-License-Identifier: EUPL-1.2
"""Pairing codes, request authentication, sealed subscriptions, test vectors."""

from __future__ import annotations

import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from conftest import KEY_ID, NOW, OTHER_UID, SECRET, UID
from veilleur_protocol import (
    Ntfy,
    PairingCode,
    ProtocolError,
    SigningKey,
    b64u_encode,
    decode_pairing_code,
    open_subscription,
    request_scope,
    seal_subscription,
    sign_request,
    verify_request,
)

ROOT = Path(__file__).resolve().parents[2]


def test_pairing_code_round_trip(key: SigningKey) -> None:
    code = PairingCode(
        "https://veille.example.org", KEY_ID, SECRET, key.public_key, Ntfy("https://ntfy.example.org", "t")
    )
    text = code.encode()
    assert text.startswith("VEIL1:") and "\n" not in text
    assert decode_pairing_code(f"  {text}\n") == code
    folder = PairingCode("folder:", KEY_ID, SECRET, key.public_key)
    assert decode_pairing_code(folder.encode()) == folder
    assert SECRET.hex() not in repr(code) and b64u_encode(SECRET) not in repr(code)


@pytest.mark.parametrize(
    "server",
    [
        "http://veille.example.org",
        "https://veille.example.org/path",
        "https://user@veille.example.org",
        "https://veille.example.org?x=1",
        "https://",
        "https://veille.example.org:99999",
        "folder:/tmp",
        "",
    ],
)
def test_pairing_code_refuses_servers_that_are_not_https_origins(key: SigningKey, server: str) -> None:
    with pytest.raises(ProtocolError) as error:
        PairingCode(server, KEY_ID, SECRET, key.public_key)
    assert error.value.code == "bad_pairing_code"


@pytest.mark.parametrize("text", ["", "VEIL1:", "VEIL1:%%%", "VEIL1:" + b64u_encode(b"[]"), "VEIL1:" + "A" * 5000])
def test_pairing_code_refuses_garbage(text: str) -> None:
    with pytest.raises(ProtocolError) as error:
        decode_pairing_code(text)
    assert error.value.code == "bad_pairing_code"


def test_request_round_trip_and_scope() -> None:
    path = f"/v1/subscriptions/{UID}/reports?after=3"
    assert request_scope(path) == UID
    assert request_scope(f"/v1/subscriptions/{UID}") == UID
    assert request_scope("/v1/collectors") is None
    headers = sign_request(SECRET, KEY_ID, "GET", path, b"", NOW)
    assert headers.authorization.startswith(f"Veilleur {KEY_ID}:") and headers.date == "2026-11-17T06:00:00Z"
    for delta in (timedelta(0), timedelta(minutes=5), -timedelta(minutes=5)):
        key_id = verify_request(
            SECRET, "GET", path, b"", authorization=headers.authorization, date=headers.date, now=NOW + delta
        )
        assert key_id == KEY_ID


def test_requests_are_refused_when_anything_differs() -> None:
    path = f"/v1/subscriptions/{UID}"
    headers = sign_request(SECRET, KEY_ID, "PUT", path, b"body", NOW)

    def code(
        *,
        secret: bytes = SECRET,
        method: str = "PUT",
        path_and_query: str = path,
        body: bytes = b"body",
        authorization: str | None = headers.authorization,
        date: str | None = headers.date,
        now: datetime = NOW,
    ) -> str:
        with pytest.raises(ProtocolError) as error:
            verify_request(secret, method, path_and_query, body, authorization=authorization, date=date, now=now)
        return error.value.code

    assert code(now=NOW + timedelta(minutes=5, seconds=1)) == "stale_date"
    assert code(now=NOW - timedelta(minutes=5, seconds=1)) == "stale_date"
    assert code(date="2026-11-17T06:00:01Z") == "bad_authorization"
    assert code(date=None) == "bad_date"
    assert code(authorization=None) == "bad_authorization"
    assert code(authorization=headers.authorization.replace("Veilleur", "veilleur")) == "bad_authorization"
    assert code(body=b"other") == "bad_authorization"
    assert code(method="POST") == "bad_authorization"
    assert code(path_and_query=f"/v1/subscriptions/{OTHER_UID}") == "bad_authorization"
    assert code(path_and_query="/v1/subscriptions/not-a-uid") == "bad_authorization"
    assert code(secret=bytes(32)) == "bad_authorization"


def test_sealed_subscription_round_trip_and_refusals() -> None:
    body = seal_subscription(SECRET, UID, 3, {"collector": "rss", "params": {"url": "https://example.org/feed"}})
    assert b"example.org" not in body
    assert open_subscription(SECRET, UID, body) == (
        3,
        {"collector": "rss", "params": {"url": "https://example.org/feed"}},
    )
    for secret, uid, data, expected in (
        (SECRET, OTHER_UID, body, "uid_mismatch"),
        (bytes(32), UID, body, "decryption_failed"),
        (SECRET, UID, body[:-1] + bytes([body[-1] ^ 1]), "decryption_failed"),
        (SECRET, UID, body + bytes(1024 * 1024), "too_large"),
    ):
        with pytest.raises(ProtocolError) as error:
            open_subscription(secret, uid, data)
        assert error.value.code == expected


def test_vectors_are_what_the_library_produces() -> None:
    result = subprocess.run(
        [sys.executable, str(ROOT / "tools" / "protocol_vectors.py"), "--check"], capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr
