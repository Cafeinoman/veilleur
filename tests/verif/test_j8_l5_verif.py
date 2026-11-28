# SPDX-License-Identifier: EUPL-1.2
"""Independent check of batch J8-L5: no false alarm after two rotations (R42), forged packages still reported.

Sources: PLAN J8-L5 (steps 1 and 2, acceptance criteria 1 to 3); SPEC ES-05, ES-07; ADR-0019; protocol §6.3, §10.2.
Keys are named as in R42: the member starts on B, the server then rotates to C, then to D.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.receiver.test_end_to_end import UID, Bench, _rotate, _server_key
from tests.verif.test_g4_verif_pass3 import _bench, _export, _forged, _read, _report  # noqa: F401  (fixture)
from veilleur_protocol import Kind, make_rotation, read_header
from veilleur_protocol.signing import SigningKey
from veilleur_receive import receiver, store

FORGED = "0-forged.veil"
"""Sorts before the files of UID: the forged package is met before the real one of its number. Behind it, a forged
`delta` would be passed over as already received without being opened (R43)."""


def _member_on_b_then_b_c_d(bench: Bench, *, package_under_d: bool = False) -> tuple[SigningKey, SigningKey]:
    """Package 1 under B (received), package 2 under C, then a rotation to D; returns (C, D)."""
    bench.subscribe()
    _report(bench, "a")
    assert bench.pull() == 0 and bench.last() == 1
    bench.core = _rotate(bench)
    _report(bench, "a", "b")
    second = _server_key(bench)
    bench.core = _rotate(bench)
    third = _server_key(bench)
    if package_under_d:
        _report(bench, "a", "b", "c")
    return second, third


def _exported(bench: Bench, target: Path) -> list[str]:
    assert _export(bench, target, UID, "--after", "1") == 0
    return sorted(path.name for path in target.iterdir())


# --- Criterion 1 / step 1: the R42 export reads in silence ------------------------------------------------------------


def test_the_r42_export_holds_a_state_before_the_delta_of_its_number(bench: Bench, tmp_path: Path) -> None:
    """PLAN J8-L5 criterion 1: the scenario is the one of R42 (rebuilt `state` 2 under D, `delta` 2 under C)."""
    _member_on_b_then_b_c_d(bench)
    names = _exported(bench, tmp_path / "usb")
    assert names == [f"{UID}-00000002-delta.veil", f"{UID}-00000002-state-rebuilt.veil"]
    state = read_header((tmp_path / "usb" / names[1]).read_bytes()[:70])
    assert state.kind is Kind.STATE and state.seq == 2


def test_the_r42_export_reads_in_silence(bench: Bench, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """PLAN J8-L5 criterion 1: exit 0 and empty stderr."""
    _member_on_b_then_b_c_d(bench)
    _exported(bench, tmp_path / "usb")
    capsys.readouterr()
    assert _read(bench, tmp_path / "usb") == 0
    assert capsys.readouterr().err == ""
    assert bench.last() == 2


# --- Step 2: the second check only decides the report (ES-07) -------------------------------------------------------


def test_the_skipped_state_is_neither_filed_nor_used_for_its_key(bench: Bench, tmp_path: Path) -> None:
    """PLAN J8-L5 step 2: the skipped package is neither filed nor read; its statement (C→D) is not acted upon."""
    second, third = _member_on_b_then_b_c_d(bench)
    _exported(bench, tmp_path / "usb")
    before = sorted(path.name for path in bench.folder.rglob("*")) if bench.folder.exists() else []
    assert _read(bench, tmp_path / "usb") == 0
    assert bench.filed() == ["00000001-state", "00000002-delta"]
    after = sorted(path.name for path in bench.folder.rglob("*"))
    assert not any("00000002-state" in name for name in after), (before, after)
    state = store.load(bench.state_dir)
    assert state.trusted_keys == [second.public_key]
    assert third.public_key not in state.trusted_keys and third.public_key not in state.given_up


def test_the_second_check_changes_nothing(bench: Bench, tmp_path: Path) -> None:
    """PLAN J8-L5 step 2: `opens_with_trusted_keys` neither saves, files, nor adopts the key it finds."""
    second, _third = _member_on_b_then_b_c_d(bench)
    source = tmp_path / "usb"
    _exported(bench, source)
    state = store.load(bench.state_dir)
    state.trusted_keys = [second.public_key]  # as after the `delta` 2 of the read
    trusted, given_up, last = list(state.trusted_keys), list(state.given_up), dict(state.last)
    saved: list[object] = []
    outcome = receiver.Outcome()
    filing = receiver._Filing(state, tmp_path / "nowhere", saved.append, outcome)
    data = (source / f"{UID}-00000002-state-rebuilt.veil").read_bytes()
    assert filing.opens_with_trusted_keys(data, UID, 2)
    assert (state.trusted_keys, state.given_up, state.last) == (trusted, given_up, last)
    assert saved == [] and outcome == receiver.Outcome() and not (tmp_path / "nowhere").exists()


def test_the_second_check_refuses_a_package_of_another_number(bench: Bench, tmp_path: Path) -> None:
    """The second check keeps every check of the reader (protocol §10.2 step 3): a number other than expected fails."""
    second, _third = _member_on_b_then_b_c_d(bench)
    source = tmp_path / "usb"
    _exported(bench, source)
    state = store.load(bench.state_dir)
    state.trusted_keys = [second.public_key]
    filing = receiver._Filing(state, tmp_path / "nowhere", lambda _state: None, receiver.Outcome())
    data = (source / f"{UID}-00000002-state-rebuilt.veil").read_bytes()
    assert not filing.opens_with_trusted_keys(data, UID, 3)
    assert not filing.opens_with_trusted_keys(data, "0" * 32, 2)


# --- Criterion 2: a forged package is still reported ---------------------------------------------------------------


def test_a_forged_package_beside_the_r42_export_is_still_reported(
    bench: Bench, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """PLAN J8-L5 criterion 2: a key adopted during the read does not vouch for an unknown key."""
    _member_on_b_then_b_c_d(bench)
    source = tmp_path / "usb"
    _exported(bench, source)
    (source / FORGED).write_bytes(_forged(bench, 2, Kind.STATE, SigningKey.generate()))
    capsys.readouterr()
    assert _read(bench, source) == 1
    err = capsys.readouterr().err
    assert err.count("bad_signature") == 1 and f"subscription {UID}, package 2: refused (bad_signature)" in err
    assert bench.filed() == ["00000001-state", "00000002-delta"]


def test_a_forged_package_is_reported_when_the_read_stops_after_an_adoption(
    bench: Bench, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The report is made with the keys of the moment the read stopped (a gap after the `delta` 2)."""
    second, _third = _member_on_b_then_b_c_d(bench)
    source = tmp_path / "usb"
    _exported(bench, source)
    (source / FORGED).write_bytes(_forged(bench, 2, Kind.STATE, SigningKey.generate()))
    (source / "gap.veil").write_bytes(_forged(bench, 5, Kind.DELTA, second))
    capsys.readouterr()
    assert _read(bench, source) == 1
    err = capsys.readouterr().err
    assert "package 2: refused (bad_signature)" in err and "missing_package" in err


# --- Criterion 3: a statement of a given-up key for a third key ----------------------------------------------------


def test_a_statement_of_c_for_a_thief_is_reported_once_d_is_adopted(
    bench: Bench, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """PLAN J8-L5 criterion 3: C adopted then given up during the read; a `delta` 2 vouched for by C is a forgery."""
    second, third = _member_on_b_then_b_c_d(bench, package_under_d=True)
    source = tmp_path / "usb"
    _exported(bench, source)
    thief = SigningKey.generate()
    statement = make_rotation(second, thief.public_key, bench.world.clock.now())
    (source / FORGED).write_bytes(_forged(bench, 2, Kind.DELTA, thief, statement))
    capsys.readouterr()
    assert _read(bench, source) == 1
    assert f"subscription {UID}, package 2: refused (bad_signature)" in capsys.readouterr().err
    state = store.load(bench.state_dir)
    assert state.trusted_keys == [third.public_key]
    assert thief.public_key not in state.trusted_keys and thief.public_key not in state.given_up


def test_a_statement_of_b_given_up_before_the_read_for_a_thief_is_reported(
    bench: Bench, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """PLAN J8-L5 criterion 3: B given up by an earlier read; a statement B→thief is still a forgery."""
    bench.subscribe()
    _report(bench, "a")
    assert bench.pull() == 0
    first = _server_key(bench)
    bench.core = _rotate(bench)
    _report(bench, "a", "b")
    assert bench.pull() == 0 and first.public_key in store.load(bench.state_dir).given_up
    _report(bench, "a", "b", "c")
    source = tmp_path / "usb"
    assert _export(bench, source, UID, "--after", "2") == 0
    thief = SigningKey.generate()
    statement = make_rotation(first, thief.public_key, bench.world.clock.now())
    (source / FORGED).write_bytes(_forged(bench, 3, Kind.STATE, thief, statement))
    capsys.readouterr()
    assert _read(bench, source) == 1
    assert f"subscription {UID}, package 3: refused (bad_signature)" in capsys.readouterr().err
    assert thief.public_key not in store.load(bench.state_dir).trusted_keys


@pytest.mark.xfail(
    strict=True,
    reason="minor (J8-L5, R02 narrowed): in the R42 export the rebuilt `state` 2 (C→D) is skipped and never filed, so "
    "the member ends on C, never given up; a statement C→thief beside it then opens with the keys trusted at the end "
    "and is no longer reported (main reported it). Telling it apart needs the conflict of two statements of C",
)
def test_a_statement_of_c_for_a_thief_beside_the_server_statement_c_to_d_is_reported(
    bench: Bench, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The export itself proves the server gave C up (statement C→D): a statement C→thief beside it is a forgery."""
    second, _third = _member_on_b_then_b_c_d(bench)
    source = tmp_path / "usb"
    _exported(bench, source)
    thief = SigningKey.generate()
    statement = make_rotation(second, thief.public_key, bench.world.clock.now())
    (source / FORGED).write_bytes(_forged(bench, 2, Kind.STATE, thief, statement))
    capsys.readouterr()
    code = _read(bench, source)
    err = capsys.readouterr().err
    assert thief.public_key not in store.load(bench.state_dir).trusted_keys
    assert code == 1 and "package 2: refused (bad_signature)" in err, (code, err)


@pytest.mark.xfail(
    strict=True,
    reason="out of spec (pre-existing, read path untouched by J8-L5): a forged `state` 3 vouched for by C sorts before "
    "the real `delta` 3 (C→D); C is still trusted when it is opened, so the thief's key is adopted",
)
def test_a_thief_key_vouched_for_by_c_is_not_adopted_when_its_state_sorts_first(
    bench: Bench, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Criterion 3 read literally ("the third key is never adopted"), on an export where the server gave C up."""
    second, third = _member_on_b_then_b_c_d(bench, package_under_d=True)
    source = tmp_path / "usb"
    _exported(bench, source)
    thief = SigningKey.generate()
    statement = make_rotation(second, thief.public_key, bench.world.clock.now())
    (source / FORGED).write_bytes(_forged(bench, 3, Kind.STATE, thief, statement))
    capsys.readouterr()
    _read(bench, source)
    state = store.load(bench.state_dir)
    assert thief.public_key not in state.trusted_keys, capsys.readouterr()
    assert third.public_key in state.trusted_keys
