# SPDX-License-Identifier: EUPL-1.2
"""The receiver's HTTPS requests, on a fake connection: no port is opened."""

from __future__ import annotations

import http.client
from dataclasses import dataclass, field
from typing import Any

import pytest

from veilleur_receive.transport import MAX_RESPONSE, HttpsTransport, TransportError


@dataclass
class FakeResponse:
    status: int = 200
    body: bytes = b"ok"

    def read(self, amount: int) -> bytes:
        return self.body[:amount]


@dataclass
class FakeConnection:
    response: FakeResponse = field(default_factory=FakeResponse)
    fail: Exception | None = None
    sent: list[tuple[str, str, dict[str, str]]] = field(default_factory=list)
    closed: bool = False

    def request(self, method: str, target: str, headers: dict[str, str]) -> None:
        if self.fail:
            raise self.fail
        self.sent.append((method, target, headers))

    def getresponse(self) -> FakeResponse:
        return self.response

    def close(self) -> None:
        self.closed = True


def transport(connection: FakeConnection, origin: str = "https://veille.example.org:8443") -> HttpsTransport:
    seen: list[tuple[str, int | None]] = []

    def connect(host: str, port: int | None) -> Any:
        seen.append((host, port))
        return connection

    result = HttpsTransport(origin, connect)
    result.seen = seen  # type: ignore[attr-defined]
    return result


def test_the_target_is_sent_exactly_as_signed_and_the_connection_closed() -> None:
    connection = FakeConnection()
    client = transport(connection)
    reply = client.get("/v1/subscriptions?x=%41", {"Authorization": "a"})
    assert (reply.status, reply.body) == (200, b"ok")
    assert connection.sent == [("GET", "/v1/subscriptions?x=%41", {"Authorization": "a"})]
    assert connection.closed and client.seen == [("veille.example.org", 8443)]  # type: ignore[attr-defined]


def test_a_redirection_is_not_followed() -> None:
    connection = FakeConnection(FakeResponse(302, b""))
    assert transport(connection).get("/v1/subscriptions", {}).status == 302
    assert len(connection.sent) == 1


@pytest.mark.parametrize("failure", [OSError("refused"), http.client.BadStatusLine("x"), TimeoutError()])
def test_a_network_failure_has_a_stable_code(failure: Exception) -> None:
    connection = FakeConnection(fail=failure)
    with pytest.raises(TransportError) as caught:
        transport(connection).get("/", {})
    assert caught.value.code == "network_unavailable" and connection.closed


def test_a_response_larger_than_a_package_is_refused() -> None:
    with pytest.raises(TransportError) as caught:
        transport(FakeConnection(FakeResponse(200, b"x" * (MAX_RESPONSE + 1)))).get("/", {})
    assert caught.value.code == "response_too_large"


def test_only_an_https_origin_is_accepted() -> None:
    with pytest.raises(ValueError, match="https"):
        HttpsTransport("http://veille.example.org")
