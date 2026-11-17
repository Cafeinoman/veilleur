# SPDX-License-Identifier: EUPL-1.2
"""Independent check of the protocol test vectors.

Written from the specification (`docs/en/protocol.md`) without importing `veilleur_protocol`: cryptography comes from
libsodium (PyNaCl) and the standard library, not from pycryptodomex. It reads every file of `protocol/vectors/` and
checks that its own computations give the same results, and that it refuses what must be refused with the same error
code.

    uv run python tools/check_vectors.py [vectors directory]
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import io
import ipaddress
import json
import re
import struct
import sys
import zipfile
import zlib
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from nacl import bindings
from nacl.exceptions import BadSignatureError, CryptoError

DEFAULT_VECTORS = Path(__file__).resolve().parent.parent / "protocol" / "vectors"
JSON = dict[str, Any]
KINDS = {1: "delta", 2: "state", 3: "history", 16: "subscription"}
NAME = re.compile(r"(manifest\.json|manifest\.sig|items\.jsonl|rotation\.json|rotation\.sig|report\.[a-z0-9]{1,16})")
TIME = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z")


class Refused(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def hkdf(secret: bytes, salt: bytes, info: bytes) -> bytes:
    """RFC 5869 with SHA-256, 32 bytes of output (a single block)."""
    prk = hmac.new(salt or bytes(32), secret, hashlib.sha256).digest()
    return hmac.new(prk, info + b"\x01", hashlib.sha256).digest()


def strict(data: bytes) -> Any:
    """RFC 8259 JSON: unique member names, no NaN or Infinity; anything else raises ValueError."""

    def unique(pairs: list[tuple[str, Any]]) -> JSON:
        if len({name for name, _ in pairs}) != len(pairs):
            raise ValueError("duplicate member name")
        return dict(pairs)

    def constant(name: str) -> Any:
        raise ValueError(name)

    def finite(text: str) -> float:
        if float(text) in (float("inf"), float("-inf")):
            raise ValueError(text)
        return float(text)

    try:
        return json.loads(data.decode("utf-8"), object_pairs_hook=unique, parse_constant=constant, parse_float=finite)
    except RecursionError as exc:
        raise ValueError("nesting") from exc


def b64u(text: str) -> bytes:
    if not re.fullmatch(r"[A-Za-z0-9_-]*", text) or len(text) % 4 == 1:
        raise ValueError("base64url")
    data = base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))
    if base64.urlsafe_b64encode(data).rstrip(b"=").decode() != text:
        raise ValueError("non-canonical")
    return data


def ed25519_ok(key: bytes, message: bytes, signature: bytes) -> bool:
    if len(key) != 32 or len(signature) != 64:
        return False
    try:
        bindings.crypto_sign_open(signature + message, key)
    except (BadSignatureError, ValueError, CryptoError):
        return False
    return True


def timestamp(value: object) -> bool:
    if not isinstance(value, str) or not TIME.fullmatch(value):
        return False
    try:
        datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError:
        return False
    return True


def open_envelope(
    secret: bytes, data: bytes, uid: str, kinds: list[str], seq: int | None, max_size: int
) -> tuple[int, str, bytes]:
    if len(data) > max_size:
        raise Refused("too_large")
    if len(data) < 30 + 24 + 16:
        raise Refused("bad_envelope")
    magic, version, raw_uid, number, code = struct.unpack(">4sB16sQB", data[:30])
    if magic != b"VEIL":
        raise Refused("bad_envelope")
    if version != 1:
        raise Refused("unsupported_version")
    if number >= 2**63 or code not in KINDS:
        raise Refused("bad_envelope")
    if raw_uid.hex() != uid:
        raise Refused("uid_mismatch")
    kind = KINDS[code]
    if kind not in kinds:
        raise Refused("kind_mismatch")
    if seq is not None and number != seq:
        raise Refused("seq_mismatch")
    info = b"veilleur-subscription" if kind == "subscription" else b"veilleur-report"
    key = hkdf(secret, raw_uid, info)
    try:
        plain = bindings.crypto_aead_xchacha20poly1305_ietf_decrypt(data[54:], data[:30], data[30:54], key)
    except CryptoError as exc:
        raise Refused("decryption_failed") from exc
    return number, kind, plain


def read_rotation(statement: bytes, signature: bytes) -> tuple[bytes, bytes]:
    try:
        document = strict(statement)
        assert isinstance(document, dict) and isinstance(document["protocol"], str)
        assert re.fullmatch(r"1\.(0|[1-9][0-9]{0,5})", document["protocol"])
        old, new = b64u(document["old_key"]), b64u(document["new_key"])
        assert timestamp(document["issued_at"]) and len(old) == 32 and len(new) == 32
    except (ValueError, KeyError, AssertionError) as exc:
        raise Refused("bad_rotation") from exc
    if not ed25519_ok(old, statement, signature):
        raise Refused("bad_rotation")
    return old, new


def open_package(case: JSON) -> JSON:
    limits = case.get("limits") or {
        "max_package": 64 << 20,
        "max_files": 32,
        "max_file": 64 << 20,
        "max_total": 128 << 20,
    }
    kinds = case.get("kinds") or ["delta", "state", "history"]
    trusted = [bytes.fromhex(k) for k in case["trusted_keys"]]
    number, kind, plain = open_envelope(
        bytes.fromhex(case["secret"]),
        bytes.fromhex(case["envelope"]),
        case["uid"],
        kinds,
        case["seq"],
        limits["max_package"],
    )
    try:
        infos = zipfile.ZipFile(io.BytesIO(plain)).infolist()
    except Exception as exc:
        raise Refused("bad_archive") from exc
    if len(infos) > limits["max_files"]:
        raise Refused("too_many_files")
    entries: dict[str, zipfile.ZipInfo] = {}
    total = 0
    for info in infos:
        if not NAME.fullmatch(info.filename):
            raise Refused("unexpected_file")
        if info.filename in entries:
            raise Refused("bad_archive")
        if info.flag_bits & 1 or info.compress_type not in (0, 8):
            raise Refused("bad_archive")
        cap = {
            "manifest.sig": 64,
            "rotation.sig": 64,
            "rotation.json": 4096,
            "manifest.json": min(1 << 20, limits["max_file"]),
        }
        if info.file_size > cap.get(info.filename, limits["max_file"]):
            raise Refused("file_too_large")
        total += info.file_size
        entries[info.filename] = info
    if total > limits["max_total"]:
        raise Refused("too_large")
    if any(n not in entries for n in ("manifest.json", "manifest.sig", "items.jsonl")):
        raise Refused("missing_file")
    if ("rotation.json" in entries) != ("rotation.sig" in entries):
        raise Refused("missing_file")

    def read(name: str) -> bytes:
        """Raw data from the local header, inflated in full: exactly the declared size and CRC."""
        info = entries[name]
        at = info.header_offset
        if plain[at : at + 4] != b"PK\x03\x04" or at + 30 > len(plain):
            raise Refused("bad_archive")
        flags, method = struct.unpack("<HH", plain[at + 6 : at + 10])
        crc, compressed, size, name_length, extra_length = struct.unpack("<IIIHH", plain[at + 14 : at + 30])
        if (flags, method, crc, compressed, size) != (
            info.flag_bits,
            info.compress_type,
            info.CRC,
            info.compress_size,
            info.file_size,
        ):
            raise Refused("bad_archive")
        if plain[at + 30 : at + 30 + name_length] != name.encode():
            raise Refused("bad_archive")
        start = at + 30 + name_length + extra_length
        raw = plain[start : start + info.compress_size]
        if len(raw) != info.compress_size:
            raise Refused("bad_archive")
        if info.compress_type == 0:
            data = raw
        else:
            inflater = zlib.decompressobj(-15)
            try:
                data = inflater.decompress(raw, info.file_size + 1)
            except zlib.error as exc:
                raise Refused("bad_archive") from exc
            if not inflater.eof or inflater.unused_data or inflater.unconsumed_tail:
                raise Refused("bad_archive")
        if len(data) != info.file_size or zlib.crc32(data) != info.CRC:
            raise Refused("bad_archive")
        return data

    manifest_bytes, signature = read("manifest.json"), read("manifest.sig")
    rotation = read_rotation(read("rotation.json"), read("rotation.sig")) if "rotation.json" in entries else None
    signer = next((k for k in trusted if ed25519_ok(k, manifest_bytes, signature)), None)
    adopted = None
    if signer is None:
        if rotation is None or rotation[0] not in trusted or not ed25519_ok(rotation[1], manifest_bytes, signature):
            raise Refused("bad_signature")
        signer = adopted = rotation[1]
    try:
        manifest = strict(manifest_bytes)
    except ValueError as exc:
        raise Refused("bad_manifest") from exc
    if not isinstance(manifest, dict):
        raise Refused("bad_manifest")
    if not isinstance(manifest.get("protocol"), str) or not re.fullmatch(
        r"1\.(0|[1-9][0-9]{0,5})", manifest["protocol"]
    ):
        raise Refused("unsupported_version")
    if (
        manifest.get("uid") != case["uid"]
        or type(manifest.get("seq")) is not int
        or manifest["seq"] != number
        or manifest.get("kind") != kind
    ):
        raise Refused("bad_manifest")
    period = manifest.get("period")
    if not (timestamp(manifest.get("created_at")) and isinstance(period, dict) and timestamp(period.get("to"))):
        raise Refused("bad_manifest")
    if "from" not in period or (period["from"] is not None and not timestamp(period["from"])):
        raise Refused("bad_manifest")
    sources, files = manifest.get("sources"), manifest.get("files")
    if not isinstance(sources, list) or not all(isinstance(s, dict) for s in sources):
        raise Refused("bad_manifest")
    if not isinstance(files, dict) or not all(
        isinstance(h, str) and re.fullmatch(r"[0-9a-f]{64}", h) for h in files.values()
    ):
        raise Refused("bad_manifest")
    present = set(entries) - {"manifest.json", "manifest.sig"}
    if set(files) - present:
        raise Refused("missing_file")
    if present - set(files):
        raise Refused("unexpected_file")
    contents = {}
    for name, digest in files.items():
        contents[name] = read(name)
        if hashlib.sha256(contents[name]).hexdigest() != digest:
            raise Refused("hash_mismatch")
    items = check_items(contents["items.jsonl"])
    return {
        "kind": kind,
        "seq": number,
        "files": {n: read(n).hex() for n in entries},
        "manifest": manifest,
        "items": items,
        "signer": signer.hex(),
        "adopted_key": None if adopted is None else adopted.hex(),
        "archive": plain.hex(),
    }


def check_items(data: bytes) -> list[JSON]:
    if data and not data.endswith(b"\n"):
        raise Refused("bad_items")
    items: list[JSON] = []
    for line in data.split(b"\n")[:-1] if data else []:
        try:
            item = strict(line)
        except ValueError as exc:
            raise Refused("bad_items") from exc
        ok = (
            isinstance(item, dict)
            and isinstance(item.get("key"), str)
            and item["key"] != ""
            and item.get("change") in ("new", "changed", "gone")
            and isinstance(item.get("hash"), str)
            and re.fullmatch(r"[0-9a-f]{64}", item["hash"]) is not None
            and isinstance(item.get("fields"), dict)
            and timestamp(item.get("fetched_at"))
            and "url" in item
            and (item["url"] is None or isinstance(item["url"], str))
        )
        if not ok or (items and not items[-1]["key"] < item["key"]):
            raise Refused("bad_items")
        items.append(item)
    return items


def auth_key(secret: bytes, path: str) -> bytes:
    match = re.match(r"/v1/subscriptions/([^/?#]*)(?:[/?#]|$)", path)
    if match is not None and not re.fullmatch(r"[0-9a-f]{32}", match.group(1)):
        raise Refused("bad_authorization")
    salt = b"" if match is None else bytes.fromhex(match.group(1))
    return hkdf(secret, salt, b"veilleur-auth")


def origin_ok(server: str) -> bool:
    """https://host[:port], host = DNS name, dotted IPv4 or bracketed IPv6, port 1-65535; one trailing / allowed."""
    match = re.fullmatch(r"https://(\[[^\]]*\]|[^/:\[\]]+)(?::([0-9]+))?/?", server)
    if match is None:
        return False
    host, port = match.group(1), match.group(2)
    if port is not None and (port.startswith("0") or not 1 <= int(port) <= 65535):
        return False
    try:
        if host.startswith("["):
            ipaddress.ip_address(host[1:-1])
            return ":" in host
        if re.fullmatch(r"[0-9.]+", host):
            return isinstance(ipaddress.ip_address(host), ipaddress.IPv4Address)
    except ValueError:
        return False
    label = r"(?!-)[A-Za-z0-9-]{1,63}(?<!-)"
    return (
        len(host) <= 253
        and re.fullmatch(rf"{label}(\.{label})*", host) is not None
        and not host.split(".")[-1].isdigit()
    )


def verify_request(case: JSON) -> None:
    match = re.fullmatch(r"Veilleur ([0-9a-f]{16}):([A-Za-z0-9_-]{43})", case["authorization"])
    if match is None:
        raise Refused("bad_authorization")
    if not timestamp(case["date"]):
        raise Refused("bad_date")
    sent = datetime.strptime(case["date"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
    now = datetime.strptime(case["now"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
    if abs((now - sent).total_seconds()) > 300:
        raise Refused("stale_date")
    body = bytes.fromhex(case["body"])
    message = "\n".join((case["method"], case["path_and_query"], case["date"], hashlib.sha256(body).hexdigest()))
    mac = hmac.new(
        auth_key(bytes.fromhex(case["secret"]), case["path_and_query"]), message.encode(), hashlib.sha256
    ).digest()
    try:
        sent_mac = b64u(match.group(2))
    except ValueError as exc:
        raise Refused("bad_authorization") from exc
    if not hmac.compare_digest(mac, sent_mac):
        raise Refused("bad_authorization")


def decode_pairing(code: str) -> JSON:
    try:
        assert code.startswith("VEIL1:")
        document = strict(b64u(code[6:]))
        assert isinstance(document, dict) and type(document.get("v")) is int and document["v"] == 1
        server = document["server"]
        assert server == "folder:" or origin_ok(server)
        assert re.fullmatch(r"[0-9a-f]{16}", document["key_id"])
        secret, sign_key = b64u(document["secret"]), b64u(document["sign_key"])
        assert len(secret) == 32 and len(sign_key) == 32
        ntfy = document.get("ntfy")
        if "ntfy" in document:
            assert isinstance(ntfy, dict) and str(ntfy["url"]).startswith("https://") and ntfy["topic"]
            ntfy = {"url": ntfy["url"], "topic": ntfy["topic"], "token": ntfy.get("token")}
    except (AssertionError, ValueError, KeyError, TypeError) as exc:
        raise Refused("bad_pairing_code") from exc
    return {
        "server": server,
        "key_id": document["key_id"],
        "secret": secret.hex(),
        "sign_key": sign_key.hex(),
        "ntfy": ntfy,
    }


def check(vectors: Path) -> list[str]:
    failures: list[str] = []

    def expect(condition: bool, what: str) -> None:
        if not condition:
            failures.append(what)

    def load(name: str) -> JSON:
        document: JSON = json.loads((vectors / name).read_text(encoding="utf-8"))
        return document

    for case in load("keys.json")["cases"]:
        salt = b"" if case["uid"] is None else bytes.fromhex(case["uid"])
        expect(
            hkdf(bytes.fromhex(case["secret"]), salt, case["info"].encode()).hex() == case["key"],
            f"keys: {case['info']} {case['uid']}",
        )
    for case in load("pairing.json")["cases"]:
        decoded = decode_pairing(case["code"])
        expect(decoded == {k: case[k] for k in decoded}, f"pairing: {case['server']}")
    for case in load("requests.json")["cases"]:
        message = "\n".join(
            (
                case["method"],
                case["path_and_query"],
                case["date"],
                hashlib.sha256(bytes.fromhex(case["body"])).hexdigest(),
            )
        )
        expect(message == case["string_to_sign"], f"requests: string to sign {case['path_and_query']}")
        mac = hmac.new(
            auth_key(bytes.fromhex(case["secret"]), case["path_and_query"]), message.encode(), hashlib.sha256
        ).digest()
        header = f"Veilleur {case['key_id']}:{base64.urlsafe_b64encode(mac).rstrip(b'=').decode()}"
        expect(header == case["authorization"], f"requests: {case['method']} {case['path_and_query']}")
    for case in load("subscriptions.json")["cases"]:
        number, _, plain = open_envelope(
            bytes.fromhex(case["secret"]), bytes.fromhex(case["envelope"]), case["uid"], ["subscription"], None, 1 << 20
        )
        expect(
            number == case["base_version"] and strict(plain) == case["document"],
            f"subscriptions: version {case['base_version']}",
        )
    for case in load("packages.json")["cases"]:
        try:
            got = open_package(case)
        except Refused as exc:
            failures.append(f"packages: {case['name']}: refused ({exc.code})")
            continue
        expect(got.pop("archive") == case["archive"], f"packages: {case['name']}: archive")
        for key, value in case["expected"].items():
            expect(got[key] == value, f"packages: {case['name']}: {key}")
    refusals = load("refusals.json")
    for case in refusals["packages"]:
        try:
            open_package(case)
            failures.append(f"refusals: {case['name']}: accepted")
        except Refused as exc:
            expect(exc.code == case["error"], f"refusals: {case['name']}: {exc.code} instead of {case['error']}")
    for case in refusals["requests"]:
        try:
            verify_request(case)
            failures.append(f"refusals: {case['name']}: accepted")
        except Refused as exc:
            expect(exc.code == case["error"], f"refusals: {case['name']}: {exc.code} instead of {case['error']}")
    for case in refusals["pairing_codes"]:
        try:
            decode_pairing(case["code"])
            failures.append(f"refusals: {case['name']}: accepted")
        except Refused as exc:
            expect(exc.code == case["error"], f"refusals: {case['name']}")
    return failures


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    failures = check(Path(args[0]) if args else DEFAULT_VECTORS)
    for failure in failures:
        print(failure, file=sys.stderr)
    print("vectors: OK" if not failures else f"vectors: {len(failures)} failure(s)")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
