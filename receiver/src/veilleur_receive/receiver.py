# SPDX-License-Identifier: EUPL-1.2
"""Fetching, checking and filing reports, over HTTPS or from a folder (spec EF-50, EF-51).

Nothing is used before `open_package` has checked it. The numbers of a subscription must follow each other: a gap is
only accepted when a `state` covers it (protocol §7.3). The state is saved after each report, so an interrupted pull
resumes where it stopped.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from veilleur_protocol import (
    DEFAULT_LIMITS,
    Header,
    Kind,
    OpenedPackage,
    ProtocolError,
    open_package,
    read_header,
    sign_request,
)

from . import errors
from .deposit import deposit
from .errors import ReceiveError
from .store import State
from .transport import Transport, TransportError

_UID = re.compile(r"[0-9a-f]{32}")
_SHA256 = re.compile(r"[0-9a-f]{64}")
_CODE = re.compile(r"[a-z0-9_]{1,64}")
_NUMBERED = frozenset({Kind.DELTA, Kind.STATE})
_HEADER_BYTES = 70
"""What `read_header` needs: the shortest envelope."""
_MAX_RECOVERIES = 3
_MAX_GIVEN_UP = 8
"""Keys given up that are kept: each rotation adds one, and a rotation is rare."""


@dataclass(frozen=True)
class Failure:
    code: str
    uid: str | None = None
    seq: int | None = None
    file: str | None = None


@dataclass
class Outcome:
    written: list[Path] = field(default_factory=list)
    pending: list[str] = field(default_factory=list)
    failures: list[Failure] = field(default_factory=list)
    key_adopted: bool = False


class _Stop(Exception):
    """This subscription cannot go on for now."""

    def __init__(self, code: str, seq: int | None = None) -> None:
        self.code, self.seq = code, seq
        super().__init__(code)


class _Pending(Exception):
    """The server is preparing what was asked for."""


class _Resync(Exception):
    """The packages that follow can no longer be read one by one: a `state` must take over."""


Save = Callable[[State], None]


class _Filing:
    """Opens packages against the state, files them, and records what was received."""

    def __init__(self, state: State, folder: Path, save: Save, outcome: Outcome) -> None:
        self.state, self.folder, self.save, self.outcome = state, folder, save, outcome

    def open(self, data: bytes, uid: str, *, seq: int | None, kinds: frozenset[Kind] = _NUMBERED) -> OpenedPackage:
        return open_package(
            data, secret=self.state.secret, uid=uid, trusted_keys=self.state.trusted_keys, seq=seq, kinds=kinds
        )

    def opens_with_trusted_keys(self, data: bytes, uid: str, seq: int) -> bool:
        """Whether a package skipped for its signature opens with the keys trusted now (R42).

        A key adopted after the package was skipped may vouch for it: the export then holds no forgery. The check only
        decides whether to report: the package is neither read for its content nor filed (ES-07).
        """
        try:
            self.open(data, uid, seq=seq)
        except ProtocolError:
            return False
        return True

    def signed_by_given_up_key(self, data: bytes, uid: str, seq: int) -> bool:
        """Whether a package refused for its signature is old rather than forged: signed by a key given up since.

        Such a package is skipped in silence, since a `state` signed by the current key covers it (protocol §6.3);
        any other is reported. A state written by 0.1.x after a rotation does not know the key it gave up: its
        packages are skipped in silence, as they were before.
        """
        if not self.state.given_up:
            return self.state.rotated
        try:
            opened = open_package(
                data, secret=self.state.secret, uid=uid, trusted_keys=self.state.given_up, seq=seq, kinds=_NUMBERED
            )
        except ProtocolError:
            return False
        # Signed by a given-up key itself: a key vouched for by one (a stolen key's statement) is a forgery.
        return opened.rotation is None

    def file(self, opened: OpenedPackage) -> None:
        try:
            self.outcome.written.append(deposit(self.folder, opened))
        except ValueError as exc:  # items no writer can encode again
            raise _Stop("bad_items", opened.seq) from exc
        if opened.rotation is not None:
            # Protocol §6.3: once the incoming key is adopted, the outgoing one is no longer trusted.
            given_up = [key for key in self.state.given_up if key not in self.state.trusted_keys]
            self.state.given_up = [*given_up, *self.state.trusted_keys][-_MAX_GIVEN_UP:]
            self.state.trusted_keys = [opened.rotation.new_key]
            self.state.rotated = True
            self.outcome.key_adopted = True
        self.state.last[opened.uid] = opened.seq
        self.save(self.state)


# --- Over HTTPS ------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class _Listing:
    packages: dict[int, tuple[int, str]]
    last: int


def _number(value: Any) -> int:
    if type(value) is not int or value < 0:
        raise ValueError("number")
    return value


def _listing(body: bytes) -> _Listing:
    try:
        document = json.loads(body)
        packages: dict[int, tuple[int, str]] = {}
        for entry in document["packages"]:
            if not isinstance(entry["sha256"], str) or not _SHA256.fullmatch(entry["sha256"]):
                raise ValueError("sha256")
            packages[_number(entry["seq"])] = (_number(entry["size"]), entry["sha256"])
        return _Listing(packages, _number(document["last"]))
    except (ValueError, KeyError, TypeError) as exc:
        raise _Stop("bad_response") from exc


def _uids(body: bytes) -> list[str]:
    """Live subscriptions. A `uid` becomes a folder name: anything but 32 hexadecimal digits is refused."""
    try:
        uids = [entry["uid"] for entry in json.loads(body)["subscriptions"]]
    except (ValueError, KeyError, TypeError) as exc:
        raise _Stop("bad_response") from exc
    if not all(isinstance(uid, str) and _UID.fullmatch(uid) for uid in uids):
        raise _Stop("bad_response")
    return uids


def _refusal(status: int, body: bytes) -> str:
    """The server's stable code for a refusal, otherwise the status."""
    try:
        code = json.loads(body)["code"]
    except (ValueError, KeyError, TypeError):
        code = None
    return code if isinstance(code, str) and _CODE.fullmatch(code) else f"http_{status}"


class _Puller:
    def __init__(self, filing: _Filing, transport: Transport, clock: Callable[[], datetime]) -> None:
        self.filing, self.transport, self.clock = filing, transport, clock

    def get(self, target: str) -> tuple[int, bytes]:
        state = self.filing.state
        signed = sign_request(state.secret, state.key_id, "GET", target, b"", self.clock())
        try:
            reply = self.transport.get(target, {"Authorization": signed.authorization, "X-Veilleur-Date": signed.date})
        except TransportError as exc:
            raise _Stop(exc.code) from exc
        return reply.status, reply.body

    def run(self) -> None:
        outcome = self.filing.outcome
        try:
            status, body = self.get("/v1/subscriptions")
            if status != 200:
                raise _Stop(_refusal(status, body))
            uids = _uids(body)
        except _Stop as stop:
            outcome.failures.append(Failure(stop.code))
            return
        for uid in uids:
            try:
                self.subscription(uid)
            except _Pending:
                outcome.pending.append(uid)
            except _Stop as stop:
                outcome.failures.append(Failure(stop.code, uid, stop.seq))

    def subscription(self, uid: str) -> None:
        for _attempt in range(_MAX_RECOVERIES):
            try:
                self.catch_up(uid)
                return
            except _Resync:
                self.take_state(uid)
        raise _Stop("no_progress")

    def catch_up(self, uid: str) -> None:
        last = self.filing.state.last.get(uid, 0)
        status, body = self.get(f"/v1/subscriptions/{uid}/reports?after={last}")
        if status != 200:
            raise _Stop(_refusal(status, body))
        listing = _listing(body)
        if listing.last < last:
            raise _Stop("server_behind")  # the server forgot reports already received: restored, or not the same one
        if listing.last == last:
            return
        for seq in range(last + 1, listing.last + 1):
            if seq not in listing.packages:
                raise _Resync  # purged (protocol §9): only a `state` can cover the gap
            self.take_package(uid, seq, *listing.packages[seq])

    def take_package(self, uid: str, seq: int, size: int, sha256: str) -> None:
        status, data = self.get(f"/v1/subscriptions/{uid}/reports/{seq}")
        if status == 410:
            raise _Resync
        if status != 200:
            raise _Stop(_refusal(status, data), seq)
        if len(data) != size or hashlib.sha256(data).hexdigest() != sha256:
            raise _Stop("listing_mismatch", seq)
        try:
            opened = self.filing.open(data, uid, seq=seq)
        except ProtocolError as exc:
            if exc.code == "bad_signature" and self.filing.signed_by_given_up_key(data, uid, seq):
                raise _Resync from exc  # signed by the key given up since: a `state` is signed by the new one
            raise _Stop(exc.code, seq) from exc
        self.filing.file(opened)

    def take_state(self, uid: str) -> None:
        last = self.filing.state.last.get(uid, 0)
        status, data = self.get(f"/v1/subscriptions/{uid}/state")
        if status == 202:
            raise _Pending
        if status != 200:
            raise _Stop(_refusal(status, data))
        try:
            opened = self.filing.open(data, uid, seq=None, kinds=frozenset({Kind.STATE}))
        except ProtocolError as exc:
            raise _Stop(exc.code) from exc
        if opened.seq <= last:
            raise _Stop("seq_mismatch", opened.seq)
        self.filing.file(opened)


def pull(state: State, transport: Transport, folder: Path, save: Save, clock: Callable[[], datetime]) -> Outcome:
    """Fetch what is new for every subscription of the pairing."""
    outcome = Outcome()
    _Puller(_Filing(state, folder, save, outcome), transport, clock).run()
    return outcome


# --- From a folder ---------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class _Found:
    path: Path
    header: Header

    @property
    def order(self) -> tuple[int, int]:
        """By number; a `state` before the `delta` of the same number, which it makes useless."""
        return self.header.seq, 0 if self.header.kind is Kind.STATE else 1


def _survey(source: Path, outcome: Outcome) -> dict[str, list[_Found]]:
    """Packages of a folder by subscription, from their headers: nothing is trusted yet."""
    found: dict[str, list[_Found]] = {}
    for path in sorted(source.iterdir()):
        if path.suffix != ".veil" or path.is_symlink() or not path.is_file():
            continue
        try:
            with path.open("rb") as file:
                header = read_header(file.read(_HEADER_BYTES))
        except ProtocolError as exc:
            outcome.failures.append(Failure(exc.code, file=path.name))
        except OSError:
            outcome.failures.append(Failure("unreadable_file", file=path.name))
        else:
            found.setdefault(header.uid, []).append(_Found(path, header))
    return found


def _can_take_over(package: _Found, following: list[_Found]) -> bool:
    """Whether a package further on holds this number, or a `state` accounts for it."""
    return any(
        other.header.kind in _NUMBERED and (other.header.seq == package.header.seq or other.header.kind is Kind.STATE)
        for other in following
    )


def _read_subscription(filing: _Filing, uid: str, packages: list[_Found]) -> None:
    skipped: list[_Found] = []
    try:
        _read_in_order(filing, uid, packages, skipped)
    finally:
        _report_forged(filing, uid, skipped)


def _report_forged(filing: _Filing, uid: str, skipped: list[_Found]) -> None:
    """Packages skipped for their signature: an old one is expected in an export, any other is reported (R02).

    Old means signed by a key trusted once the whole subscription is read, adopted meanwhile included (R42), or by a
    key given up since.
    """
    for package in skipped:
        try:
            data = package.path.read_bytes()
        except OSError:
            filing.outcome.failures.append(Failure("unreadable_file", uid, package.header.seq))
            continue
        seq = package.header.seq
        if not (filing.opens_with_trusted_keys(data, uid, seq) or filing.signed_by_given_up_key(data, uid, seq)):
            filing.outcome.failures.append(Failure("bad_signature", uid, seq))


def _read_in_order(filing: _Filing, uid: str, packages: list[_Found], skipped: list[_Found]) -> None:
    ordered = sorted(packages, key=lambda found: found.order)
    newest_state = max((p.header.seq for p in ordered if p.header.kind is Kind.STATE), default=0)
    for position, package in enumerate(ordered):
        seq, kind = package.header.seq, package.header.kind
        if kind not in _NUMBERED:
            filing.outcome.failures.append(Failure("kind_mismatch", uid, seq))
            continue
        last = filing.state.last.get(uid, 0)
        if seq <= last:
            continue  # already received
        if kind is Kind.DELTA and seq != last + 1:
            if newest_state > seq:
                continue  # a later `state` covers it
            raise _Stop("missing_package", last + 1)
        try:
            if package.path.stat().st_size > DEFAULT_LIMITS.max_package:
                raise _Stop("too_large", seq)
            opened = filing.open(package.path.read_bytes(), uid, seq=seq)
        except ProtocolError as exc:
            if exc.code == "bad_signature" and _can_take_over(package, ordered[position + 1 :]):
                # Another key than the one trusted now: what follows is checked in turn, the last one stops. Whether
                # this one was old or forged is told once the subscription is read, the keys adopted meanwhile known.
                skipped.append(package)
                continue
            raise _Stop(exc.code, seq) from exc
        except OSError as exc:
            raise _Stop("unreadable_file", seq) from exc
        filing.file(opened)


def read_folder(state: State, source: Path, folder: Path, save: Save) -> Outcome:
    """Read the packages of a folder written by `veilleur export` (EF-51)."""
    if source.is_symlink() or not source.is_dir():
        raise ReceiveError(errors.NO_SOURCE_FOLDER)
    outcome = Outcome()
    filing = _Filing(state, folder, save, outcome)
    for uid, packages in sorted(_survey(source, outcome).items()):
        try:
            _read_subscription(filing, uid, packages)
        except _Stop as stop:
            outcome.failures.append(Failure(stop.code, uid, stop.seq))
    return outcome
