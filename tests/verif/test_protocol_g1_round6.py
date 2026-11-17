# SPDX-License-Identifier: EUPL-1.2
"""Independent verification of G1, sixth round.

Written from the specification (docs/en/protocol.md) only. Each test names the requirement it checks. A failing test
is a finding: the code was not changed to make it pass.
"""

from __future__ import annotations

import hashlib
import importlib.util
import io
import json
import zipfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from veilleur_protocol import (
    Change,
    Item,
    Kind,
    PackageContent,
    ProtocolError,
    SigningKey,
    encode_items,
    format_time,
    make_rotation,
    open_package,
    parse_items,
    parse_time,
    seal_package,
    sign_request,
    verify_request,
    verify_rotation,
)
from veilleur_protocol.envelope import Header, seal

ROOT = Path(__file__).resolve().parents[2]
SECRET = hashlib.sha256(b"verif6 secret").digest()
UID = "66778899aabbccddeeff001122334455"
KEY_ID = "1122334455667788"
NOW = datetime(2026, 11, 17, 6, 0, 0, tzinfo=UTC)
KEY = SigningKey(hashlib.sha256(b"verif6 server key").digest())
OTHER = SigningKey(hashlib.sha256(b"verif6 other key").digest())
HASH = "f" * 64
OLD = datetime(999, 1, 1, tzinfo=UTC)
"""A date the reader accepts when written as §2 says (`0999-01-01T00:00:00Z`)."""


def _checker() -> ModuleType:
    spec = importlib.util.spec_from_file_location("verif6_check_vectors", ROOT / "tools" / "check_vectors.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


CHECKER = _checker()


def _content(**changes: Any) -> PackageContent:
    base: dict[str, Any] = {
        "uid": UID,
        "seq": 1,
        "kind": Kind.DELTA,
        "created_at": NOW,
        "period_to": NOW,
        "period_from": None,
        "items": encode_items([Item("a", Change.NEW, HASH, {"x": 1}, NOW, None)]),
    }
    base.update(changes)
    return PackageContent(**base)


def _open(envelope: bytes) -> str | None:
    try:
        open_package(envelope, secret=SECRET, uid=UID, trusted_keys=[KEY.public_key], seq=1)
    except ProtocolError as error:
        return error.code
    return None


# --- §2 timestamps: writers must write exactly YYYY-MM-DDTHH:MM:SSZ ------------------------------------------------


def test_the_reader_accepts_a_four_digit_year_below_1000() -> None:
    """Control, §2: `0999-01-01T00:00:00Z` has the form YYYY-MM-DDTHH:MM:SSZ and is read."""
    assert parse_time("0999-01-01T00:00:00Z") == OLD


@pytest.mark.parametrize("year", [1, 999, 1000, 2026])
def test_format_time_always_writes_four_digit_years(year: int) -> None:
    """§2: a timestamp is exactly YYYY-MM-DDTHH:MM:SSZ; format_time is documented as parse_time's strict inverse.

    A writer either produces that form or refuses the date; it must never produce a text the reader refuses."""
    moment = datetime(year, 1, 1, tzinfo=UTC)
    try:
        text = format_time(moment)
    except ValueError:
        return
    assert len(text) == 20, text
    assert parse_time(text) == moment


def test_package_writer_with_an_early_period_from_does_not_emit_a_package_its_reader_refuses() -> None:
    """§7.2 period.from is a timestamp; seal_package raises ValueError for packages a reader would refuse.

    A `history` prepared from `since=0999-01-01` (§9) is the realistic way to get such a date."""
    try:
        envelope = seal_package(SECRET, KEY, _content(kind=Kind.HISTORY, period_from=OLD))
    except ValueError:
        return
    code = None
    try:
        open_package(envelope, secret=SECRET, uid=UID, trusted_keys=[KEY.public_key], seq=1)
    except ProtocolError as error:
        code = error.code
    assert code is None, f"the reader refuses what the writer produced: {code}"


def test_items_writer_with_an_early_fetched_at_does_not_emit_items_its_reader_refuses() -> None:
    """§7.4 fetched_at is a timestamp; encode_items must not produce an items.jsonl that parse_items refuses."""
    try:
        data = encode_items([Item("a", Change.NEW, HASH, {}, OLD, None)])
    except ValueError:
        return
    try:
        parse_items(data)
    except ProtocolError as error:
        pytest.fail(f"encode_items produced {data!r}, which parse_items refuses: {error.code}")


def test_rotation_writer_with_an_early_date_does_not_emit_a_statement_its_reader_refuses() -> None:
    """§6.3 issued_at is a timestamp; make_rotation must not produce a statement verify_rotation refuses."""
    try:
        rotation = make_rotation(KEY, OTHER.public_key, OLD)
    except ValueError:
        return
    try:
        verify_rotation(rotation.statement, rotation.signature)
    except ProtocolError as error:
        pytest.fail(f"make_rotation produced {rotation.statement!r}, which verify_rotation refuses: {error.code}")


def test_request_signer_with_an_early_date_does_not_emit_a_date_its_verifier_refuses() -> None:
    """§8 X-Veilleur-Date is a timestamp: sign_request then verify_request at the same moment must agree."""
    try:
        headers = sign_request(SECRET, KEY_ID, "GET", "/v1/collectors", b"", OLD)
    except ValueError:
        return
    try:
        verify_request(
            SECRET, "GET", "/v1/collectors", b"", authorization=headers.authorization, date=headers.date, now=OLD
        )
    except ProtocolError as error:
        pytest.fail(f"sign_request wrote {headers.date!r}, which verify_request refuses: {error.code}")


# --- §7.2 / §13 minor versions -------------------------------------------------------------------------------------


def _package_with_protocol(protocol: str) -> bytes:
    items = encode_items([Item("a", Change.NEW, HASH, {"x": 1}, NOW, None)])
    document = {
        "protocol": protocol,
        "uid": UID,
        "seq": 1,
        "kind": "delta",
        "created_at": format_time(NOW),
        "period": {"from": None, "to": format_time(NOW)},
        "files": {"items.jsonl": hashlib.sha256(items).hexdigest()},
        "sources": [],
    }
    manifest = json.dumps(document, separators=(",", ":"), sort_keys=True).encode()
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, data in (("manifest.json", manifest), ("manifest.sig", KEY.sign(manifest)), ("items.jsonl", items)):
            archive.writestr(zipfile.ZipInfo(name, (1980, 1, 1, 0, 0, 0)), data)
    return seal(SECRET, Header(UID, 1, Kind.DELTA), buffer.getvalue())


@pytest.mark.parametrize("protocol", ["1.0", "1.7", "1.999999"])
def test_minor_versions_are_accepted_control(protocol: str) -> None:
    """Control, §7.2: `1.<minor>` is accepted."""
    assert _open(_package_with_protocol(protocol)) is None


def test_every_minor_version_is_accepted() -> None:
    """§7.2: 'a reader accepts 1.<minor> and refuses any other major version'; §13 sets no bound on the minor number.

    1.1000000 is a minor version of major 1."""
    assert _open(_package_with_protocol("1.1000000")) is None


# --- Both implementations: same code for the same request or statement -----------------------------------------------


def _non_canonical_authorization() -> str:
    """A well-formed header whose 43-character MAC has one of its two unused trailing bits set (§2)."""
    headers = sign_request(SECRET, KEY_ID, "GET", "/v1/collectors", b"", NOW)
    scheme_and_id, mac = headers.authorization.split(":")
    alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"
    last = alphabet[alphabet.index(mac[-1]) ^ 1]
    return f"{scheme_and_id}:{mac[:-1]}{last}"


def _reference_request(authorization: str, date: str) -> str | None:
    try:
        verify_request(SECRET, "GET", "/v1/collectors", b"", authorization=authorization, date=date, now=NOW)
    except ProtocolError as error:
        return error.code
    return None


def _independent_request(authorization: str, date: str) -> str | None:
    case = {
        "authorization": authorization,
        "date": date,
        "now": format_time(NOW),
        "body": "",
        "method": "GET",
        "path_and_query": "/v1/collectors",
        "secret": SECRET.hex(),
    }
    try:
        CHECKER.verify_request(case)
    except CHECKER.Refused as refusal:
        code: str = refusal.code
        return code
    return None


def test_non_canonical_mac_alone_is_bad_authorization_in_both() -> None:
    """Control: with a good date, both implementations refuse a non-canonical MAC as bad_authorization."""
    authorization = _non_canonical_authorization()
    assert _reference_request(authorization, format_time(NOW)) == "bad_authorization"
    assert _independent_request(authorization, format_time(NOW)) == "bad_authorization"


@pytest.mark.parametrize(
    "date", [format_time(NOW - timedelta(minutes=6)), "2026-11-17 06:00:00"], ids=["stale", "malformed"]
)
def test_both_implementations_give_the_same_code_for_a_non_canonical_mac_and_a_bad_date(date: str) -> None:
    """§12: the independent implementation must refuse what the reference refuses 'with the same error code'."""
    authorization = _non_canonical_authorization()
    assert _independent_request(authorization, date) == _reference_request(authorization, date)


@pytest.mark.parametrize("member", ["old_key", "new_key"])
def test_independent_implementation_refuses_a_non_string_key_in_a_rotation_statement(member: str) -> None:
    """§6.3, §10.2 step 7: a malformed rotation statement is bad_rotation, in both implementations (§12)."""
    rotation = make_rotation(KEY, OTHER.public_key, NOW)
    document = json.loads(rotation.statement)
    document[member] = 12345
    statement = json.dumps(document, separators=(",", ":"), sort_keys=True).encode()
    signature = KEY.sign(statement)
    with pytest.raises(ProtocolError) as reference:
        verify_rotation(statement, signature)
    assert reference.value.code == "bad_rotation"
    try:
        CHECKER.read_rotation(statement, signature)
    except CHECKER.Refused as refusal:
        assert refusal.code == "bad_rotation"
    except Exception as error:  # the checker must refuse, not crash
        pytest.fail(f"check_vectors.read_rotation raised {type(error).__name__}: {error}")
    else:
        pytest.fail("check_vectors.read_rotation accepted a malformed statement")
