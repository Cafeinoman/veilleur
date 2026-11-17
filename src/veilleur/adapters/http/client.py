# SPDX-License-Identifier: EUPL-1.2
"""The networked HTTP client of the collectors (cahier EF-06, ES-08).

Every request goes through the same steps:
1. the address is checked: `http` or `https`, a host, no credentials;
2. per host, `robots.txt` is read (once per process) and obeyed, a quota is counted and a delay kept between
   requests;
3. the host name is resolved, and **every** resolved address must pass the SSRF guard (`guard.is_allowed`); the
   connection is then made to one of those checked addresses, never to a name resolved again (DNS rebinding);
4. the response is capped in size and time; a redirection starts again at step 1 for its target, up to a limit;
5. the content type must be one of those the collector expects; a cached copy answers `304 Not Modified`.

Failures raise `CollectorError` with a stable code, never with detail from the network.
"""

from __future__ import annotations

import logging
import socket
import threading
import time
import zlib
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Protocol
from urllib.parse import quote, urljoin, urlsplit
from urllib.robotparser import RobotFileParser

from veilleur import __version__
from veilleur.core.domain import errors
from veilleur.core.domain.errors import CollectorError
from veilleur.core.ports.http import HttpResponse

from . import guard
from .cache import CachedResponse, HttpCache, MemoryCache

log = logging.getLogger(__name__)
REDIRECTS = frozenset({301, 302, 303, 307, 308})
ROBOTS_AGENT = "Veilleur"
ROBOTS_TTL = 86400.0


@dataclass(frozen=True)
class Limits:
    max_bytes: int = 5_000_000
    """Largest response body, after decompression."""
    timeout: float = 30.0
    """Longest request, redirections included, in seconds."""
    max_redirects: int = 5
    host_interval: float = 1.0
    """Shortest time between two requests to the same host, in seconds."""
    host_quota: int = 200
    """Most requests to one host by one process (a round)."""


@dataclass(frozen=True)
class RawResponse:
    status: int
    headers: Mapping[str, str]
    """Header names in lower case."""
    body: bytes = field(repr=False)


class Transport(Protocol):
    """Sends one request to an address already checked. Raises `OSError` (including `TimeoutError`) on failure."""

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
    ) -> RawResponse: ...


Resolver = Callable[[str, int], Sequence[str]]


def system_resolver(host: str, port: int) -> Sequence[str]:
    """Every address of `host`, IPv4 and IPv6."""
    infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    return [str(info[4][0]) for info in infos]


@dataclass(frozen=True)
class _Url:
    scheme: str
    host: str
    port: int
    target: str
    text: str

    @property
    def origin(self) -> tuple[str, str, int]:
        return (self.scheme, self.host, self.port)


def _parse(url: str) -> _Url:
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError as exc:
        raise CollectorError(errors.BAD_URL) from exc
    if parts.scheme not in ("http", "https") or not parts.hostname or parts.username or parts.password:
        raise CollectorError(errors.BAD_URL)
    host = parts.hostname.rstrip(".").lower()
    if not host or any(c.isspace() or c in "\\" for c in url):
        raise CollectorError(errors.BAD_URL)
    try:
        host = host.encode("idna").decode("ascii") if not host.isascii() else host
    except UnicodeError as exc:
        raise CollectorError(errors.BAD_URL) from exc
    port = port or (443 if parts.scheme == "https" else 80)
    path = quote(parts.path or "/", safe="/%:@!$&'()*+,;=-._~")
    query = quote(parts.query, safe="/%:@!$&'()*+,;=-._~?")
    target = path + ("?" + query if query else "")
    return _Url(parts.scheme, host, port, target, url)


def _media_type(headers: Mapping[str, str]) -> str:
    return headers.get("content-type", "").split(";", 1)[0].strip().lower()


def _accepted(media_type: str, accept: Sequence[str]) -> bool:
    for wanted in accept:
        if wanted == media_type or (wanted.endswith("/*") and media_type.startswith(wanted[:-1])):
            return True
    return False


class NetworkHttpClient:
    """The HTTP client of collections. Thread-safe: requests are serialised (the service has one worker thread)."""

    def __init__(
        self,
        *,
        public_url: str = "folder:",
        cache: HttpCache | None = None,
        limits: Limits = Limits(),
        resolver: Resolver = system_resolver,
        transport: Transport | None = None,
        monotonic: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        contact = f" (+{public_url})" if public_url.startswith("https://") else ""
        self.user_agent = f"Veilleur/{__version__}{contact}"
        self.cache = cache if cache is not None else MemoryCache()
        self.limits = limits
        self._resolve = resolver
        if transport is None:
            from .transport import SocketTransport

            transport = SocketTransport()
        self._transport = transport
        self._monotonic = monotonic
        self._sleep = sleep
        self._now = now
        self._lock = threading.RLock()
        self._last_request: dict[str, float] = {}
        self._requests: dict[str, int] = {}
        self._robots: dict[tuple[str, str, int], tuple[float, RobotFileParser | None]] = {}

    # --- Port -------------------------------------------------------------------------------------------------

    def get(self, url: str, *, accept: Sequence[str] = ()) -> HttpResponse:
        with self._lock:
            start = self._monotonic()
            first = _parse(url)
            cached = self.cache.get(first.text)
            current = first
            for _ in range(self.limits.max_redirects + 1):
                self._check_robots(current, start)
                headers = {"Accept": ", ".join(accept) if accept else "*/*"}
                if cached is not None and current is first:
                    if cached.etag:
                        headers["If-None-Match"] = cached.etag
                    if cached.last_modified:
                        headers["If-Modified-Since"] = cached.last_modified
                raw = self._send(current, headers, start)
                if raw.status in REDIRECTS:
                    location = raw.headers.get("location")
                    if not location:
                        raise CollectorError(errors.BAD_RESPONSE)
                    current = _parse(urljoin(current.text, location.strip()))
                    continue
                if raw.status == 304 and cached is not None and current is first:
                    return HttpResponse(200, cached.url, dict(cached.headers), cached.body)
                if raw.status >= 400:
                    raise CollectorError(f"http_{raw.status}" if 400 <= raw.status <= 599 else errors.BAD_RESPONSE)
                if not 200 <= raw.status < 300:
                    raise CollectorError(errors.BAD_RESPONSE)
                if accept and not _accepted(_media_type(raw.headers), accept):
                    raise CollectorError(errors.UNEXPECTED_CONTENT_TYPE)
                kept = {k: v for k, v in raw.headers.items() if k in ("content-type", "etag", "last-modified")}
                if current is first and ("etag" in kept or "last-modified" in kept):
                    self.cache.put(
                        first.text,
                        CachedResponse(
                            current.text, kept, raw.body, kept.get("etag"), kept.get("last-modified"), self._now()
                        ),
                    )
                return HttpResponse(raw.status, current.text, kept, raw.body)
            raise CollectorError(errors.TOO_MANY_REDIRECTS)

    # --- Steps ------------------------------------------------------------------------------------------------

    def _remaining(self, start: float) -> float:
        remaining = self.limits.timeout - (self._monotonic() - start)
        if remaining <= 0:
            raise CollectorError(errors.TIMEOUT)
        return remaining

    def _pace(self, host: str, start: float) -> None:
        """Count the request against the host's quota and keep the delay since its previous request."""
        count = self._requests.get(host, 0)
        if count >= self.limits.host_quota:
            raise CollectorError(errors.HOST_QUOTA_EXCEEDED)
        self._requests[host] = count + 1
        last = self._last_request.get(host)
        if last is not None:
            wait = self.limits.host_interval - (self._monotonic() - last)
            if wait > 0:
                if wait >= self._remaining(start):
                    raise CollectorError(errors.TIMEOUT)
                self._sleep(wait)
        self._last_request[host] = self._monotonic()

    def _addresses(self, url: _Url) -> list[str]:
        try:
            resolved = list(self._resolve(url.host, url.port))
        except (OSError, UnicodeError) as exc:
            raise CollectorError(errors.DNS_FAILED) from exc
        if not resolved:
            raise CollectorError(errors.DNS_FAILED)
        allowed = [guard.parse_allowed(text) for text in resolved]
        if any(address is None for address in allowed):
            # One refused address is enough: a name pointing to both a public and a private address is a trap.
            raise CollectorError(errors.ADDRESS_REFUSED)
        return [str(address) for address in allowed]

    def _send(self, url: _Url, headers: Mapping[str, str], start: float) -> RawResponse:
        self._pace(url.host, start)
        addresses = self._addresses(url)
        sent = {
            **headers,
            "User-Agent": self.user_agent,
            "Accept-Encoding": "gzip, identity",
            "Connection": "close",
        }
        last_error: CollectorError | None = None
        for address in addresses:
            try:
                raw = self._transport.request(
                    scheme=url.scheme,
                    address=address,
                    host=url.host,
                    port=url.port,
                    target=url.target,
                    headers=sent,
                    timeout=self._remaining(start),
                    max_bytes=self.limits.max_bytes,
                )
            except TimeoutError as exc:
                raise CollectorError(errors.TIMEOUT) from exc
            except OSError as exc:
                log.info("request failed: %s", type(exc).__name__)
                last_error = CollectorError(errors.NETWORK_ERROR)
                continue
            self._remaining(start)
            return self._decoded(raw)
        assert last_error is not None
        raise last_error

    def _decoded(self, raw: RawResponse) -> RawResponse:
        body = raw.body
        if len(body) > self.limits.max_bytes:
            raise CollectorError(errors.RESPONSE_TOO_LARGE)
        encoding = raw.headers.get("content-encoding", "identity").strip().lower()
        if encoding in ("gzip", "x-gzip"):
            inflater = zlib.decompressobj(wbits=31)
            try:
                body = inflater.decompress(body, self.limits.max_bytes + 1)
            except zlib.error as exc:
                raise CollectorError(errors.BAD_RESPONSE) from exc
            if len(body) > self.limits.max_bytes or inflater.unconsumed_tail:
                raise CollectorError(errors.RESPONSE_TOO_LARGE)
        elif encoding not in ("", "identity"):
            raise CollectorError(errors.BAD_RESPONSE)
        headers = {k: v for k, v in raw.headers.items() if k != "content-encoding"}
        return RawResponse(raw.status, headers, body)

    # --- robots.txt -------------------------------------------------------------------------------------------

    def _check_robots(self, url: _Url, start: float) -> None:
        if url.target.split("?", 1)[0] == "/robots.txt":
            return
        rules = self._robots_for(url, start)
        if rules is not None and not rules.can_fetch(ROBOTS_AGENT, url.text):
            raise CollectorError(errors.ROBOTS_DISALLOWED)

    def _robots_for(self, url: _Url, start: float) -> RobotFileParser | None:
        """Rules of the origin, read once a day: a missing `robots.txt` (4xx) allows everything; one that cannot be
        read (5xx, network failure) refuses the request, as the robots exclusion protocol asks (RFC 9309)."""
        known = self._robots.get(url.origin)
        if known is not None and self._monotonic() - known[0] < ROBOTS_TTL:
            return known[1]
        default_port = 443 if url.scheme == "https" else 80
        netloc = url.host if url.port == default_port else f"{url.host}:{url.port}"
        if ":" in url.host:
            netloc = f"[{url.host}]" if url.port == default_port else f"[{url.host}]:{url.port}"
        robots_url = _parse(f"{url.scheme}://{netloc}/robots.txt")
        rules: RobotFileParser | None = None
        current = robots_url
        for _ in range(self.limits.max_redirects + 1):
            try:
                raw = self._send(current, {"Accept": "text/plain, */*"}, start)
            except CollectorError as exc:  # a network failure keeps its own code
                if exc.code in (errors.RESPONSE_TOO_LARGE, errors.BAD_RESPONSE):
                    raise CollectorError(errors.ROBOTS_UNAVAILABLE) from exc
                raise
            if raw.status in REDIRECTS and raw.headers.get("location"):
                current = _parse(urljoin(current.text, raw.headers["location"].strip()))
                continue
            if 400 <= raw.status < 500:
                break
            if raw.status != 200:
                raise CollectorError(errors.ROBOTS_UNAVAILABLE)
            rules = RobotFileParser()
            rules.parse(raw.body[:500_000].decode("utf-8", "replace").splitlines())
            break
        else:
            raise CollectorError(errors.ROBOTS_UNAVAILABLE)
        self._robots[url.origin] = (self._monotonic(), rules)
        return rules
