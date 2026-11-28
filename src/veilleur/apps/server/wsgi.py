# SPDX-License-Identifier: EUPL-1.2
"""HTTP interface `/v1` (spec §7.4, protocol specification §8 and §9), as a WSGI application.

Routing works on the **raw** request target, the one the client signs (protocol §8): `REQUEST_URI` (or `RAW_URI`),
never a decoded or normalised path. Without either, the target is rebuilt from `PATH_INFO` and `QUERY_STRING`, and
the MAC is checked against that same text, so that what is routed is always what is authenticated.

Nothing about a request is logged: no body, no header, no address (ES-09).
"""

from __future__ import annotations

import json
import logging
import re
import threading
import time
from collections import deque
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from veilleur.core.domain import errors
from veilleur.core.domain.errors import VeilleurError
from veilleur.core.domain.model import JobStatus, Origin, Pairing
from veilleur.core.ports.sealer import SealError
from veilleur.core.services import jobs, reports, subscriptions
from veilleur.core.services.context import Core
from veilleur_protocol import ProtocolError, parse_authorization, parse_time, request_scope, verify_request
from veilleur_protocol.auth import DATE_HEADER, TOLERANCE

from .messages import error_message

log = logging.getLogger(__name__)

MAX_BODY = 1_000_000
"""Largest request body (spec ES-11), enforced here even if the reverse proxy lets more through."""
RETRY_AFTER = 5
RATE_LIMIT = 120
RATE_WINDOW = 60.0
UNAUTHENTICATED_LIMIT = 300
"""Most `401` answers per `RATE_WINDOW` for the whole process (R04, D12); beyond, `429` without reading the body."""
_SUBSCRIPTION = re.compile(r"/v1/subscriptions/([0-9a-f]{32})(/reports|/reports/([1-9][0-9]{0,17})|/state|/history)?")
_AFTER = re.compile(r"after=(0|[1-9][0-9]{0,17})")
_SINCE = re.compile(r"since=([0-9]{4}-[0-9]{2}-[0-9]{2})")
_STATUS = {
    200: "200 OK",
    202: "202 Accepted",
    204: "204 No Content",
    400: "400 Bad Request",
    401: "401 Unauthorized",
    403: "403 Forbidden",
    404: "404 Not Found",
    409: "409 Conflict",
    410: "410 Gone",
    413: "413 Content Too Large",
    429: "429 Too Many Requests",
    500: "500 Internal Server Error",
}
_HTTP_STATUS = {
    errors.BAD_REQUEST: 400,
    errors.INVALID_SUBSCRIPTION: 400,
    errors.INVALID_PARAMS: 400,
    errors.UNKNOWN_COLLECTOR: 400,
    errors.UNKNOWN_FILTER: 400,
    errors.UNKNOWN_RENDERER: 400,
    errors.NOT_FOUND: 404,
    errors.REVOKED: 403,
    errors.COLLECTOR_NOT_ALLOWED: 403,
    errors.TEAM_SUBSCRIPTION: 403,
    errors.VERSION_CONFLICT: 409,
    errors.SUBSCRIPTION_DELETED: 409,
    errors.PURGED: 410,
    errors.BODY_TOO_LARGE: 413,
    errors.RATE_LIMITED: 429,
}

StartResponse = Callable[[str, list[tuple[str, str]]], Any]


@dataclass(frozen=True)
class Response:
    status: int
    body: bytes = b""
    content_type: str | None = None
    headers: tuple[tuple[str, str], ...] = ()


class _Refusal(Exception):
    def __init__(self, status: int, code: str, params: Mapping[str, Any] | None = None) -> None:
        self.status, self.code, self.params = status, code, dict(params or {})
        super().__init__(code)


def _json(status: int, document: Any) -> Response:
    return Response(status, json.dumps(document, separators=(",", ":")).encode("utf-8"), "application/json")


def _package(data: bytes) -> Response:
    return Response(200, data, "application/octet-stream")


def _pending() -> Response:
    return Response(202, headers=(("Retry-After", str(RETRY_AFTER)),))


def request_language(header: str | None, default: str) -> str:
    """The first supported language of `Accept-Language`, by weight; otherwise `default`."""
    choices: list[tuple[float, int, str]] = []
    for index, part in enumerate((header or "").split(",")):
        tag, _, rest = part.strip().partition(";")
        weight = 1.0
        if rest.strip().startswith("q="):
            try:
                weight = float(rest.strip()[2:])
            except ValueError:
                continue
        language = tag.strip().split("-")[0].lower()
        if language in ("en", "fr") and weight > 0:
            choices.append((-weight, index, language))
    return min(choices)[2] if choices else default


class RateLimiter:
    """At most `limit` events per key in any `window` seconds (`429`): requests of a pairing, or `401` answers."""

    def __init__(
        self, limit: int = RATE_LIMIT, window: float = RATE_WINDOW, clock: Callable[[], float] = time.monotonic
    ):
        self.limit, self.window, self._clock = limit, window, clock
        self._seen: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def allow(self, key_id: str) -> bool:
        now = self._clock()
        with self._lock:
            seen = self._seen.setdefault(key_id, deque())
            while seen and now - seen[0] >= self.window:
                seen.popleft()
            if len(seen) >= self.limit:
                return False
            seen.append(now)
            return True


class Api:
    """The WSGI application. `wake_worker` is called when a long job is queued."""

    def __init__(
        self,
        core: Core,
        *,
        language: str = "en",
        limiter: RateLimiter | None = None,
        refusals: RateLimiter | None = None,
        wake_worker: Callable[[], None] = lambda: None,
    ) -> None:
        self.core = core
        self.language = language
        self.limiter = limiter or RateLimiter()
        self.refusals = refusals or RateLimiter(UNAUTHENTICATED_LIMIT, RATE_WINDOW)
        self.wake_worker = wake_worker

    def __call__(self, environ: dict[str, Any], start_response: StartResponse) -> Iterable[bytes]:
        language = request_language(environ.get("HTTP_ACCEPT_LANGUAGE"), self.language)
        try:
            response = self._handle(environ)
        except _Refusal as refusal:
            response = self._error(refusal.status, refusal.code, refusal.params, language)
        except VeilleurError as exc:
            status = _HTTP_STATUS.get(exc.code, 500)
            response = self._error(status, exc.code if status != 500 else errors.INTERNAL_ERROR, exc.params, language)
        except Exception as exc:  # never show internal detail (§7.4); log the type only
            log.error("request failed: %s", type(exc).__name__)
            response = self._error(500, errors.INTERNAL_ERROR, {}, language)
        headers = [("Cache-Control", "no-store"), ("Content-Length", str(len(response.body)))]
        if response.content_type:
            headers.append(("Content-Type", response.content_type))
        headers.extend(response.headers)
        start_response(_STATUS[response.status], headers)
        return [response.body]

    @staticmethod
    def _error(status: int, code: str, params: Mapping[str, Any], language: str) -> Response:
        return _json(status, {"code": code, "message": error_message(code, params, language=language)})

    # --- Authentication (protocol §8) --------------------------------------------------------------------------

    @staticmethod
    def _target(environ: Mapping[str, Any]) -> str:
        raw = environ.get("REQUEST_URI") or environ.get("RAW_URI")
        if isinstance(raw, str) and raw:
            return raw
        query = str(environ.get("QUERY_STRING", ""))
        return str(environ.get("PATH_INFO", "")) + (f"?{query}" if query else "")

    @staticmethod
    def _body(environ: Mapping[str, Any]) -> bytes:
        length_text = environ.get("CONTENT_LENGTH") or "0"
        if not length_text.isdigit():
            raise _Refusal(400, errors.BAD_REQUEST)
        length = int(length_text)
        if length > MAX_BODY:
            raise _Refusal(413, errors.BODY_TOO_LARGE, {"limit": MAX_BODY})
        body: bytes = environ["wsgi.input"].read(length) if length else b""
        if len(body) != length:
            raise _Refusal(400, errors.BAD_REQUEST)
        return body

    def _identify(self, target: str, environ: Mapping[str, Any]) -> Pairing:
        """The checks of §8 that need no body: header, date, staleness, then the pairing found by `key_id`."""
        authorization = environ.get("HTTP_AUTHORIZATION")
        date = environ.get("HTTP_" + DATE_HEADER.upper().replace("-", "_"))
        try:
            key_id, _mac = parse_authorization(authorization)
            try:
                sent = parse_time(date)
            except ProtocolError as exc:
                raise ProtocolError("bad_date") from exc
            if abs(self.core.clock.now() - sent) > TOLERANCE:
                raise ProtocolError("stale_date")
            request_scope(target)
            pairing = self.core.store.get_pairing(key_id)
            if pairing is None:
                raise ProtocolError("bad_authorization", "unknown key_id")
        except ProtocolError as exc:
            raise self._unauthenticated(exc.code) from exc
        return pairing

    def _verify(self, pairing: Pairing, method: str, target: str, body: bytes, environ: Mapping[str, Any]) -> None:
        """The last check of §8, the MAC, which covers the body's hash."""
        try:
            verify_request(
                pairing.secret,
                method,
                target,
                body,
                authorization=environ.get("HTTP_AUTHORIZATION"),
                date=environ.get("HTTP_" + DATE_HEADER.upper().replace("-", "_")),
                now=self.core.clock.now(),
            )
        except ProtocolError as exc:
            raise self._unauthenticated(exc.code) from exc

    def _unauthenticated(self, code: str) -> _Refusal:
        """`401`, or `429` once the process has given `UNAUTHENTICATED_LIMIT` of them in the window (R04)."""
        if not self.refusals.allow(""):
            return _Refusal(429, errors.RATE_LIMITED)
        return _Refusal(401, code)

    # --- Routing (protocol §9) ---------------------------------------------------------------------------------

    def _handle(self, environ: Mapping[str, Any]) -> Response:
        method = environ.get("REQUEST_METHOD", "")
        target = self._target(environ)
        pairing = self._identify(target, environ)  # before the body is read (R04)
        body = self._body(environ)
        self._verify(pairing, method, target, body, environ)
        if not pairing.active:
            raise _Refusal(403, errors.REVOKED)
        if not self.limiter.allow(pairing.key_id):
            raise _Refusal(429, errors.RATE_LIMITED)
        path, _, query = target.partition("?")
        if path == "/v1/collectors":
            if method != "GET" or query:
                raise VeilleurError(errors.NOT_FOUND if method != "GET" else errors.BAD_REQUEST)
            return self._collectors(pairing)
        if path == "/v1/subscriptions":
            if method != "GET" or query:
                raise VeilleurError(errors.NOT_FOUND if method != "GET" else errors.BAD_REQUEST)
            return self._subscriptions(pairing)
        match = _SUBSCRIPTION.fullmatch(path)
        if match is None:
            raise VeilleurError(errors.NOT_FOUND)
        uid, route, seq = match.group(1), match.group(2), match.group(3)
        key_id = pairing.key_id
        if route is None:
            if query:
                raise VeilleurError(errors.BAD_REQUEST)
            if method == "PUT":
                return self._put(pairing, uid, body)
            if method == "DELETE":
                subscriptions.delete_subscription(self.core, key_id, uid)
                return Response(204)
            raise VeilleurError(errors.NOT_FOUND)
        if method != "GET":
            raise VeilleurError(errors.NOT_FOUND)
        subscription = subscriptions.get_live_subscription(self.core, key_id, uid)
        if route == "/reports":
            after = _AFTER.fullmatch(query) if query else None
            if query and after is None:
                raise VeilleurError(errors.BAD_REQUEST)
            return self._list(key_id, uid, int(after.group(1)) if after else 0)
        if query and route != "/history":
            raise VeilleurError(errors.BAD_REQUEST)
        if seq is not None:
            return self._report(key_id, uid, int(seq))
        if route == "/state":
            built = reports.build_state(self.core, subscription)
            return _pending() if built is None else _package(built[1])
        since = _SINCE.fullmatch(query)
        if since is None:
            raise VeilleurError(errors.BAD_REQUEST)
        return self._history(key_id, uid, since.group(1))

    def _collectors(self, pairing: Pairing) -> Response:
        listed = [
            {"name": c.name, "schema": c.schema} for c in subscriptions.allowed_collectors(self.core, pairing.key_id)
        ]
        return _json(200, {"collectors": listed})

    def _subscriptions(self, pairing: Pairing) -> Response:
        """Live subscriptions of this pairing, so that a receiving tool learns the uids of its team subscriptions."""
        listed: list[dict[str, Any]] = []
        for s in self.core.store.list_subscriptions():
            if s.key_id != pairing.key_id:
                continue
            entry: dict[str, Any] = {"uid": s.uid, "origin": s.origin.value, "version": s.version}
            if s.origin is Origin.TEAM:
                entry["name"] = s.team_name
            listed.append(entry)
        listed.sort(key=lambda entry: entry["uid"])
        return _json(200, {"subscriptions": listed})

    def _put(self, pairing: Pairing, uid: str, body: bytes) -> Response:
        try:
            base_version, document = self.core.sealer.open_subscription(pairing.secret, uid, body)
        except SealError as exc:
            raise _Refusal(413 if exc.code == "too_large" else 400, exc.code) from exc
        version = subscriptions.put_subscription(self.core, pairing.key_id, uid, base_version, document)
        if version == 1:
            self.wake_worker()
        return _json(200, {"version": version})

    def _list(self, key_id: str, uid: str, after: int) -> Response:
        bounds = self.core.store.package_bounds(key_id, uid)
        packages = [
            {"seq": p.seq, "size": p.size, "sha256": p.sha256}
            for p in self.core.store.list_packages(key_id, uid, after)
        ]
        return _json(200, {"packages": packages, "oldest": bounds.oldest, "last": bounds.last})

    def _report(self, key_id: str, uid: str, seq: int) -> Response:
        data = self.core.store.get_package(key_id, uid, seq)
        if data is not None:
            return _package(data)
        if seq <= self.core.store.package_bounds(key_id, uid).purged_through:
            raise VeilleurError(errors.PURGED)
        raise VeilleurError(errors.NOT_FOUND)

    def _history(self, key_id: str, uid: str, since: str) -> Response:
        job = jobs.request_history(self.core, key_id, uid, since)
        if job.status is JobStatus.DONE and job.result is not None:
            return _package(job.result)
        self.wake_worker()
        return _pending()
