# SPDX-License-Identifier: EUPL-1.2
"""Independent check of the `/v1` interface of milestone G2 (spec §7.4, ES-06, ES-09, ES-11; protocol §8, §9).

The WSGI application is called directly: no port is opened.
"""

from __future__ import annotations

import contextlib
import io
import json
import logging
from collections.abc import Iterator
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from tests.server.fakes import World, make_world
from veilleur.apps.server.service import _Handler
from veilleur.apps.server.wsgi import Api
from veilleur.core.domain.model import Origin, Pairing
from veilleur.core.services import jobs, pairing, round, subscriptions
from veilleur.core.services.subscriptions import TeamSubscription, sync_team
from veilleur_protocol import Kind, open_package, seal_subscription, sign_request

UID = "aaaabbbbccccddddeeeeffff00001111"
DOC = {"collector": "fake", "params": {"topic": "confidential-topic"}, "frequency": "every_round"}


@pytest.fixture
def world(tmp_path: Path) -> Iterator[World]:
    w = make_world(tmp_path / "state")
    yield w
    w.app.close()


class Caller:
    def __init__(self, world: World, p: Pairing, api: Api | None = None) -> None:
        self.world, self.pairing = world, p
        self.api = api or Api(world.app.core)

    def __call__(
        self,
        method: str,
        target: str,
        body: bytes = b"",
        *,
        headers: dict[str, str] | None = None,
        at: datetime | None = None,
        sign: bool = True,
        environ: dict[str, Any] | None = None,
    ) -> tuple[int, dict[str, str], bytes]:
        env: dict[str, Any] = {
            "REQUEST_METHOD": method,
            "REQUEST_URI": target,
            "CONTENT_LENGTH": str(len(body)),
            "wsgi.input": io.BytesIO(body),
        }
        if sign:
            s = sign_request(
                self.pairing.secret, self.pairing.key_id, method, target, body, at or self.world.clock.now()
            )
            env["HTTP_AUTHORIZATION"], env["HTTP_X_VEILLEUR_DATE"] = s.authorization, s.date
        for k, v in (headers or {}).items():
            env["HTTP_" + k.upper().replace("-", "_")] = v
        env.update(environ or {})
        seen: dict[str, Any] = {}

        def start(status: str, hs: list[tuple[str, str]]) -> None:
            seen["s"], seen["h"] = status, dict(hs)

        data = b"".join(self.api(env, start))
        assert seen["h"]["Cache-Control"] == "no-store"
        return int(seen["s"].split()[0]), seen["h"], data

    def put(self, document: dict[str, Any], base: int = 0, uid: str = UID) -> tuple[int, dict[str, str], bytes]:
        return self("PUT", f"/v1/subscriptions/{uid}", seal_subscription(self.pairing.secret, uid, base, document))


@pytest.fixture
def call(world: World) -> Caller:
    return Caller(world, pairing.create_pairing(world.app.core, "desk 1"))


def _code(reply: tuple[int, dict[str, str], bytes]) -> tuple[int, str]:
    status, headers, body = reply
    document = json.loads(body)
    assert set(document) == {"code", "message"} and headers["Content-Type"] == "application/json"
    return status, document["code"]


# --- §8: authentication -------------------------------------------------------------------------------------------


def test_date_tolerance_is_five_minutes(call: Caller) -> None:
    now = call.world.clock.now()
    assert call("GET", "/v1/collectors", at=now - timedelta(minutes=5))[0] == 200
    assert call("GET", "/v1/collectors", at=now + timedelta(minutes=5))[0] == 200
    assert _code(call("GET", "/v1/collectors", at=now + timedelta(minutes=5, seconds=1))) == (401, "stale_date")


def test_unknown_key_id_checks_header_date_and_staleness_first(call: Caller) -> None:
    stranger = Caller(call.world, Pairing("0" * 16, "x", bytes(32), call.world.clock.now()), call.api)
    old = call.world.clock.now() - timedelta(hours=1)
    assert _code(stranger("GET", f"/v1/subscriptions/{UID}/reports", at=old)) == (401, "stale_date")
    assert _code(stranger("GET", f"/v1/subscriptions/{UID}/reports", headers={"X-Veilleur-Date": ""})) == (
        401,
        "bad_date",
    )
    assert _code(stranger("PUT", f"/v1/subscriptions/{UID}", b"x")) == (401, "bad_authorization")


def test_subscription_requests_need_the_subscription_key(call: Caller) -> None:
    """ES-02: a request about a subscription is signed with that subscription's key, not the pairing's."""
    call.put(DOC)
    target = f"/v1/subscriptions/{UID}/reports"
    signed = sign_request(
        call.pairing.secret, call.pairing.key_id, "GET", "/v1/collectors", b"", call.world.clock.now()
    )
    # Reuse a MAC computed with the pairing-wide key for the subscription path.
    import hashlib
    import hmac

    from veilleur_protocol.encoding import b64u_encode
    from veilleur_protocol.keys import Usage, derive_key

    key = derive_key(call.pairing.secret, Usage.AUTH, None)
    message = "\n".join(("GET", target, signed.date, hashlib.sha256(b"").hexdigest())).encode()
    mac = b64u_encode(hmac.digest(key, message, "sha256"))
    headers = {"Authorization": f"Veilleur {call.pairing.key_id}:{mac}", "X-Veilleur-Date": signed.date}
    assert _code(call("GET", target, sign=False, headers=headers)) == (401, "bad_authorization")


def test_non_ascii_target_is_refused(call: Caller) -> None:
    reply = call("GET", "/v1/collectors", sign=True, environ={"REQUEST_URI": "/v1/colléctors"})
    assert _code(reply) == (401, "bad_authorization")


# --- §9: routes ------------------------------------------------------------------------------------------------------


def test_put_returns_version_and_team_subscriptions_are_read_only(call: Caller) -> None:
    status, headers, body = call.put(DOC)
    assert status == 200 and json.loads(body) == {"version": 1} and headers["Content-Type"] == "application/json"
    core = call.world.app.core
    spec = subscriptions.parse_spec(DOC, core.plugins)
    sync_team(core, [TeamSubscription("team", spec, (call.pairing.key_id,))])
    team = next(s for s in core.store.list_subscriptions() if s.origin is Origin.TEAM)
    assert _code(call.put(DOC, base=1, uid=team.uid)) == (403, "team_subscription")
    assert _code(call("DELETE", f"/v1/subscriptions/{team.uid}")) == (403, "team_subscription")
    # A team subscription is served to its pairing like any other.
    call.world.collector.set("confidential-topic", ("a", {"t": 1}))
    round.run_round(core)
    status, _, package = call("GET", f"/v1/subscriptions/{team.uid}/reports/1")
    assert status == 200
    opened = open_package(package, secret=call.pairing.secret, uid=team.uid, trusted_keys=[core.sealer.public_key])
    assert opened.kind is Kind.STATE


def test_reports_listing_shape(call: Caller) -> None:
    call.put(DOC)
    call.world.collector.set("confidential-topic", ("a", {"t": 1}))
    round.run_round(call.world.app.core)
    status, _, body = call("GET", f"/v1/subscriptions/{UID}/reports?after=5")
    assert status == 200 and json.loads(body) == {"packages": [], "oldest": 1, "last": 1}
    listing = json.loads(call("GET", f"/v1/subscriptions/{UID}/reports?after=0")[2])
    assert set(listing["packages"][0]) == {"seq", "size", "sha256"}
    package = call("GET", f"/v1/subscriptions/{UID}/reports/1")[2]
    import hashlib

    assert listing["packages"][0]["sha256"] == hashlib.sha256(package).hexdigest()


def test_state_before_the_first_collection_answers_202(call: Caller) -> None:
    call.put(DOC)
    call.world.collector.fail = "network_unavailable"
    jobs.run_pending(call.world.app.core)
    status, headers, body = call("GET", f"/v1/subscriptions/{UID}/state")
    assert (status, headers.get("Retry-After"), body) == (202, "5", b"")
    call.world.collector.fail = None
    call.world.collector.set("confidential-topic")
    round.run_round(call.world.app.core)
    assert json.loads(call("GET", f"/v1/subscriptions/{UID}/reports")[2])["last"] == 1


def test_history_answers_202_then_the_package(call: Caller) -> None:
    call.put(DOC)
    call.world.collector.set("confidential-topic", ("a", {"t": 1}))
    jobs.run_pending(call.world.app.core)
    status, headers, _ = call("GET", f"/v1/subscriptions/{UID}/history?since=2026-11-01")
    assert status == 202 and headers["Retry-After"].isdigit()
    jobs.run_pending(call.world.app.core)
    status, headers, data = call("GET", f"/v1/subscriptions/{UID}/history?since=2026-11-01")
    assert status == 200 and headers["Content-Type"] == "application/octet-stream"
    opened = open_package(
        data, secret=call.pairing.secret, uid=UID, trusted_keys=[call.world.app.core.sealer.public_key]
    )
    assert opened.kind is Kind.HISTORY and opened.seq == 1
    assert opened.manifest["period"]["from"] == "2026-11-01T00:00:00Z"


@pytest.mark.parametrize(
    "target",
    [
        f"/v1/subscriptions/{UID}/history?since=2026-1-01",
        f"/v1/subscriptions/{UID}/history?since=2026-02-30",
        f"/v1/subscriptions/{UID}/history?since=2026-11-01&since=2026-11-02",
        f"/v1/subscriptions/{UID}/reports?after=",
        f"/v1/subscriptions/{UID}/reports?after=-1",
        f"/v1/subscriptions/{UID}/reports?AFTER=1",
        f"/v1/subscriptions/{UID}/reports/1?x=1",
        f"/v1/subscriptions/{UID}?x=1",
    ],
)
def test_unlisted_queries_are_400(call: Caller, target: str) -> None:
    call.put(DOC)
    method = "DELETE" if target.endswith("?x=1") and "/reports" not in target else "GET"
    assert _code(call(method, target)) == (400, "bad_request")


@pytest.mark.parametrize(
    "target",
    [
        f"/v1/subscriptions/{UID}/",
        f"/v1/subscriptions/{UID}/reports/",
        f"/v1/subscriptions/{UID}//reports",
        f"/v1/subscriptions/{UID}/reports/1/x",
        "/v1/collectors/",
        "/v1//collectors",
        # "/v1/subscriptions" became a route in G3 (GET /v1/subscriptions, decided by the user on 2026-11-18).
        "/v1/subscription",
    ],
)
def test_other_paths_are_404(call: Caller, target: str) -> None:
    call.put(DOC)
    assert _code(call("GET", target)) == (404, "not_found")


def test_deleted_subscription_is_no_longer_served(call: Caller) -> None:
    call.put(DOC)
    call.world.collector.set("confidential-topic", ("a", {"t": 1}))
    jobs.run_pending(call.world.app.core)
    assert call("DELETE", f"/v1/subscriptions/{UID}")[0] == 204
    for route in ("/reports", "/reports/1", "/state", "/history?since=2026-11-01"):
        assert _code(call("GET", f"/v1/subscriptions/{UID}{route}")) == (404, "not_found")
    assert call("DELETE", f"/v1/subscriptions/{UID}")[0] == 204
    assert _code(call.put(DOC, base=0)) == (409, "subscription_deleted")


def test_delete_of_an_unknown_uid(call: Caller) -> None:
    assert _code(call("DELETE", f"/v1/subscriptions/{UID}")) == (404, "not_found")


def test_body_limit_is_exactly_one_million_bytes(call: Caller) -> None:
    exactly = b"\x00" * 1_000_000
    status, _ = _code(call("PUT", f"/v1/subscriptions/{UID}", exactly))
    assert status == 400  # read and refused as an envelope, not as too large
    assert _code(call("PUT", f"/v1/subscriptions/{UID}", exactly + b"\x00")) == (413, "body_too_large")


def test_truncated_body_is_400(call: Caller) -> None:
    reply = call("PUT", f"/v1/subscriptions/{UID}", b"abc", environ={"CONTENT_LENGTH": "10"})
    assert _code(reply) == (400, "bad_request")


def test_default_rate_limit_is_120_per_minute(call: Caller) -> None:
    statuses = [call("GET", "/v1/collectors")[0] for _ in range(121)]
    assert statuses[:120] == [200] * 120 and statuses[120] == 429
    other = Caller(call.world, pairing.create_pairing(call.world.app.core, "desk 2"), call.api)
    assert other("GET", "/v1/collectors")[0] == 200


def test_french_messages_for_every_api_code(call: Caller) -> None:
    fr = {"Accept-Language": "fr"}
    _, _, body = call("GET", "/v1/collectors", headers=fr, at=call.world.clock.now() - timedelta(hours=1))
    document = json.loads(body)
    assert document["code"] == "stale_date" and "minutes" in document["message"]
    assert "server" not in document["message"]
    reply = call(
        "PUT",
        f"/v1/subscriptions/{UID}",
        seal_subscription(call.pairing.secret, UID, 0, {"collector": "fetch", "params": {"topic": "x"}}),
        headers=fr,
    )
    message = json.loads(reply[2])["message"]
    assert reply[0] == 403 and "fetch" in message and "allowed" not in message


# --- ES-09: nothing about a request in the logs; no client address ------------------------------------------------


def test_logs_hold_no_request_secret_or_parameter(call: Caller, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)
    call.put(DOC)
    call.world.collector.fail = "crash"
    jobs.run_pending(call.world.app.core)
    round.run_round(call.world.app.core)
    call("GET", f"/v1/subscriptions/{UID}/state")
    call("GET", "/v1/collectors", headers={"Authorization": "Veilleur " + call.pairing.key_id + ":" + "A" * 43})
    events = " ".join(f"{e.code} {e.params}" for e in call.world.app.store.events(100))
    text = caplog.text + events
    assert call.pairing.secret.hex() not in text
    assert "confidential-topic" not in text
    assert "Veilleur " not in text and "X-Veilleur-Date" not in text


def test_handler_passes_the_raw_target_and_drops_the_client_address() -> None:
    """ES-09 and protocol §8: the HTTP handler gives the raw request target and no client address."""
    from email.message import Message

    handler = _Handler.__new__(_Handler)
    handler.server = type("S", (), {"base_environ": {}, "get_app": lambda self: None})()
    handler.command = "GET"
    handler.path = f"/v1/subscriptions/{UID}/repor%74s?after=0"
    handler.request_version = "HTTP/1.1"
    handler.client_address = ("192.0.2.7", 40000)
    handler.headers = Message()
    handler.rfile = io.BytesIO()
    environ = handler.get_environ()
    assert environ["REQUEST_URI"] == f"/v1/subscriptions/{UID}/repor%74s?after=0"
    assert "192.0.2.7" not in repr(environ)
    err = io.StringIO()
    with contextlib.redirect_stderr(err):
        handler.log_message("%s", "192.0.2.7")
    assert err.getvalue() == ""


# --- EF-62: a revoked pairing ---------------------------------------------------------------------------------------


def test_revoked_pairing_gets_403_on_every_route(call: Caller) -> None:
    call.put(DOC)
    pairing.revoke_pairing(call.world.app.core, call.pairing.key_id)
    for method, target in (
        ("GET", "/v1/collectors"),
        ("PUT", f"/v1/subscriptions/{UID}"),
        ("DELETE", f"/v1/subscriptions/{UID}"),
        ("GET", f"/v1/subscriptions/{UID}/reports"),
        ("GET", f"/v1/subscriptions/{UID}/state"),
        ("GET", f"/v1/subscriptions/{UID}/history?since=2026-11-01"),
    ):
        assert _code(call(method, target)) == (403, "revoked")


# --- Separate uid spaces ----------------------------------------------------------------------------------------------


def test_same_uid_in_two_pairings_are_two_subscriptions(world: World) -> None:
    a = Caller(world, pairing.create_pairing(world.app.core, "desk 1"))
    b = Caller(world, pairing.create_pairing(world.app.core, "desk 2"), a.api)
    assert a.put(DOC)[0] == 200
    assert b.put({**DOC, "params": {"topic": "other"}})[0] == 200
    world.collector.set("confidential-topic", ("a", {"t": 1}))
    world.collector.set("other", ("b", {"t": 1}))
    round.run_round(world.app.core)
    for caller, key in ((a, "a"), (b, "b")):
        data = caller("GET", f"/v1/subscriptions/{UID}/reports/1")[2]
        opened = open_package(
            data, secret=caller.pairing.secret, uid=UID, trusted_keys=[world.app.core.sealer.public_key]
        )
        assert [i.key for i in opened.items] == [key]
    assert a("DELETE", f"/v1/subscriptions/{UID}")[0] == 204
    assert b("GET", f"/v1/subscriptions/{UID}/reports")[0] == 200


def test_end_to_end_with_a_fresh_world(tmp_path: Path) -> None:
    w = make_world(tmp_path / "state")
    try:
        c = Caller(w, pairing.create_pairing(w.app.core, "desk 1"))
        w.collector.set("confidential-topic", ("a", {"t": 1}))
        assert c.put(DOC)[0] == 200
        jobs.run_pending(w.app.core)
        assert json.loads(c("GET", f"/v1/subscriptions/{UID}/reports")[2])["last"] == 1
    finally:
        w.app.close()


@pytest.mark.xfail(
    reason="minor: a lone surrogate in parameters is refused with 500 internal_error instead of a 400 code (EF-12)",
    strict=True,
)
def test_lone_surrogate_in_parameters_is_a_400(call: Caller) -> None:
    from veilleur_protocol.envelope import Header, seal
    from veilleur_protocol.envelope import Kind as EnvelopeKind

    plain = b'{"collector":"fake","params":{"topic":"\\ud800"}}'
    body = seal(call.pairing.secret, Header(UID, 0, EnvelopeKind.SUBSCRIPTION), plain)
    status, _ = _code(call("PUT", f"/v1/subscriptions/{UID}", body))
    assert status == 400
    assert call.world.app.store.get_subscription(call.pairing.key_id, UID) is None
