# SPDX-License-Identifier: EUPL-1.2
"""J8-L1: independent review of the three fixes no verifier had read (reservation R01).

Written from the specification only, before reading the diffs `383b9ca..a48c755`, `0e30a66` and `bdc6946`:

- `docs/en/protocol.md` §6.1 (small-order public keys), §6.3 (rotation statements), §10.1 (reader limits);
- `docs/en/threat-model.md` §4 (compromised outgoing key);
- `docs/SPEC.md` ES-04, ES-05, EF-05 and ADR-0019 (accepted limit of two rotations over a purged gap).

Each test names the paragraph it comes from. The Edwards-curve arithmetic below is written here, from RFC 8032 §5.1,
so that the list of weak keys does not come from the code under review.
"""

from __future__ import annotations

import base64
import importlib.util
import json
import re
from collections.abc import Callable
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
from nacl.signing import SigningKey as NaclSigningKey

from tests.server.fakes import World, make_world
from veilleur.core.domain import errors
from veilleur.core.domain.model import CollectedItem
from veilleur.core.services import pairing, round, subscriptions
from veilleur_protocol import ProtocolError, decode_pairing_code, new_key_id, verify_rotation
from veilleur_protocol.signing import is_public_key, verify

ROOT = Path(__file__).resolve().parents[2]

# --- Edwards25519 arithmetic (RFC 8032 §5.1), independent of the code under review ---------------------------------

P = 2**255 - 19
L = 2**252 + 27742317777372353535851937790883648493
D = (-121665 * pow(121666, P - 2, P)) % P
SQRT_M1 = pow(2, (P - 1) // 4, P)
Point = tuple[int, int, int, int]  # extended coordinates (X, Y, Z, T)
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


def _equal(a: Point, b: Point) -> bool:
    return (a[0] * b[2] - b[0] * a[2]) % P == 0 and (a[1] * b[2] - b[1] * a[2]) % P == 0


def _decode(data: bytes, *, canonical: bool = True) -> Point | None:
    """RFC 8032 §5.1.3; with `canonical=False`, reduces y modulo p as lenient libraries do."""
    number = int.from_bytes(data, "little")
    sign = number >> 255
    y = number & ((1 << 255) - 1)
    if y >= P:
        if canonical:
            return None
        y -= P
    u, v = (y * y - 1) % P, (D * y * y + 1) % P
    x = (u * pow(v, 3, P) * pow(u * pow(v, 7, P), (P - 5) // 8, P)) % P
    if (v * x * x - u) % P != 0:
        x = x * SQRT_M1 % P
        if (v * x * x - u) % P != 0:
            return None
    if x == 0 and sign:
        if canonical:
            return None
    elif x & 1 != sign:
        x = P - x
    return (x, y, 1, x * y % P)


def _encode(point: Point) -> bytes:
    x, y, z, _ = point
    inverse = pow(z, P - 2, P)
    x, y = x * inverse % P, y * inverse % P
    return (y | ((x & 1) << 255)).to_bytes(32, "little")


def _h(text: str) -> bytes:
    return bytes.fromhex(text)


ORDER_8 = _h("c7176a703d4dd84fba3c0b760d10670f2a2053fa2c39ccc64ec7fd7792ac037a")

#: The eight points of the small-order subgroup, canonically encoded (§6.1: "other than the neutral point (no
#: small-order component)"): the neutral point, the point of order 2, two of order 4, four of order 8.
SMALL_ORDER_CANONICAL = {
    "neutral": _h("01" + "00" * 31),
    "order 2": _h("ec" + "ff" * 30 + "7f"),
    "order 4 (+)": _h("00" * 32),
    "order 4 (-)": _h("00" * 31 + "80"),
    "order 8 (a+)": ORDER_8,
    "order 8 (a-)": ORDER_8[:31] + bytes([ORDER_8[31] | 0x80]),
    "order 8 (b+)": _h("26e8958fc2b227b045c3f489f2ef98f0d5dfac05d3c63339b13802886d53fc05"),
    "order 8 (b-)": _h("26e8958fc2b227b045c3f489f2ef98f0d5dfac05d3c63339b13802886d53fc85"),
}

#: Non-canonical encodings of small-order points (§6.1: "the canonical encoding of a point"), the kind that
#: libraries reducing y modulo p accept.
SMALL_ORDER_NON_CANONICAL = {
    "neutral, x sign bit set": _h("01" + "00" * 30 + "80"),
    "neutral as y = p + 1": _h("ee" + "ff" * 30 + "7f"),
    "order 4 as y = p": _h("ed" + "ff" * 30 + "7f"),
    "order 2, x sign bit set": _h("ec" + "ff" * 31),
}


def _honest_key(seed: int = 7) -> NaclSigningKey:
    return NaclSigningKey(bytes([seed]) * 32)


def _mixed_order_key() -> bytes:
    """An honest public key plus a point of order 8: on the curve, canonical, but with a small-order component."""
    honest = _decode(bytes(_honest_key().verify_key))
    torsion = _decode(ORDER_8)
    assert honest is not None and torsion is not None
    return _encode(_add(honest, torsion))


WEAK_KEYS = {
    **SMALL_ORDER_CANONICAL,
    **SMALL_ORDER_NON_CANONICAL,
    "honest key plus order-8 point": _mixed_order_key(),
}


def test_the_list_of_weak_keys_is_what_it_claims() -> None:
    """Self-check of the test data: at least 8 small-order keys, including the neutral point and an order-8 point."""
    assert len(set(SMALL_ORDER_CANONICAL.values())) == 8
    for name, key in SMALL_ORDER_CANONICAL.items():
        point = _decode(key)
        assert point is not None, name
        assert _equal(_mul(8, point), IDENTITY), name
        assert _encode(point) == key, name
    assert _equal(_decode(SMALL_ORDER_CANONICAL["neutral"]), IDENTITY)  # type: ignore[arg-type]
    order_8 = _decode(ORDER_8)
    assert order_8 is not None and not _equal(_mul(4, order_8), IDENTITY)
    for name, key in SMALL_ORDER_NON_CANONICAL.items():
        assert _decode(key) is None, name
        lenient = _decode(key, canonical=False)
        assert lenient is not None and _equal(_mul(8, lenient), IDENTITY), name
    mixed = _decode(WEAK_KEYS["honest key plus order-8 point"])
    assert mixed is not None
    assert not _equal(_mul(L, mixed), IDENTITY) and not _equal(_mul(8, mixed), IDENTITY)
    honest = _decode(bytes(_honest_key().verify_key))
    assert honest is not None and _equal(_mul(L, honest), IDENTITY)


# --- §6.1: the library refuses weak keys ----------------------------------------------------------------------------


def _b64u(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _pairing_code(sign_key: bytes) -> str:
    """§3: a pairing code that satisfies the table, except possibly for `sign_key`."""
    document = {
        "v": 1,
        "server": "https://veille.example.org",
        "key_id": new_key_id(),
        "secret": _b64u(bytes(range(32))),
        "sign_key": _b64u(sign_key),
    }
    return "VEIL1:" + _b64u(json.dumps(document).encode())


def _rotation(new_key: bytes, old: NaclSigningKey | None = None) -> tuple[bytes, bytes]:
    """§6.3: a rotation statement signed by an honest outgoing key, naming `new_key` as the incoming one."""
    old = old or _honest_key()
    statement = json.dumps(
        {
            "protocol": "1.0",
            "old_key": _b64u(bytes(old.verify_key)),
            "new_key": _b64u(new_key),
            "issued_at": "2026-11-26T08:00:00Z",
        },
        separators=(",", ":"),
    ).encode()
    return statement, old.sign(statement).signature


def _forged_signature_for_the_neutral_key() -> bytes:
    """With A the neutral point, R = neutral and S = 0 satisfy [S]B = R + [k]A for every message (RFC 8032 §5.1.7)."""
    return SMALL_ORDER_CANONICAL["neutral"] + bytes(32)


def test_controls_an_honest_key_is_accepted_everywhere() -> None:
    """§6.1: "refuses no key an honest server makes" — the controls of the refusal tests below."""
    key = bytes(_honest_key().verify_key)
    assert is_public_key(key)
    assert decode_pairing_code(_pairing_code(key))
    statement, signature = _rotation(bytes(_honest_key(9).verify_key))
    verify_rotation(statement, signature)
    message = b"manifest"
    assert verify(key, message, _honest_key().sign(message).signature)


@pytest.mark.parametrize("name", sorted(WEAK_KEYS))
def test_the_library_refuses_a_weak_public_key(name: str) -> None:
    """§6.1: a public key MUST be canonical and of the prime-order subgroup, other than the neutral point."""
    assert not is_public_key(WEAK_KEYS[name])


@pytest.mark.parametrize("name", sorted(WEAK_KEYS))
def test_a_pairing_code_with_a_weak_key_is_refused(name: str) -> None:
    """§6.1: a reader refuses another key with `bad_pairing_code` in a pairing code."""
    with pytest.raises(ProtocolError) as error:
        decode_pairing_code(_pairing_code(WEAK_KEYS[name]))
    assert error.value.code == "bad_pairing_code"


@pytest.mark.parametrize("name", sorted(WEAK_KEYS))
def test_a_rotation_to_a_weak_key_is_refused(name: str) -> None:
    """§6.1 and §6.3: `bad_rotation` in a rotation statement, even one signed by the trusted outgoing key."""
    statement, signature = _rotation(WEAK_KEYS[name])
    with pytest.raises(ProtocolError) as error:
        verify_rotation(statement, signature)
    assert error.value.code == "bad_rotation"


def test_a_rotation_from_a_weak_key_is_refused() -> None:
    """§6.1: a statement whose `old_key` is the neutral point and whose signature is the universal forgery."""
    statement = json.dumps(
        {
            "protocol": "1.0",
            "old_key": _b64u(SMALL_ORDER_CANONICAL["neutral"]),
            "new_key": _b64u(bytes(_honest_key().verify_key)),
            "issued_at": "2026-11-26T08:00:00Z",
        },
        separators=(",", ":"),
    ).encode()
    with pytest.raises(ProtocolError) as error:
        verify_rotation(statement, _forged_signature_for_the_neutral_key())
    assert error.value.code == "bad_rotation"


@pytest.mark.parametrize("name", sorted(WEAK_KEYS))
def test_no_signature_verifies_under_a_weak_key(name: str) -> None:
    """§6.1: "a signature under it never verifies", including the forgery RFC 8032 lets through for the neutral key."""
    message = b'{"protocol":"1.0"}'
    assert not verify(WEAK_KEYS[name], message, _forged_signature_for_the_neutral_key())
    assert not verify(WEAK_KEYS[name], message, SMALL_ORDER_CANONICAL[sorted(SMALL_ORDER_CANONICAL)[0]] + bytes(32))


# --- §6.1: the independent checker refuses them too ----------------------------------------------------------------


def _checker() -> ModuleType:
    spec = importlib.util.spec_from_file_location("j8_l1_check_vectors", ROOT / "tools" / "check_vectors.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_controls_the_checker_accepts_an_honest_key() -> None:
    checker = _checker()
    key = bytes(_honest_key().verify_key)
    assert checker.key_ok(key)
    assert checker.decode_pairing(_pairing_code(key))
    checker.read_rotation(*_rotation(bytes(_honest_key(9).verify_key)))


@pytest.mark.parametrize("name", sorted(WEAK_KEYS))
def test_the_checker_refuses_a_weak_public_key(name: str) -> None:
    """§6.1, in `tools/check_vectors.py`: the second implementation agrees with the library."""
    checker = _checker()
    key = WEAK_KEYS[name]
    assert not checker.key_ok(key)
    assert not checker.ed25519_ok(key, b"message", _forged_signature_for_the_neutral_key())
    with pytest.raises(checker.Refused) as pairing_error:
        checker.decode_pairing(_pairing_code(key))
    assert pairing_error.value.code == "bad_pairing_code"
    with pytest.raises(checker.Refused) as rotation_error:
        checker.read_rotation(*_rotation(key))
    assert rotation_error.value.code == "bad_rotation"


# --- EF-05 and protocol §7.4: an item too deep to hash is dropped as `bad_item`, the round goes on ------------------


def _nested(depth: int, inner: Any = "leaf", *, as_list: bool = False) -> Any:
    value = inner
    for _ in range(depth):
        value = [value] if as_list else {"a": value}
    return value


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


def _source(world: World, key_id: str, uid: str) -> Any:
    subscription = world.app.store.get_subscription(key_id, uid)
    assert subscription is not None
    return world.app.store.get_source(subscription.spec.collection_id)


@pytest.mark.parametrize("as_list", [False, True], ids=["objects", "arrays"])
def test_an_item_nested_10000_levels_deep_is_a_bad_item_and_the_round_goes_on(world: World, as_list: bool) -> None:
    """EF-05: "une source en panne n'arrête pas le tour"; criterion 3 of J8-L1: 10 000 levels give `bad_item`."""
    deep_key, deep_uid = _subscribe(world, "deep", "d" * 32), "d" * 32
    fine_key, fine_uid = _subscribe(world, "fine", "f" * 32), "f" * 32
    world.collector.items["deep"] = [
        CollectedItem({"title": "ok"}, key="ok"),
        CollectedItem({"body": _nested(10_000, as_list=as_list)}, key="deep"),
    ]
    world.collector.set("fine", ("a", {"title": "A"}), ("b", {"title": "B"}))

    summary = round.run_round(world.app.core)

    deep = _source(world, deep_key, deep_uid)
    assert deep is not None and deep.error == errors.BAD_ITEM
    fine = _source(world, fine_key, fine_uid)
    assert fine is not None and fine.ok and fine.error is None
    assert world.app.store.package_bounds(fine_key, fine_uid).last == 1
    assert summary.failed_collections <= 1


def test_a_deep_item_does_not_make_earlier_items_gone(world: World) -> None:
    """EF-05 and §7.4: a partial collection never turns the items it could not read into `gone`."""
    key_id, uid = _subscribe(world, "news", "a" * 32), "a" * 32
    world.collector.set("news", ("a", {"title": "A"}), ("b", {"title": "B"}))
    round.run_round(world.app.core)
    world.clock.advance(hours=1)
    world.collector.items["news"] = [
        CollectedItem({"title": "A"}, key="a", url="https://example.org/a"),
        CollectedItem(_nested(10_000), key="b", url="https://example.org/b"),
    ]
    round.run_round(world.app.core)
    source = _source(world, key_id, uid)
    assert source is not None and source.error == errors.BAD_ITEM
    assert world.app.store.package_bounds(key_id, uid).last == 1


def test_an_item_of_ordinary_depth_is_still_accepted(world: World) -> None:
    """Control: depth alone is refused only when the item cannot be hashed; 50 levels is an ordinary document."""
    key_id, uid = _subscribe(world, "news", "a" * 32), "a" * 32
    world.collector.items["news"] = [CollectedItem({"body": _nested(50)}, key="k")]
    round.run_round(world.app.core)
    source = _source(world, key_id, uid)
    assert source is not None and source.ok and source.error is None
    assert world.app.store.package_bounds(key_id, uid).last == 1


# Added after reading `0e30a66`: that fix catches `RecursionError` where the item is hashed, but the storage walks the
# fields again from deeper in the call stack. Probing showed a band (about 989 to 994 levels) where the hash passed and
# the round stopped in `canonical_json`. Decision D19 sets an explicit limit of 100 levels.


@pytest.mark.parametrize("depth", [*range(960, 1000, 3), 1_000, 2_000])
def test_no_depth_near_the_recursion_limit_stops_the_round(world: World, depth: int) -> None:
    """EF-05 and D19: around Python's recursion limit, the item is a `bad_item` and the other collection goes on."""
    deep_key, deep_uid = _subscribe(world, "deep", "d" * 32), "d" * 32
    fine_key, fine_uid = _subscribe(world, "fine", "f" * 32), "f" * 32
    world.collector.items["deep"] = [CollectedItem({"body": _nested(depth)}, key="deep")]
    world.collector.set("fine", ("a", {"title": "A"}))
    round.run_round(world.app.core)
    deep = _source(world, deep_key, deep_uid)
    assert deep is not None and deep.error == errors.BAD_ITEM
    assert world.app.store.package_bounds(fine_key, fine_uid).last == 1


@pytest.mark.parametrize(("levels", "accepted"), [(100, True), (101, False)])
def test_the_limit_is_100_levels_with_fields_counting_as_one(world: World, levels: int, accepted: bool) -> None:
    """SPEC EF-05 (D19): more than 100 levels, the `fields` object counting as one, is a `bad_item`."""
    key_id, uid = _subscribe(world, "news", "a" * 32), "a" * 32
    fields = _nested(levels, inner="leaf")  # `levels` nested objects, `fields` being the outermost
    assert isinstance(fields, dict)
    world.collector.items["news"] = [CollectedItem(fields, key="k")]
    round.run_round(world.app.core)
    source = _source(world, key_id, uid)
    assert source is not None
    assert (source.error is None) is accepted
    if not accepted:
        assert source.error == errors.BAD_ITEM


# --- ES-05, ADR-0019, protocol §6.3: one accepted limit, described the same way everywhere -------------------------

PROTOCOL_EN = ROOT / "docs" / "en" / "protocol.md"
PROTOCOL_FR = ROOT / "docs" / "fr" / "protocol.md"
ADR_0019 = ROOT / "docs" / "adr" / "0019-recepteur-et-rotations.md"
SPEC = ROOT / "docs" / "SPEC.md"
G4_PASS3 = ROOT / "tests" / "verif" / "test_g4_verif_pass3.py"


def _flat(path: Path) -> str:
    return re.sub(r"\s+", " ", path.read_text(encoding="utf-8"))


def _section(text: str, start: str, end: str) -> str:
    assert start in text, start
    rest = text[text.index(start) :]
    return rest[: rest.index(end)] if end in rest else rest


#: For each document: (the paragraph that states the limit, the three facts it must state). The three facts are the
#: same everywhere: a package that is purged (missing), two rotations or more missed, and pairing again.
LIMIT: dict[str, tuple[Callable[[], str], tuple[str, ...]]] = {
    "protocol (en) §6.3": (
        lambda: _section(_flat(PROTOCOL_EN), "### 6.3 Key rotation", "## 7."),
        (r"lacks a purged package", r"missed two rotations or more", r"must be paired again"),
    ),
    "protocol (fr) §6.3": (
        lambda: _section(_flat(PROTOCOL_FR), "### 6.3", "## 7."),
        (r"manque un paquet purgé", r"manqué au moins deux rotations", r"jumelé de nouveau"),
    ),
    "ADR-0019": (
        lambda: _section(_flat(ADR_0019), "## Décision", "## Conséquences"),
        (r"manque un paquet déjà purgé", r"manqué deux rotations ou plus", r"rejumelé"),
    ),
    "SPEC ES-05": (
        lambda: _section(_flat(SPEC), "**ES-05", "**ES-06"),
        (r"manque un paquet purgé", r"manqué deux rotations ou plus", r"rejumelé"),
    ),
}


@pytest.mark.parametrize("document", sorted(LIMIT))
def test_the_accepted_limit_is_stated_with_its_three_facts(document: str) -> None:
    """ES-05, ADR-0019, protocol §6.3 (en, fr): purged package, two rotations or more, pairing again."""
    text, facts = LIMIT[document]
    paragraph = text()
    for fact in facts:
        assert re.search(fact, paragraph), f"{document}: {fact!r} missing"


def test_the_limit_is_not_stated_as_a_single_rotation_anywhere() -> None:
    """The limit is two rotations, not one: no document says that one missed rotation over a purged gap forces
    pairing again (that case is followed through the statement carried by the covering `state`)."""
    for path in (PROTOCOL_EN, PROTOCOL_FR, ADR_0019, SPEC):
        text = _flat(path)
        assert not re.search(r"missed (one|a single) rotation", text), path
        assert not re.search(r"manqué une (seule )?rotation", text), path


def _xfail_reasons(path: Path) -> dict[str, str]:
    """Reason of each strict xfail marker, keyed by the test it decorates."""
    text = path.read_text(encoding="utf-8")
    found = re.findall(r'@pytest\.mark\.xfail\(strict=True, reason="([^"]*)"\)\n(?:@[^\n]*\n)*def (test_\w+)', text)
    return {name: reason for reason, name in found}


LIMIT_TESTS = (
    "test_a_member_back_after_a_purge_follows_two_rotations_from_a_folder",
    "test_a_member_back_after_a_purge_follows_two_rotations_over_http",
)


@pytest.mark.parametrize("test", LIMIT_TESTS)
def test_the_xfail_of_the_limit_states_the_same_limit(test: str) -> None:
    """The reasons of the `xfail` cases of the limit name it as accepted, with the same two facts."""
    reason = _xfail_reasons(G4_PASS3)[test]
    assert reason.startswith("accepted limit")
    assert "purge" in reason and "two rotations" in reason
    assert "§6.3" in reason


@pytest.mark.parametrize("test", LIMIT_TESTS)
def test_the_xfail_of_the_limit_cites_a_document_that_states_it(test: str) -> None:
    """The reason cites the authoritative documents (ES-05 or ADR-0019), not a section of a retired document."""
    reason = _xfail_reasons(G4_PASS3)[test]
    assert "ES-05" in reason or "ADR-0019" in reason, reason
