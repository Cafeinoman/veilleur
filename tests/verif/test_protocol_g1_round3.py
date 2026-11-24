# SPDX-License-Identifier: EUPL-1.2
"""Independent check of milestone G1, third round.

Written from docs/en/protocol.md (normative), docs/en/threat-model.md and the spec (ES-03, ES-07, ES-11, ES-13).
Targets: what the writers produce (a server must not make packages its own reader refuses), the agreement of the two
implementations (§12), and the consistency of the documents. No network, no disk.
"""

from __future__ import annotations

import hashlib
import importlib.util
import io
import json
import random
import re
import struct
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from veilleur_protocol import (
    Change,
    Item,
    Kind,
    ProtocolError,
    SigningKey,
    b64u_encode,
    decode_pairing_code,
    encode_items,
    open_package,
    parse_items,
)
from veilleur_protocol.envelope import Header, seal
from veilleur_protocol.package import PackageContent, build_archive, manifest_bytes, seal_package
from veilleur_protocol.subscription import open_subscription, seal_subscription

ROOT = Path(__file__).resolve().parents[2]
SECRET = hashlib.sha256(b"verif3 secret").digest()
UID = "33445566778899aabbccddeeff001122"
KEY_ID = "8899aabbccddeeff"
NOW = datetime(2026, 11, 17, 6, 0, 0, tzinfo=UTC)
KEY = SigningKey(hashlib.sha256(b"verif3 server key").digest())
HASH = "c" * 64
MiB = 1024 * 1024


def _checker() -> ModuleType:
    spec = importlib.util.spec_from_file_location("verif3_check_vectors", ROOT / "tools" / "check_vectors.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


CHECKER = _checker()


def _items(fields: dict[str, Any] | None = None) -> bytes:
    return encode_items([Item("a", Change.NEW, HASH, fields if fields is not None else {"x": 1}, NOW, None)])


def _content(**changes: Any) -> PackageContent:
    values: dict[str, Any] = {
        "uid": UID,
        "seq": 1,
        "kind": Kind.DELTA,
        "created_at": NOW,
        "period_to": NOW,
        "period_from": None,
        "items": _items(),
    }
    values.update(changes)
    return PackageContent(**values)


def _open(data: bytes) -> Any:
    return open_package(data, secret=SECRET, uid=UID, trusted_keys=[KEY.public_key])


def _code(data: bytes) -> str:
    try:
        _open(data)
    except ProtocolError as error:
        return error.code
    except Exception as exc:
        pytest.fail(f"the reader raised {type(exc).__name__}: {exc} (expected a ProtocolError)")
    return "accepted"


def _zip(entries: list[tuple[str, bytes]]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, data in entries:
            info = zipfile.ZipInfo(name, (1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_STORED
            archive.writestr(info, data)
    return buffer.getvalue()


def _signed_manifest_package(manifest: bytes, items: bytes) -> bytes:
    plain = _zip([("manifest.json", manifest), ("manifest.sig", KEY.sign(manifest)), ("items.jsonl", items)])
    return seal(SECRET, Header(UID, 1, Kind.DELTA), plain)


# --- Writers must only produce what the reader accepts (§2: JSON is RFC 8259; §7.1, §10.1) -------------------------


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")], ids=["nan", "inf", "-inf"])
def test_items_writer_never_emits_non_json_numbers(value: float) -> None:
    """§2: a reader MUST refuse NaN and Infinity. Item fields come from collectors, i.e. from hostile sources (threat
    model §2); Python's json module accepts `NaN` in a JSON API response. The writer must refuse such a value, not
    produce an items.jsonl every receiving tool refuses (bad_items)."""
    try:
        data = _items({"price": value})
    except ValueError:
        return
    with pytest.raises(ProtocolError):
        parse_items(data)
    pytest.fail(f"encode_items wrote {data!r}, which parse_items refuses")


def test_package_writer_never_emits_a_package_its_reader_refuses_because_of_nan() -> None:
    """Same, end to end: seal_package must refuse rather than seal a package that open_package refuses."""
    try:
        sealed = seal_package(SECRET, KEY, _content(items=_items({"score": float("nan")})))
    except ValueError:
        return
    pytest.fail(f"seal_package sealed a package the reader refuses with {_code(sealed)}")


def test_manifest_writer_never_emits_non_json_numbers_in_sources() -> None:
    """§7.5 / §2: `sources` is written by the server; a NaN there makes the manifest unreadable (bad_manifest)."""
    try:
        sealed = seal_package(SECRET, KEY, _content(sources=[{"id": "s", "ok": True, "latency": float("nan")}]))
    except ValueError:
        return
    pytest.fail(f"seal_package sealed a package the reader refuses with {_code(sealed)}")


def test_subscription_writer_never_emits_non_json_numbers() -> None:
    """§7.6 / §2: the receiving tool must not send a document the server refuses (bad_subscription)."""
    try:
        body = seal_subscription(SECRET, UID, 0, {"threshold": float("nan")})
    except ValueError:
        return
    with pytest.raises(ProtocolError) as error:
        open_subscription(SECRET, UID, body)
    pytest.fail(f"seal_subscription sealed a document open_subscription refuses with {error.value.code}")


def test_package_writer_stays_within_the_file_count_limit() -> None:
    """§10.1: a reader refuses more than 32 files. A server must not seal a package no reader can open."""
    renderings = {f"report.r{index}": b"x" for index in range(40)}
    try:
        sealed = seal_package(SECRET, KEY, _content(renderings=renderings))
    except ValueError:
        return
    code = _code(sealed)
    assert code == "accepted", f"seal_package sealed a package of 43 files that the reader refuses with {code}"


def test_subscription_writer_stays_within_the_envelope_limit() -> None:
    """§10.1: a subscription envelope is at most 1 MiB; a larger body can only be refused by the server."""
    try:
        body = seal_subscription(SECRET, UID, 0, {"x": "a" * (2 * MiB)})
    except ValueError:
        return
    with pytest.raises(ProtocolError) as error:
        open_subscription(SECRET, UID, body)
    pytest.fail(f"seal_subscription sealed {len(body)} bytes; open_subscription refuses with {error.value.code}")


# --- Consistency of the limits (§7.6, §9, §10.1, ES-11) -------------------------------------------------------------


def test_the_subscription_limits_agree() -> None:
    """§7.6, §9, §10.1 and ES-11 must agree. The verifier's first version of this test found that the plaintext
    (1 MiB), the envelope (1 MiB) and the request body (1 MB) disagreed; the specification now follows ES-11: the
    envelope is the request body, at most 1 000 000 bytes, so the plaintext is at most 999 930 bytes. The largest
    document opens; one byte more cannot be sealed."""
    largest = 1_000_000 - 70
    document = {"x": "a" * (largest - len(b'{"x":""}'))}
    assert len(json.dumps(document, separators=(",", ":")).encode()) == largest
    body = seal_subscription(SECRET, UID, 0, document)
    assert len(body) == 1_000_000
    try:
        open_subscription(SECRET, UID, body)
    except ProtocolError as error:
        pytest.fail(f"a {largest}-byte subscription document (§7.6) is refused with {error.code}")
    with pytest.raises(ValueError):
        seal_subscription(SECRET, UID, 0, {"x": document["x"] + "a"})


# --- Documents must not contradict each other (CLAUDE.md, spec §6) ------------------------------------------------


def test_protocol_and_threat_model_agree_on_replays() -> None:
    """protocol.md §8 says a replay within the 5-minute window "changes nothing"; threat-model.md §4 says a replayed
    DELETE or creation "takes effect". The normative text must not claim more than the threat model grants."""
    protocol = (ROOT / "docs" / "en" / "protocol.md").read_text(encoding="utf-8")
    threat = (ROOT / "docs" / "en" / "threat-model.md").read_text(encoding="utf-8")
    threat_admits_effective_replays = "takes effect" in threat
    protocol_denies_them = re.search(r"replay within the window\s+changes nothing", protocol) is not None
    assert not (threat_admits_effective_replays and protocol_denies_them), (
        "protocol.md §8 states that a replay changes nothing; threat-model.md §4 lists replays that take effect"
    )


# --- §3: the server member is an origin `https://host[:port]` --------------------------------------------------------


def _pairing(server: str) -> str:
    document = {
        "v": 1,
        "server": server,
        "key_id": KEY_ID,
        "secret": b64u_encode(SECRET),
        "sign_key": b64u_encode(KEY.public_key),
    }
    return "VEIL1:" + b64u_encode(json.dumps(document, separators=(",", ":")).encode())


@pytest.mark.parametrize(
    "server",
    [
        "https://veille.example.org\\evil",  # WHATWG URL parsers read "\" as "/": a path
        "https://veille.example.org\\",
        "https://veille.example.org:0",  # port 0 cannot be connected to
        "https://<veille>.example.org",
        "https://veille.example.org%2Fx",
    ],
)
def test_pairing_server_host_is_a_host(server: str) -> None:
    """§3: `https://host[:port]`, no path. A value that another URL parser reads with a path, or whose host is not a
    host name, does not satisfy the table and MUST be refused (bad_pairing_code)."""
    with pytest.raises(ProtocolError) as error:
        decode_pairing_code(_pairing(server))
    assert error.value.code == "bad_pairing_code"


@pytest.mark.parametrize(
    "server",
    [
        "https://veille.example.org",
        "https://veille.example.org:8443/",
        "https://[2001:db8::1]",  # spec ENF-03b: the public address may be an IP address
        "https://[2001:db8::1]:8443",
        "https://veille.example.org:99999",
        "https://veille.example.org:0",
        "https://veille.example.org\\evil",
    ],
)
def test_both_implementations_agree_on_the_server_member(server: str) -> None:
    """§12: the library and the independent implementation are both written from §3; they must agree on what a
    valid `server` is, otherwise the vectors only prove agreement on the cases chosen."""
    try:
        decode_pairing_code(_pairing(server))
        library = "accepted"
    except ProtocolError as error:
        library = error.code
    try:
        CHECKER.decode_pairing(_pairing(server))
        independent = "accepted"
    except CHECKER.Refused as refused:
        independent = refused.code
    assert library == independent, f"{server!r}: library {library}, independent implementation {independent}"


# --- §8: scope of the authentication key, in both implementations ---------------------------------------------------


@pytest.mark.parametrize(
    "path",
    ["/v1/subscriptions/" + "AB" * 16 + "/reports", "/v1/subscriptions/", "/v1/subscriptions/?after=1"],
)
def test_both_implementations_refuse_a_malformed_uid_in_the_path(path: str) -> None:
    """§8: "a malformed uid there is refused". The independent implementation must not derive a key for it."""
    from veilleur_protocol.auth import request_scope

    with pytest.raises(ProtocolError):
        request_scope(path)
    try:
        CHECKER.auth_key(SECRET, path)
    except (ValueError, CHECKER.Refused):
        return
    pytest.fail(f"the independent implementation derives an authentication key for {path!r}")


# --- §2, §10.2 step 8: a byte order mark is refused -----------------------------------------------------------------


def test_a_manifest_with_a_byte_order_mark_is_bad_manifest() -> None:
    manifest = b"\xef\xbb\xbf" + manifest_bytes(_content(), {"items.jsonl": _items()})
    assert _code(_signed_manifest_package(manifest, _items())) == "bad_manifest"


def test_a_manifest_without_period_from_is_bad_manifest() -> None:
    """§7.2: `period` is `{"from": timestamp or null, "to": timestamp}`; `from` is a member, possibly null."""
    document = json.loads(manifest_bytes(_content(), {"items.jsonl": _items()}))
    del document["period"]["from"]
    manifest = json.dumps(document, sort_keys=True, separators=(",", ":")).encode()
    assert _code(_signed_manifest_package(manifest, _items())) == "bad_manifest"


def test_a_package_envelope_of_kind_subscription_is_kind_mismatch() -> None:
    """§10.2 step 3: open_package never accepts a subscription envelope, even when asked to."""
    sealed = seal(SECRET, Header(UID, 1, Kind.SUBSCRIPTION), build_archive(_content(), KEY))
    with pytest.raises(ProtocolError) as error:
        open_package(sealed, secret=SECRET, uid=UID, trusted_keys=[KEY.public_key], kinds=[Kind.SUBSCRIPTION])
    assert error.value.code == "kind_mismatch"


# --- §12 / ES-13: random damage to the plain archive, both implementations -----------------------------------------


def test_damaged_archives_are_refused_or_yield_exactly_the_signed_content() -> None:
    """ES-04 / ES-13: random damage to the plain archive (deflated entries, so that sizes and CRCs matter). The reader
    only ever raises ProtocolError, and when it accepts a damaged archive, what it returns is exactly what the server
    signed: damage may only have touched bytes that carry no meaning (dates, attributes, version fields)."""
    renderings = {"report.md": b"# r\n" * 50}
    base = build_archive(_content(renderings=renderings), KEY)
    expected = _open(seal(SECRET, Header(UID, 1, Kind.DELTA), base))
    generator = random.Random(3_20261117)
    crashes: list[str] = []
    altered: list[str] = []
    for _ in range(3000):
        data = bytearray(base)
        for _ in range(generator.randrange(1, 4)):
            position = generator.randrange(len(data))
            if generator.random() < 0.5:
                data[position] = generator.randrange(256)
            else:
                struct.pack_into("<H", data, min(position, len(data) - 2), generator.randrange(65536))
        sealed = seal(SECRET, Header(UID, 1, Kind.DELTA), bytes(data))
        try:
            opened = _open(sealed)
        except ProtocolError:
            continue
        except Exception as exc:
            crashes.append(f"{type(exc).__name__}: {exc}")
            continue
        if (opened.manifest, opened.items, opened.renderings) != (
            expected.manifest,
            expected.items,
            expected.renderings,
        ):
            altered.append(repr(opened.renderings)[:80])
    assert not crashes, crashes[:5]
    assert not altered, altered[:5]
