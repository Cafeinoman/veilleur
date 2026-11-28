# SPDX-License-Identifier: EUPL-1.2
"""HTTP interface `/v1`, called directly as a WSGI application (no port opened)."""

from __future__ import annotations

import io
import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

import pytest

from veilleur.apps.server.wsgi import MAX_BODY, UNAUTHENTICATED_LIMIT, Api, RateLimiter, request_language
from veilleur.core.domain.model import Pairing, SubscriptionSpec
from veilleur.core.services import jobs, pairing, round
from veilleur.core.services.subscriptions import TeamSubscription, sync_team
from veilleur_protocol import Kind, open_package, seal_subscription, sign_request

from .fakes import World

UID = "0123456789abcdef0123456789abcdef"


@dataclass
class Reply:
    status: str
    headers: dict[str, str]
    body: bytes

    @property
    def code(self) -> int:
        return int(self.status.split()[0])

    def json(self) -> Any:
        return json.loads(self.body)


@dataclass
class Client:
    api: Api
    world: World
    pairing: Pairing
    extra: dict[str, str] = field(default_factory=dict)

    def call(
        self,
        method: str,
        target: str,
        body: bytes = b"",
        *,
        signed_target: str | None = None,
        at: datetime | None = None,
        headers: dict[str, str] | None = None,
        sign: bool = True,
        environ: dict[str, Any] | None = None,
    ) -> Reply:
        env: dict[str, Any] = {
            "REQUEST_METHOD": method,
            "REQUEST_URI": target,
            "PATH_INFO": target.split("?")[0],
            "QUERY_STRING": target.partition("?")[2],
            "CONTENT_LENGTH": str(len(body)),
            "wsgi.input": io.BytesIO(body),
        }
        if sign:
            signed = sign_request(
                self.pairing.secret,
                self.pairing.key_id,
                method,
                signed_target or target,
                body,
                at or self.world.clock.now(),
            )
            env["HTTP_AUTHORIZATION"] = signed.authorization
            env["HTTP_X_VEILLEUR_DATE"] = signed.date
        for name, value in {**self.extra, **(headers or {})}.items():
            env["HTTP_" + name.upper().replace("-", "_")] = value
        env.update(environ or {})
        captured: dict[str, Any] = {}

        def start_response(status: str, response_headers: list[tuple[str, str]]) -> None:
            captured["status"], captured["headers"] = status, dict(response_headers)

        data = b"".join(self.api(env, start_response))
        assert captured["headers"]["Cache-Control"] == "no-store"
        assert int(captured["headers"]["Content-Length"]) == len(data)
        return Reply(captured["status"], captured["headers"], data)

    def put(self, document: dict[str, Any], base: int = 0, uid: str = UID) -> Reply:
        body = seal_subscription(self.pairing.secret, uid, base, document)
        return self.call("PUT", f"/v1/subscriptions/{uid}", body)


def _client(world: World, label: str = "desk 3", **kwargs: Any) -> Client:
    p = pairing.create_pairing(world.app.core, label)
    return Client(Api(world.app.core, **kwargs), world, p)


@pytest.fixture
def client(world: World) -> Client:
    return _client(world)


DOC = {"collector": "fake", "params": {"topic": "news"}, "frequency": "every_round"}


def test_full_flow(client: Client) -> None:
    world = client.world
    world.collector.set("news", ("a", {"title": "A"}))
    reply = client.put(DOC)
    assert (reply.code, reply.json()) == (200, {"version": 1})
    assert client.call("GET", f"/v1/subscriptions/{UID}/reports").json() == {"packages": [], "oldest": None, "last": 0}
    pending = client.call("GET", f"/v1/subscriptions/{UID}/state")
    assert pending.code == 202 and pending.headers["Retry-After"] == "5" and pending.body == b""
    jobs.run_pending(world.app.core)  # the worker thread
    listing = client.call("GET", f"/v1/subscriptions/{UID}/reports?after=0").json()
    assert listing["last"] == 1 and listing["oldest"] == 1 and len(listing["packages"]) == 1
    package = client.call("GET", f"/v1/subscriptions/{UID}/reports/1")
    assert package.code == 200 and package.headers["Content-Type"] == "application/octet-stream"
    assert listing["packages"][0]["size"] == len(package.body)
    opened = open_package(
        package.body, secret=client.pairing.secret, uid=UID, trusted_keys=[world.app.core.sealer.public_key], seq=1
    )
    assert opened.kind is Kind.STATE and [i.key for i in opened.items] == ["a"]
    world.clock.advance(hours=1)
    world.collector.set("news", ("a", {"title": "A"}), ("b", {"title": "B"}))
    round.run_round(world.app.core)
    assert client.call("GET", f"/v1/subscriptions/{UID}/reports?after=1").json()["packages"][0]["seq"] == 2
    state = client.call("GET", f"/v1/subscriptions/{UID}/state")
    opened = open_package(
        state.body, secret=client.pairing.secret, uid=UID, trusted_keys=[world.app.core.sealer.public_key], seq=2
    )
    assert opened.kind is Kind.STATE and [i.key for i in opened.items] == ["a", "b"]
    history = client.call("GET", f"/v1/subscriptions/{UID}/history?since=2026-11-17")
    assert history.code == 202
    jobs.run_pending(world.app.core)
    history = client.call("GET", f"/v1/subscriptions/{UID}/history?since=2026-11-17")
    assert history.code == 200
    opened = open_package(
        history.body, secret=client.pairing.secret, uid=UID, trusted_keys=[world.app.core.sealer.public_key]
    )
    assert opened.kind is Kind.HISTORY and opened.seq == 2
    assert client.put({**DOC, "params": {"topic": "other"}}, base=1).json() == {"version": 2}
    assert client.call("DELETE", f"/v1/subscriptions/{UID}").code == 204
    assert client.call("GET", f"/v1/subscriptions/{UID}/reports").code == 404


def test_collectors(client: Client) -> None:
    reply = client.call("GET", "/v1/collectors")
    assert reply.code == 200
    assert [c["name"] for c in reply.json()["collectors"]] == ["fake"]
    assert reply.json()["collectors"][0]["schema"]["required"] == ["topic"]
    client.world.app.store.set_grant(client.pairing.key_id, "fetch", True)
    assert [c["name"] for c in client.call("GET", "/v1/collectors").json()["collectors"]] == ["fake", "fetch"]


def _error(reply: Reply) -> tuple[int, str]:
    assert set(reply.json()) == {"code", "message"}
    assert reply.headers["Content-Type"] == "application/json"
    return reply.code, reply.json()["code"]


def test_authentication_order_for_an_unknown_key_id(client: Client) -> None:
    """Protocol §8: header, date and staleness are checked before the secret is looked up."""
    stranger = Client(client.api, client.world, Pairing("f" * 16, "x", bytes(32), client.world.clock.now()))
    old = client.world.clock.now() - timedelta(minutes=6)
    assert _error(stranger.call("GET", "/v1/collectors", at=old)) == (401, "stale_date")
    assert _error(stranger.call("GET", "/v1/collectors", headers={"X-Veilleur-Date": "yesterday"})) == (
        401,
        "bad_date",
    )
    assert _error(stranger.call("GET", "/v1/collectors")) == (401, "bad_authorization")


@pytest.mark.parametrize(
    ("headers", "code"),
    [
        ({"Authorization": "Bearer x"}, "bad_authorization"),
        ({"Authorization": "Veilleur " + "0" * 16 + ":" + "A" * 43}, "bad_authorization"),
        ({"X-Veilleur-Date": "2026-11-17 06:00:00"}, "bad_date"),
    ],
)
def test_authentication_refusals(client: Client, headers: dict[str, str], code: str) -> None:
    assert _error(client.call("GET", "/v1/collectors", headers=headers)) == (401, code)


def test_missing_headers(client: Client) -> None:
    assert _error(client.call("GET", "/v1/collectors", sign=False)) == (401, "bad_authorization")


def test_mac_covers_body_method_and_target(client: Client) -> None:
    body = seal_subscription(client.pairing.secret, UID, 0, DOC)
    signed = sign_request(
        client.pairing.secret, client.pairing.key_id, "PUT", f"/v1/subscriptions/{UID}", body, client.world.clock.now()
    )
    headers = {"Authorization": signed.authorization, "X-Veilleur-Date": signed.date}
    other = seal_subscription(client.pairing.secret, UID, 0, {**DOC, "frequency": "daily"})
    assert _error(client.call("PUT", f"/v1/subscriptions/{UID}", other, sign=False, headers=headers))[0] == 401
    assert _error(client.call("DELETE", f"/v1/subscriptions/{UID}", sign=False, headers=headers))[0] == 401
    assert client.call("PUT", f"/v1/subscriptions/{UID}", body, sign=False, headers=headers).code == 200


def test_routing_uses_the_raw_target(client: Client) -> None:
    client.put(DOC)
    encoded = f"/v1/subscriptions/{UID}/repor%74s"
    # Signed as sent: the raw target is authenticated, and it routes nowhere.
    assert _error(client.call("GET", encoded)) == (404, "not_found")
    # Signed over the decoded path but sent encoded: the MAC does not match what was received.
    decoded = f"/v1/subscriptions/{UID}/reports"
    assert _error(client.call("GET", encoded, signed_target=decoded)) == (401, "bad_authorization")
    # A dot segment is not normalised either.
    assert _error(client.call("GET", f"/v1/subscriptions/{UID}/../{UID}/reports")) == (404, "not_found")


def test_without_raw_uri_the_rebuilt_target_is_authenticated(client: Client) -> None:
    client.put(DOC)
    target = f"/v1/subscriptions/{UID}/reports?after=0"
    reply = client.call("GET", target, environ={"REQUEST_URI": ""})
    assert reply.code == 200


@pytest.mark.parametrize("uid", ["XYZ", UID.upper(), UID + "00", f"{UID[:-2]}%41"])
def test_malformed_uid_in_the_path_is_an_authentication_error(client: Client, uid: str) -> None:
    signed = sign_request(
        client.pairing.secret, client.pairing.key_id, "GET", "/v1/collectors", b"", client.world.clock.now()
    )
    headers = {"Authorization": signed.authorization, "X-Veilleur-Date": signed.date}
    reply = client.call("GET", f"/v1/subscriptions/{uid}/reports", sign=False, headers=headers)
    assert _error(reply) == (401, "bad_authorization")


def test_revoked_pairing(client: Client) -> None:
    client.put(DOC)
    pairing.revoke_pairing(client.world.app.core, client.pairing.key_id)
    assert _error(client.call("GET", f"/v1/subscriptions/{UID}/reports")) == (403, "revoked")
    assert _error(client.call("GET", "/v1/collectors")) == (403, "revoked")


def test_collector_not_allowed(client: Client) -> None:
    assert _error(client.put({"collector": "fetch", "params": {"topic": "x"}})) == (403, "collector_not_allowed")


def test_invalid_documents(client: Client) -> None:
    assert _error(client.put({"collector": "fake", "params": {}})) == (400, "invalid_params")
    assert _error(client.put({"collector": "nope"})) == (400, "unknown_collector")
    sealed_for_other = seal_subscription(client.pairing.secret, "f" * 32, 0, DOC)
    assert _error(client.call("PUT", f"/v1/subscriptions/{UID}", sealed_for_other)) == (400, "uid_mismatch")
    assert _error(client.call("PUT", f"/v1/subscriptions/{UID}", b"garbage")) == (400, "bad_envelope")
    wrong_key = seal_subscription(bytes(32), UID, 0, DOC)
    assert _error(client.call("PUT", f"/v1/subscriptions/{UID}", wrong_key)) == (400, "decryption_failed")


def test_versions_over_http(client: Client) -> None:
    client.put(DOC)
    assert _error(client.put(DOC)) == (409, "version_conflict")
    assert client.put(DOC, base=1).json() == {"version": 2}
    assert client.call("DELETE", f"/v1/subscriptions/{UID}").code == 204


def test_replayed_delete_and_creation_have_no_effect(client: Client) -> None:
    """Threat model §4: versions keep increasing across a deletion, and a deleted uid is never reused."""
    creation = seal_subscription(client.pairing.secret, UID, 0, DOC)
    assert client.call("PUT", f"/v1/subscriptions/{UID}", creation).code == 200
    deletion = sign_request(
        client.pairing.secret,
        client.pairing.key_id,
        "DELETE",
        f"/v1/subscriptions/{UID}",
        b"",
        client.world.clock.now(),
    )
    headers = {"Authorization": deletion.authorization, "X-Veilleur-Date": deletion.date}
    assert client.call("DELETE", f"/v1/subscriptions/{UID}", sign=False, headers=headers).code == 204
    assert _error(client.call("PUT", f"/v1/subscriptions/{UID}", creation)) == (409, "subscription_deleted")
    assert client.call("DELETE", f"/v1/subscriptions/{UID}", sign=False, headers=headers).code == 204
    stored = client.world.app.store.get_subscription(client.pairing.key_id, UID)
    assert stored is not None and stored.deleted and stored.version == 2


def test_other_pairings_subscriptions_are_invisible(client: Client) -> None:
    client.put(DOC)
    jobs.run_pending(client.world.app.core)
    other = _client(client.world, "desk 4")
    assert _error(other.call("GET", f"/v1/subscriptions/{UID}/reports/1")) == (404, "not_found")
    assert _error(other.call("DELETE", f"/v1/subscriptions/{UID}")) == (404, "not_found")


def test_body_limit(client: Client) -> None:
    big = b"x" * (MAX_BODY + 1)
    assert _error(client.call("PUT", f"/v1/subscriptions/{UID}", big)) == (413, "body_too_large")
    lying = client.call("PUT", f"/v1/subscriptions/{UID}", b"", environ={"CONTENT_LENGTH": str(MAX_BODY + 1)})
    assert _error(lying) == (413, "body_too_large")
    assert _error(client.call("PUT", f"/v1/subscriptions/{UID}", b"", environ={"CONTENT_LENGTH": "-1"}))[0] == 400


def test_purged_package_answers_410(client: Client) -> None:
    world = client.world
    client.put(DOC)
    jobs.run_pending(world.app.core)
    world.clock.advance(days=91)
    round.run_round(world.app.core)
    assert _error(client.call("GET", f"/v1/subscriptions/{UID}/reports/1")) == (410, "purged")
    assert _error(client.call("GET", f"/v1/subscriptions/{UID}/reports/2")) == (404, "not_found")
    assert client.call("GET", f"/v1/subscriptions/{UID}/reports").json() == {"packages": [], "oldest": None, "last": 1}
    assert client.call("GET", f"/v1/subscriptions/{UID}/state").code == 200


@pytest.mark.parametrize(
    ("method", "target", "status"),
    [
        ("GET", "/v1/subscriptions/{uid}/reports?after=01", 400),
        ("GET", "/v1/subscriptions/{uid}/reports?after=1&x=2", 400),
        ("GET", "/v1/subscriptions/{uid}/reports/0", 404),
        ("GET", "/v1/subscriptions/{uid}/reports/01", 404),
        ("GET", "/v1/subscriptions/{uid}/history", 400),
        ("GET", "/v1/subscriptions/{uid}/history?since=2026-13-01", 400),
        ("GET", "/v1/subscriptions/{uid}/state?x=1", 400),
        ("POST", "/v1/subscriptions/{uid}/reports", 404),
        ("GET", "/v1/subscriptions/{uid}", 404),
        ("GET", "/v1/collectors?x=1", 400),
        ("POST", "/v1/collectors", 404),
        ("GET", "/v2/collectors", 404),
        ("GET", "/", 404),
    ],
)
def test_bad_requests(client: Client, method: str, target: str, status: int) -> None:
    client.put(DOC)
    assert _error(client.call(method, target.format(uid=UID)))[0] == status


def test_rate_limit(world: World) -> None:
    ticks = iter(range(1000))
    client = _client(world, limiter=RateLimiter(limit=3, window=10, clock=lambda: float(next(ticks))))
    assert [client.call("GET", "/v1/collectors").code for _ in range(4)] == [200, 200, 200, 429]
    assert _error(client.call("GET", "/v1/collectors")) == (429, "rate_limited")
    for _ in range(10):
        ticks.__next__()
    assert client.call("GET", "/v1/collectors").code == 200


def test_messages_follow_accept_language(client: Client) -> None:
    reply = client.call("GET", "/v2", headers={"Accept-Language": "fr-FR,fr;q=0.9,en;q=0.8"})
    assert reply.json() == {"code": "not_found", "message": "Rien ici."}
    reply = client.call("GET", "/v2")
    assert reply.json()["message"] == "Nothing here."


@pytest.mark.parametrize(
    ("header", "expected"),
    [
        (None, "en"),
        ("fr", "fr"),
        ("de, fr;q=0.5, en;q=0.4", "fr"),
        ("en;q=0.1, fr;q=0.9", "fr"),
        ("fr;q=0, en", "en"),
        ("fr;q=abc", "en"),
    ],
)
def test_request_language(header: str | None, expected: str) -> None:
    assert request_language(header, "en") == expected


def test_internal_errors_show_no_detail(client: Client, monkeypatch: pytest.MonkeyPatch) -> None:
    def broken(*args: Any) -> None:
        raise RuntimeError("secret detail")

    monkeypatch.setattr(client.world.app.store, "grants", broken)
    reply = client.call("GET", "/v1/collectors")
    assert _error(reply) == (500, "internal_error")
    assert b"secret" not in reply.body


def test_subscription_listing(client: Client) -> None:
    """GET /v1/subscriptions: the live subscriptions of this pairing only, team ones with their name."""
    core = client.world.app.core
    assert client.call("GET", "/v1/subscriptions").json() == {"subscriptions": []}
    assert client.put(DOC).code == 200
    other = _client(client.world, "desk 4")
    assert other.put(DOC, uid="f" * 32).code == 200
    spec = SubscriptionSpec("fake", {"topic": "team"})
    sync_team(core, [TeamSubscription("news", spec, (client.pairing.key_id,))])
    listed = client.call("GET", "/v1/subscriptions").json()["subscriptions"]
    assert len(listed) == 2
    mine = next(s for s in listed if s["uid"] == UID)
    assert mine == {"uid": UID, "origin": "client", "version": 1}
    team = next(s for s in listed if s["uid"] != UID)
    assert team["origin"] == "team" and team["name"] == "news" and team["version"] == 1
    assert "params" not in team
    assert client.call("DELETE", f"/v1/subscriptions/{UID}").code == 204
    assert [s["uid"] for s in client.call("GET", "/v1/subscriptions").json()["subscriptions"]] == [team["uid"]]
    assert _error(client.call("GET", "/v1/subscriptions?x=1")) == (400, "bad_request")
    assert _error(client.call("POST", "/v1/subscriptions")) == (404, "not_found")


class _Untouchable(io.RawIOBase):
    """A request body that fails the test if the server reads it."""

    def read(self, size: int = -1) -> bytes:
        raise AssertionError("the body was read")

    readline = readinto = read  # type: ignore[assignment]


def test_unauthenticated_requests_are_refused_before_the_body_is_read(client: Client) -> None:
    untouchable = {"wsgi.input": _Untouchable(), "CONTENT_LENGTH": "10"}
    target = f"/v1/subscriptions/{UID}"
    missing = client.call("PUT", target, sign=False, environ=untouchable)
    assert _error(missing) == (401, "bad_authorization")
    stranger = Client(
        client.api,
        client.world,
        Pairing(client.pairing.key_id[::-1], "desk 9", os.urandom(32), client.world.clock.now()),
    )
    assert _error(stranger.call("PUT", target, environ=untouchable)) == (401, "bad_authorization")
    stale = client.call("PUT", target, at=client.world.clock.now() - timedelta(minutes=6), environ=untouchable)
    assert _error(stale) == (401, "stale_date")
    unauthenticated_large = client.call("PUT", target, sign=False, environ={"CONTENT_LENGTH": str(MAX_BODY + 1)})
    assert _error(unauthenticated_large) == (401, "bad_authorization")


def test_unauthenticated_answers_are_limited_for_the_whole_process(world: World) -> None:
    now = [0.0]
    client = _client(world, refusals=RateLimiter(UNAUTHENTICATED_LIMIT, 60, clock=lambda: now[0]))
    other = Client(client.api, world, pairing.create_pairing(world.app.core, "desk 4"))
    untouchable = {"wsgi.input": _Untouchable(), "CONTENT_LENGTH": "10"}
    codes = [client.call("GET", "/v1/collectors", sign=False).code for _ in range(UNAUTHENTICATED_LIMIT)]
    assert codes == [401] * UNAUTHENTICATED_LIMIT
    now[0] = 59.0
    assert _error(client.call("PUT", f"/v1/subscriptions/{UID}", sign=False, environ=untouchable)) == (
        429,
        "rate_limited",
    )
    assert _error(client.call("GET", "/v1/collectors", headers={"Authorization": "Veilleur x:y"})) == (
        429,
        "rate_limited",
    )
    # Authenticated requests, of this pairing or another, are neither counted nor refused.
    assert client.call("GET", "/v1/collectors").code == 200
    assert other.call("GET", "/v1/subscriptions").code == 200
    now[0] = 60.0
    assert _error(client.call("GET", "/v1/collectors", sign=False)) == (401, "bad_authorization")


def test_a_bad_mac_counts_as_an_unauthenticated_answer(world: World) -> None:
    client = _client(world, refusals=RateLimiter(1, 60, clock=lambda: 0.0))
    forged = client.call("PUT", f"/v1/subscriptions/{UID}", b"{}", signed_target=f"/v1/subscriptions/{UID}/state")
    assert _error(forged) == (401, "bad_authorization")
    again = client.call("PUT", f"/v1/subscriptions/{UID}", b"{}", signed_target=f"/v1/subscriptions/{UID}/state")
    assert _error(again) == (429, "rate_limited")
    assert client.call("GET", "/v1/collectors").code == 200


def test_the_default_unauthenticated_limit_is_300_per_minute(client: Client) -> None:
    assert (client.api.refusals.limit, client.api.refusals.window) == (300, 60.0)
