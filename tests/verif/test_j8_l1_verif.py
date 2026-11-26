# SPDX-License-Identifier: EUPL-1.2
"""J8-L1, verifier pass 1: what the lot's own review file (`test_j8_l1_review.py`) leaves out.

Written from `docs/en/protocol.md` §6.1, §6.3, §8, §10.1, §10.2, `docs/SPEC.md` EF-05 (D19) and ES-05, and the plan's
step 1 and acceptance criteria for J8-L1. Every test names the paragraph it comes from.
"""

from __future__ import annotations

import ast
import base64
import hashlib
import hmac
import importlib.util
import json
import re
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
from nacl.signing import SigningKey as NaclSigningKey

from tests.server.fakes import World, make_world
from veilleur.core.domain import errors
from veilleur.core.domain.model import CollectedItem
from veilleur.core.services import pairing, round, subscriptions
from veilleur_protocol import (
    Kind,
    Limits,
    PackageContent,
    ProtocolError,
    Rotation,
    SigningKey,
    decode_pairing_code,
    new_key_id,
    open_package,
    seal_package,
    sign_request,
    verify_request,
    verify_rotation,
)
from veilleur_protocol.signing import is_public_key

ROOT = Path(__file__).resolve().parents[2]
UID = "c" * 32
SECRET = bytes(range(32))
NOW = datetime(2026, 11, 26, 8, 0, tzinfo=UTC)

# --- Edwards25519, written here from RFC 8032 §5.1 --------------------------------------------------------------------

P = 2**255 - 19
L = 2**252 + 27742317777372353535851937790883648493
D = (-121665 * pow(121666, P - 2, P)) % P
SQRT_M1 = pow(2, (P - 1) // 4, P)
Point = tuple[int, int, int, int]
IDENTITY: Point = (0, 1, 1, 0)


def _add(a: Point, b: Point) -> Point:
    x1, y1, z1, t1 = a
    x2, y2, z2, t2 = b
    aa = (y1 - x1) * (y2 - x2) % P
    bb = (y1 + x1) * (y2 + x2) % P
    cc = 2 * t1 * t2 * D % P
    dd = 2 * z1 * z2 % P
    e, f, g, h = bb - aa, dd - cc, dd + cc, bb + aa
    return (e * f % P, g * h % P, f * g % P, e * h % P)


def _mul(n: int, point: Point) -> Point:
    result = IDENTITY
    while n:
        if n & 1:
            result = _add(result, point)
        point = _add(point, point)
        n >>= 1
    return result


def _is_identity(a: Point) -> bool:
    return a[0] % P == 0 and (a[1] - a[2]) % P == 0


def _x_for(y: int, sign: int) -> int | None:
    u, v = (y * y - 1) % P, (D * y * y + 1) % P
    x = (u * pow(v, 3, P) * pow(u * pow(v, 7, P), (P - 5) // 8, P)) % P
    if (v * x * x - u) % P != 0:
        x = x * SQRT_M1 % P
        if (v * x * x - u) % P != 0:
            return None
    if x & 1 != sign:
        x = P - x
    return x


def _point(y: int, sign: int) -> Point:
    x = _x_for(y, sign)
    assert x is not None
    return (x, y, 1, x * y % P)


def _encode(point: Point) -> bytes:
    x, y, z, _ = point
    inverse = pow(z, P - 2, P)
    x, y = x * inverse % P, y * inverse % P
    return (y | ((x & 1) << 255)).to_bytes(32, "little")


def _decode(data: bytes) -> Point:
    number = int.from_bytes(data, "little")
    return _point(number & ((1 << 255) - 1), number >> 255)


NEUTRAL = _encode(IDENTITY)
ORDER_2 = _encode((0, P - 1, 1, 0))
ORDER_4 = _encode(_point(0, 0))  # (x, 0) with x = sqrt(-1): order 4


def _honest_key(seed: int = 3) -> NaclSigningKey:
    return NaclSigningKey(bytes([seed]) * 32)


def _honest_point() -> Point:
    return _decode(bytes(_honest_key().verify_key))


T2: Point = (0, P - 1, 1, 0)
"""The point of order 2: x = 0 like the neutral point, y = -1."""

#: y = 9 gives a point of order 2L (a prime-order point plus the point of order 2, checked below); y + p fits in 255
#: bits, a non-canonical encoding of it.
NON_CANONICAL = (9 + P).to_bytes(32, "little")

MIXED = {
    "honest key plus the point of order 2": _encode(_add(_honest_point(), T2)),
    "honest key plus a point of order 4": _encode(_add(_honest_point(), _decode(ORDER_4))),
    "y = 9, order 2L": _encode(_point(9, 0)),
}


def _b64u(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _checker() -> ModuleType:
    spec = importlib.util.spec_from_file_location("j8_l1_verif_check_vectors", ROOT / "tools" / "check_vectors.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_test_keys_are_what_they_claim() -> None:
    """Self-check of the data, from RFC 8032 §5.1: every key below has a small-order component."""
    assert int.from_bytes(NON_CANONICAL, "little") < 2**255
    assert _encode(_point(9, 0)) != NON_CANONICAL and _decode(NON_CANONICAL)[1] % P == 9
    assert _is_identity(_mul(2, _decode(ORDER_2))) and not _is_identity(_decode(ORDER_2))
    assert _is_identity(_mul(4, _decode(ORDER_4))) and not _is_identity(_mul(2, _decode(ORDER_4)))
    for name, key in MIXED.items():
        mixed = _decode(key)
        assert not _is_identity(_mul(L, mixed)), name
        assert _is_identity(_mul(4 * L, mixed)), name
    for name in ("honest key plus the point of order 2", "y = 9, order 2L"):
        torsion = _mul(L, _decode(MIXED[name]))  # [L]A is the point of order 2: x = 0, y = -1
        assert torsion[0] % P == 0 and (torsion[1] + torsion[2]) % P == 0, name


@pytest.mark.parametrize("name", [*sorted(MIXED), "non-canonical encoding"])
def test_both_readers_refuse_other_weak_keys(name: str) -> None:
    """§6.1: a key MUST be canonical, of the prime-order subgroup (no small-order component, whatever its order)."""
    key = MIXED.get(name, NON_CANONICAL)
    assert not is_public_key(key)
    assert not _checker().key_ok(key)
    document = {
        "v": 1,
        "server": "https://veille.example.org",
        "key_id": new_key_id(),
        "secret": _b64u(SECRET),
        "sign_key": _b64u(key),
    }
    code = "VEIL1:" + _b64u(json.dumps(document).encode())
    with pytest.raises(ProtocolError) as error:
        decode_pairing_code(code)
    assert error.value.code == "bad_pairing_code"


# --- §6.1 and §10.2 step 7, at the level of a whole package ---------------------------------------------------------


class _NeutralForger:
    """Stands for a signing key: signs every manifest with R = neutral point, S = 0 (valid under the neutral key)."""

    public_key = NEUTRAL

    def sign(self, message: bytes) -> bytes:
        return NEUTRAL + bytes(32)


def _content(rotation: Rotation | None = None) -> PackageContent:
    return PackageContent(
        uid=UID, seq=1, kind=Kind.STATE, created_at=NOW, period_to=NOW, period_from=None, items=b"", rotation=rotation
    )


def _checker_case(envelope: bytes, trusted: list[bytes], limits: dict[str, int] | None = None) -> dict[str, Any]:
    return {
        "secret": SECRET.hex(),
        "envelope": envelope.hex(),
        "uid": UID,
        "seq": 1,
        "trusted_keys": [k.hex() for k in trusted],
        "limits": limits,
    }


def test_a_package_forged_for_the_neutral_key_is_refused_by_both_readers() -> None:
    """§6.1 "a signature under it never verifies", §10.2 step 7: even if a reader were told to trust the key."""
    envelope = seal_package(SECRET, _NeutralForger(), _content())  # type: ignore[arg-type]
    with pytest.raises(ProtocolError) as error:
        open_package(envelope, secret=SECRET, uid=UID, trusted_keys=[NEUTRAL], seq=1)
    assert error.value.code == "bad_signature"
    checker = _checker()
    with pytest.raises(checker.Refused) as refused:
        checker.open_package(_checker_case(envelope, [NEUTRAL]))
    assert refused.value.code == "bad_signature"


def _statement(old: SigningKey, new_key: bytes, padding: str | None = None) -> Rotation:
    document: dict[str, Any] = {
        "protocol": "1.0",
        "old_key": _b64u(old.public_key),
        "new_key": _b64u(new_key),
        "issued_at": "2026-11-26T08:00:00Z",
    }
    if padding is not None:
        document["note"] = padding
    statement = json.dumps(document, separators=(",", ":")).encode()
    return Rotation(old.public_key, new_key, NOW, statement, old.sign(statement))


@pytest.mark.parametrize("name", sorted(MIXED))
def test_a_package_rotating_to_a_weak_key_is_refused_by_both_readers(name: str) -> None:
    """§6.3 and §10.2 step 7: a rotation statement naming a weak incoming key is `bad_rotation`, in a package too."""
    old = SigningKey(bytes(32))
    envelope = seal_package(SECRET, old, _content(_statement(old, MIXED[name])))
    with pytest.raises(ProtocolError) as error:
        open_package(envelope, secret=SECRET, uid=UID, trusted_keys=[old.public_key], seq=1)
    assert error.value.code == "bad_rotation"
    checker = _checker()
    with pytest.raises(checker.Refused) as refused:
        checker.open_package(_checker_case(envelope, [old.public_key]))
    assert refused.value.code == "bad_rotation"


class _TwinSigner:
    """Signs with the scalar of an honest key under its twin A + T2 (order 2L), as RFC 8032 §5.1.6 would."""

    def __init__(self, seed: bytes) -> None:
        digest = hashlib.sha512(seed).digest()
        scalar = int.from_bytes(digest[:32], "little")
        self.scalar = (scalar & ((1 << 254) - 8)) | (1 << 254)
        self.prefix = digest[32:]
        self.base = _point(4 * pow(5, P - 2, P) % P, 0)
        honest = _mul(self.scalar, self.base)
        assert _encode(honest) == bytes(NaclSigningKey(seed).verify_key)
        self.public_key = _encode(_add(honest, T2))

    def sign(self, message: bytes) -> bytes:
        r = int.from_bytes(hashlib.sha512(self.prefix + message).digest(), "little") % L
        big_r = _encode(_mul(r, self.base))
        k = int.from_bytes(hashlib.sha512(big_r + self.public_key + message).digest(), "little") % L
        return big_r + ((r + k * self.scalar) % L).to_bytes(32, "little")


def test_no_reader_adopts_a_key_with_a_component_of_order_2() -> None:
    """§6.1 (no small-order component; "makes every reader agree") and §10.2 step 7: a trusted outgoing key that
    names the twin A + T2 of an honest key must give `bad_rotation`, never an adopted key."""
    old, twin = SigningKey(bytes(32)), _TwinSigner(bytes([3]) * 32)
    envelope = seal_package(SECRET, twin, _content(_statement(old, twin.public_key)))  # type: ignore[arg-type]
    checker = _checker()
    with pytest.raises(checker.Refused) as refused:
        checker.open_package(_checker_case(envelope, [old.public_key]))
    assert refused.value.code == "bad_rotation"
    with pytest.raises(ProtocolError) as error:
        open_package(envelope, secret=SECRET, uid=UID, trusted_keys=[old.public_key], seq=1)
    assert error.value.code == "bad_rotation"


def test_a_lowered_file_limit_bounds_rotation_json_in_both_readers() -> None:
    """§10.1: "a lowered limit for one file also bounds the files listed in parentheses" (`rotation.json`)."""
    old, new = SigningKey(bytes(32)), SigningKey(bytes([1]) * 32)
    rotation = _statement(old, new.public_key, padding="x" * 2000)
    verify_rotation(rotation.statement, rotation.signature)  # a well-formed statement, larger than the manifest
    envelope = seal_package(SECRET, new, _content(rotation))
    limits = Limits(max_file=1500)
    opened = open_package(envelope, secret=SECRET, uid=UID, trusted_keys=[old.public_key], seq=1)  # control
    assert opened.rotation is not None
    with pytest.raises(ProtocolError) as error:
        open_package(envelope, secret=SECRET, uid=UID, trusted_keys=[old.public_key], seq=1, limits=limits)
    assert error.value.code == "file_too_large"
    checker = _checker()
    lowered = {"max_package": 64 << 20, "max_files": 32, "max_file": 1500, "max_total": 128 << 20}
    checker.open_package(_checker_case(envelope, [old.public_key]))  # control
    with pytest.raises(checker.Refused) as refused:
        checker.open_package(_checker_case(envelope, [old.public_key], lowered))
    assert refused.value.code == "file_too_large"


# --- §8: the request form, in the library and in the checker ---------------------------------------------------------


def _checker_request(method: str, path: str, date: str) -> dict[str, Any]:
    key_id = "0123456789abcdef"
    return {
        "authorization": f"Veilleur {key_id}:" + _b64u(bytes(32)),
        "method": method,
        "path_and_query": path,
        "date": date,
        "now": "2026-11-26T08:00:00Z",
        "body": "",
        "secret": SECRET.hex(),
    }


BAD_FORMS = {
    "lower-case method": ("get", "/v1/pairing"),
    "mixed-case method": ("Get", "/v1/pairing"),
    "method with a digit": ("GET2", "/v1/pairing"),
    "path with a line feed": ("GET", "/v1/pairing\nX"),
    "non-ASCII path": ("GET", "/v1/é"),
    "path not starting with /": ("GET", "v1/pairing"),
}


@pytest.mark.parametrize("name", sorted(BAD_FORMS))
def test_a_request_of_the_wrong_form_is_bad_authorization_in_both(name: str) -> None:
    """§8: method in upper-case letters, path ASCII from `/` without line feed, "otherwise ... `bad_authorization`"."""
    method, path = BAD_FORMS[name]
    with pytest.raises(ProtocolError) as error:
        sign_request(SECRET, "0123456789abcdef", method, path, b"", NOW)
    assert error.value.code == "bad_authorization"
    # A MAC computed by hand over the string to sign, as a client that ignores the rule would.
    date = "2026-11-26T08:00:00Z"
    message = "\n".join((method, path, date, hashlib.sha256(b"").hexdigest())).encode()
    from veilleur_protocol import Usage, derive_key, request_scope

    try:
        scope = request_scope(path)
    except ProtocolError:
        scope = None
    mac = hmac.digest(derive_key(SECRET, Usage.AUTH, scope), message, "sha256")
    header = f"Veilleur 0123456789abcdef:{_b64u(mac)}"
    with pytest.raises(ProtocolError) as error:
        verify_request(SECRET, method, path, b"", authorization=header, date=date, now=NOW)
    assert error.value.code == "bad_authorization"
    checker = _checker()
    case = _checker_request(method, path, date)
    case["authorization"] = header
    with pytest.raises(checker.Refused) as refused:
        checker.verify_request(case)
    assert refused.value.code == "bad_authorization"


@pytest.mark.xfail(
    strict=True,
    reason="out of spec (R40): §8 does not place the request-form check in its order; the library answers bad_date, "
    "the checker bad_authorization",
)
def test_both_implementations_give_the_same_code_for_a_bad_form_and_a_bad_date() -> None:
    """§8 orders the header, the date, then the MAC; the form refusal is not placed. Two readers should agree."""
    header = "Veilleur 0123456789abcdef:" + _b64u(bytes(32))
    with pytest.raises(ProtocolError) as error:
        verify_request(SECRET, "get", "/v1/pairing", b"", authorization=header, date="yesterday", now=NOW)
    checker = _checker()
    with pytest.raises(checker.Refused) as refused:
        checker.verify_request(_checker_request("get", "/v1/pairing", "yesterday"))
    assert error.value.code == refused.value.code


# --- EF-05 (D19): depth of an item ---------------------------------------------------------------------------------


@pytest.fixture
def world(tmp_path: Path) -> Any:
    w = make_world(tmp_path / "state")
    yield w
    w.app.close()


def _subscribe(world: World, topic: str, uid: str) -> str:
    p = pairing.create_pairing(world.app.core, f"desk {topic}")
    subscriptions.put_subscription(
        world.app.core, p.key_id, uid, 0, {"collector": "fake", "params": {"topic": topic}, "frequency": "every_round"}
    )
    return p.key_id


def _items(world: World, key_id: str, uid: str, seq: int) -> dict[str, Any]:
    data = world.app.store.get_package(key_id, uid, seq)
    assert data is not None
    secret = world.app.store.get_pairing(key_id).secret  # type: ignore[union-attr]
    opened = open_package(data, secret=secret, uid=uid, trusted_keys=[world.app.core.sealer.public_key], seq=seq)
    return {item.key: item.fields for item in opened.items}


def _lists(levels: int) -> dict[str, Any]:
    """`fields` (one level) holding `levels - 1` nested lists."""
    value: Any = "leaf"
    for _ in range(levels - 1):
        value = [value]
    return {"a": value}


@pytest.mark.parametrize(("levels", "accepted"), [(1, True), (100, True), (101, False)])
def test_the_limit_counts_lists_too(world: World, levels: int, accepted: bool) -> None:
    """EF-05 (D19): lists and objects nest on at most 100 levels, `fields` counting as one."""
    key_id, uid = _subscribe(world, "news", "a" * 32), "a" * 32
    world.collector.items["news"] = [CollectedItem(_lists(levels), key="k")]
    round.run_round(world.app.core)
    status = world.app.store.get_source(world.app.store.get_subscription(key_id, uid).spec.collection_id)  # type: ignore[union-attr]
    assert status is not None
    assert status.error == (None if accepted else errors.BAD_ITEM)
    if accepted:  # the item of 100 levels reaches the receiving tool intact
        assert _items(world, key_id, uid, 1) == {"k": _lists(levels)}


def test_the_valid_items_of_a_partial_collection_are_reported(world: World) -> None:
    """EF-05 (D19): a too-deep item is left out and "rend la collecte partielle": the other items are delivered."""
    key_id, uid = _subscribe(world, "news", "a" * 32), "a" * 32
    world.collector.items["news"] = [CollectedItem({"t": "ok"}, key="ok"), CollectedItem(_lists(5_000), key="deep")]
    round.run_round(world.app.core)
    assert _items(world, key_id, uid, 1) == {"ok": {"t": "ok"}}


def test_an_item_that_contains_itself_is_a_bad_item(world: World) -> None:
    """EF-05: a plugin may hand a cyclic object; it is invalid and the round goes on (the depth walk ends on it)."""
    key_id, uid = _subscribe(world, "loop", "a" * 32), "a" * 32
    fine_key, fine_uid = _subscribe(world, "fine", "f" * 32), "f" * 32
    cyclic: dict[str, Any] = {}
    cyclic["self"] = cyclic
    world.collector.items["loop"] = [CollectedItem(cyclic, key="loop")]
    world.collector.set("fine", ("a", {"title": "A"}))
    round.run_round(world.app.core)
    status = world.app.store.get_source(world.app.store.get_subscription(key_id, uid).spec.collection_id)  # type: ignore[union-attr]
    assert status is not None and status.error == errors.BAD_ITEM
    assert world.app.store.package_bounds(fine_key, fine_uid).last == 1


# --- Criterion 1 of J8-L1: every test of the review cites the paragraph it comes from ------------------------------

_REFERENCE = re.compile(r"§\s?\d|\b(ES|EF|ENF)-\d|ADR-\d|RFC \d")


@pytest.mark.xfail(
    strict=True,
    reason="minor (R39): J8-L1 criterion 1, some tests of test_j8_l1_review.py cite no paragraph of the specification",
)
def test_every_review_test_cites_its_paragraph() -> None:
    """Plan J8-L1, criterion 1: "cite pour chaque test le paragraphe de la spécification dont il vient"."""
    tree = ast.parse((ROOT / "tests" / "verif" / "test_j8_l1_review.py").read_text(encoding="utf-8"))
    uncited = [
        node.name
        for node in tree.body
        if isinstance(node, ast.FunctionDef)
        and node.name.startswith("test_")
        and not _REFERENCE.search(ast.get_docstring(node) or "")
    ]
    assert uncited == []


# --- Pass 2 (after commit 44aefc4): every small-order component, alone or added to an honest key -------------------


def _torsion() -> list[Point]:
    """The 8 points of the torsion subgroup (RFC 8032 §5.1: the curve has order 8L), built as [L]P for points P."""
    found: dict[bytes, Point] = {_encode(IDENTITY): IDENTITY}
    y = 2
    while len(found) < 8:
        x = _x_for(y, 0)
        if x is not None:
            t = _mul(L, (x, y, 1, x * y % P))
            for k in range(8):
                multiple = _mul(k, t)
                found.setdefault(_encode(multiple), multiple)
        y += 1
    return list(found.values())


TORSION = _torsion()


def test_the_torsion_points_are_what_they_claim() -> None:
    """Self-check of the data: 8 distinct points, each killed by 8, one of order 8 at least."""
    assert len({_encode(t) for t in TORSION}) == 8
    assert all(_is_identity(_mul(8, t)) for t in TORSION)
    assert any(not _is_identity(_mul(4, t)) for t in TORSION)


@pytest.mark.parametrize("index", range(8))
def test_a_small_order_point_alone_is_refused_by_both_readers(index: int) -> None:
    """§6.1: a key of small order (the neutral point included) is not a key; libsodium agrees."""
    key = _encode(TORSION[index])
    assert not is_public_key(key)
    assert not _checker().key_ok(key)


@pytest.mark.parametrize("index", range(8))
@pytest.mark.parametrize("seed", [3, 7, 200])
def test_an_honest_key_plus_any_torsion_point_is_judged_alike(index: int, seed: int) -> None:
    """§6.1 ("no small-order component"; "makes every reader agree", ADR-0008): A + T is a key only when T is the
    neutral point, for the library and libsodium alike."""
    honest = _decode(bytes(_honest_key(seed).verify_key))
    key = _encode(_add(honest, TORSION[index]))
    expected = _is_identity(TORSION[index])
    assert is_public_key(key) is expected
    assert _checker().key_ok(key) is expected


@pytest.mark.parametrize("seed", range(20))
def test_no_honest_key_is_refused(seed: int) -> None:
    """§6.1 / signing.py docstring: requiring order L refuses no honest key."""
    key = SigningKey(hashlib.sha256(bytes([seed])).digest()).public_key
    assert is_public_key(key)
    assert _checker().key_ok(key)
