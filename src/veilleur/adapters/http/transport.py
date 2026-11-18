# SPDX-License-Identifier: EUPL-1.2
"""Sockets of the networked client: a connection to an address already checked by the SSRF guard.

The host name is used only for the `Host` header and TLS (SNI and certificate check), never resolved again here.
No proxy from the environment is used.
"""

from __future__ import annotations

import contextlib
import http.client
import socket
import ssl
import threading
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
        # handshake after `self.sock` is set, so that the watchdog of `SocketTransport.request` can cut it too
        self.sock = self._tls.wrap_socket(sock, server_hostname=self.host, do_handshake_on_connect=False)
        self.sock.do_handshake()


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
        connection = self.connection(scheme, address, host, port, timeout)
        expired = threading.Event()

        def cut() -> None:  # the whole request is capped: TLS handshake, status line and headers included
            expired.set()
            if connection.sock is not None:
                with contextlib.suppress(OSError):
                    socket.socket.shutdown(connection.sock, socket.SHUT_RDWR)

        watchdog = threading.Timer(timeout, cut)
        watchdog.daemon = True
        watchdog.start()
        try:
            connection.connect()
            if expired.is_set():
                raise TimeoutError
            connection.request("GET", target, headers=dict(headers))
            response = connection.getresponse()
            chunks: list[bytes] = []
            size = 0
            while size <= max_bytes:
                chunk = response.read1(min(65536, max_bytes + 1 - size))
                if not chunk:
                    break
                chunks.append(chunk)
                size += len(chunk)
            if expired.is_set():
                raise TimeoutError
            body = b"".join(chunks)
            received = {name.lower(): value for name, value in response.getheaders()}
            return RawResponse(response.status, received, body)
        except (http.client.HTTPException, ssl.SSLError, ValueError) as exc:
            if expired.is_set():
                raise TimeoutError from exc
            raise OSError(type(exc).__name__) from exc
        except OSError:
            if expired.is_set():
                raise TimeoutError from None
            raise
        finally:
            watchdog.cancel()
            connection.close()
