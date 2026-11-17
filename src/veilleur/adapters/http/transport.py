# SPDX-License-Identifier: EUPL-1.2
"""Sockets of the networked client: a connection to an address already checked by the SSRF guard.

The host name is used only for the `Host` header and TLS (SNI and certificate check), never resolved again here.
No proxy from the environment is used.
"""

from __future__ import annotations

import http.client
import socket
import ssl
import time
from collections.abc import Mapping

from .client import RawResponse


class _Connection(http.client.HTTPConnection):
    def __init__(self, address: str, host: str, port: int, timeout: float) -> None:
        super().__init__(host, port, timeout=timeout)
        self._address = address

    def connect(self) -> None:
        self.sock = socket.create_connection((self._address, self.port), self.timeout)


class _TlsConnection(http.client.HTTPSConnection):
    def __init__(self, address: str, host: str, port: int, timeout: float, context: ssl.SSLContext) -> None:
        super().__init__(host, port, timeout=timeout, context=context)
        self._address = address
        self._tls = context

    def connect(self) -> None:
        sock = socket.create_connection((self._address, self.port), self.timeout)
        self.sock = self._tls.wrap_socket(sock, server_hostname=self.host)


class SocketTransport:
    def __init__(self, context: ssl.SSLContext | None = None) -> None:
        self._context = context or ssl.create_default_context()

    def connection(self, scheme: str, address: str, host: str, port: int, timeout: float) -> http.client.HTTPConnection:
        if scheme == "https":
            return _TlsConnection(address, host, port, timeout, self._context)
        return _Connection(address, host, port, timeout)

    def request(
        self,
        *,
        scheme: str,
        address: str,
        host: str,
        port: int,
        target: str,
        headers: Mapping[str, str],
        timeout: float,
        max_bytes: int,
    ) -> RawResponse:
        deadline = time.monotonic() + timeout
        connection = self.connection(scheme, address, host, port, timeout)
        try:
            connection.request("GET", target, headers=dict(headers))
            response = connection.getresponse()
            chunks: list[bytes] = []
            size = 0
            while size <= max_bytes:  # read in chunks, so that a slow source cannot hold the round past `timeout`
                if time.monotonic() > deadline:
                    raise TimeoutError
                chunk = response.read1(min(65536, max_bytes + 1 - size))
                if not chunk:
                    break
                chunks.append(chunk)
                size += len(chunk)
            body = b"".join(chunks)
            received = {name.lower(): value for name, value in response.getheaders()}
            return RawResponse(response.status, received, body)
        except (http.client.HTTPException, ssl.SSLError, ValueError) as exc:
            raise OSError(type(exc).__name__) from exc
        finally:
            connection.close()
