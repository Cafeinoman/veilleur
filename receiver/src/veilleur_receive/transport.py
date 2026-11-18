# SPDX-License-Identifier: EUPL-1.2
"""HTTPS requests to the server: certificates checked, no redirection followed, responses bounded."""

from __future__ import annotations

import http.client
import ssl
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Protocol
from urllib.parse import urlsplit

from veilleur_protocol import DEFAULT_LIMITS

MAX_RESPONSE = DEFAULT_LIMITS.max_package
TIMEOUT = 60.0


@dataclass(frozen=True)
class Reply:
    status: int
    body: bytes = b""


class TransportError(Exception):
    """The server could not be reached, or sent more than a package may hold; `code` says which."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class Transport(Protocol):
    def get(self, target: str, headers: Mapping[str, str]) -> Reply:
        """Send a `GET` for exactly `target` (the signed path and query)."""
        ...


Connect = Callable[[str, int | None], http.client.HTTPConnection]


def _connect(host: str, port: int | None) -> http.client.HTTPConnection:
    return http.client.HTTPSConnection(host, port, timeout=TIMEOUT, context=ssl.create_default_context())


class HttpsTransport:
    def __init__(self, origin: str, connect: Connect = _connect) -> None:
        parts = urlsplit(origin)
        if parts.scheme != "https" or parts.hostname is None:
            raise ValueError("the server is an https origin")
        self._host, self._port, self._connect = parts.hostname, parts.port, connect

    def get(self, target: str, headers: Mapping[str, str]) -> Reply:
        connection = self._connect(self._host, self._port)
        try:
            connection.request("GET", target, headers=dict(headers))
            response = connection.getresponse()
            body = response.read(MAX_RESPONSE + 1)
        except (OSError, http.client.HTTPException) as exc:
            raise TransportError("network_unavailable") from exc
        finally:
            connection.close()
        if len(body) > MAX_RESPONSE:
            raise TransportError("response_too_large")
        return Reply(response.status, body)
