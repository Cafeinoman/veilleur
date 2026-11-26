# SPDX-License-Identifier: EUPL-1.2
"""Independent check of batch J8-L2: reporting a forged package (R02), never repeating a pairing code typed on the
command line (R03), refusing a pairing code that is not text (R14).

Sources: PLAN J8-L2 (acceptance criteria 1 to 3); SPEC ES-07, EF-60; ADR-0019; protocol §6.3.
"""

from __future__ import annotations

import io
import os
import subprocess
import sys
from pathlib import Path

import pytest

from tests.receiver.test_end_to_end import OTHER, UID, Bench, _rotate, _sealed, _server_key, _two_reports
from tests.verif.test_g4_verif_pass3 import _bench, _export, _forged, _read, _report  # noqa: F401  (fixture)
from veilleur_protocol import make_rotation
from veilleur_protocol.envelope import Kind
from veilleur_protocol.signing import SigningKey
from veilleur_receive import cli, i18n, store


def _leaks(code: str, text: str) -> list[str]:
    """Substrings of 16 characters of the code found in the text (PLAN J8-L2, criterion 2)."""
    return [code[start : start + 16] for start in range(len(code) - 15) if code[start : start + 16] in text]


def _run(argv: list[str], capsys: pytest.CaptureFixture[str]) -> tuple[int | str | None, str]:
    capsys.readouterr()
    with pytest.raises(SystemExit) as raised:
        cli.main(argv)
    captured = capsys.readouterr()
    return raised.value.code, captured.out + captured.err


# --- R03, criterion 2: the code is never repeated --------------------------------------------------------------------


@pytest.mark.parametrize("lang", ["en", "fr"])
@pytest.mark.parametrize(
    "argv",
    [
        ["pair", "{code}"],  # criterion 2 as written
        ["pair", "--", "{code}"],
        ["pair", "{code}", "{code}"],
        ["pair", "--code", "{code}"],
        ["pair", "-c{code}"],
        ["{code}"],
        ["{code}", "pair"],
        ["--lang", "{code}", "pair"],
        ["--lang={code}", "pair"],
        ["version", "{code}"],
        ["pull", "{code}"],
        ["pull", "--folder", "r", "--from", "s", "{code}"],
        ["pull", "--folder", "r", "--bogus={code}"],
        ["--state-dir", "s", "--{code}", "pair"],
    ],
)
def test_no_16_characters_of_the_code_are_repeated(
    bench: Bench, lang: str, argv: list[str], capsys: pytest.CaptureFixture[str]
) -> None:
    tokens = [token.format(code=bench.code) for token in argv]
    status, text = _run(["--lang", lang, "--state-dir", str(bench.state_dir), *tokens], capsys)
    assert status not in (0, None)
    assert _leaks(bench.code, text) == []


def test_pair_with_a_code_exits_non_zero_before_reading_anything(
    bench: Bench, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Criterion 2: the command fails; it neither reads the standard input nor pairs."""

    class Untouchable(io.StringIO):
        def readline(self, *args: object) -> str:  # type: ignore[override]
            raise AssertionError("standard input read")

    monkeypatch.setattr("sys.stdin", Untouchable())
    state = tmp_path / "fresh"
    status, text = _run(["--lang", "en", "--state-dir", str(state), "pair", bench.code], capsys)
    assert status == 2
    assert not (state / store.STATE_FILE).exists()
    assert "never from the command line" in text


@pytest.mark.parametrize("suffix", ["\r", "\t", "\n", "\x1b"])
@pytest.mark.xfail(
    strict=True,
    reason="minor (J8-L2 R03): argparse quotes an invalid choice with repr(); a code typed with a control character "
    "(pasted '\\r', tab) is escaped in the message, so the raw token no longer matches and the code is repeated",
)
def test_a_code_with_a_control_character_is_not_repeated(
    bench: Bench, suffix: str, capsys: pytest.CaptureFixture[str]
) -> None:
    status, text = _run(["--lang", "en", "--state-dir", str(bench.state_dir), bench.code + suffix], capsys)
    assert status not in (0, None)
    assert _leaks(bench.code, text) == []


@pytest.mark.xfail(
    strict=True,
    reason="minor (J8-L2 R03): a code pasted with an invisible format character (U+200B, U+FEFF) is escaped by "
    "repr() in argparse's 'invalid choice' message and repeated",
)
def test_a_code_with_an_invisible_character_is_not_repeated(bench: Bench, capsys: pytest.CaptureFixture[str]) -> None:
    status, text = _run(["--lang", "en", "--state-dir", str(bench.state_dir), "﻿" + bench.code], capsys)
    assert status not in (0, None)
    assert _leaks(bench.code, text) == []


def test_a_short_mistake_is_still_explained(capsys: pytest.CaptureFixture[str]) -> None:
    """Hiding must not make ordinary mistakes unreadable."""
    status, text = _run(["--lang", "en", "pull", "--folder"], capsys)
    assert status == 2 and "--folder" in text and "expected one argument" in text


def test_the_new_message_is_translated(capsys: pytest.CaptureFixture[str]) -> None:
    """Criterion 3: the message added exists in French and in English."""
    _, english = _run(["--lang", "en", "pair", "x"], capsys)
    _, french = _run(["--lang", "fr", "pair", "x"], capsys)
    assert "never from the command line" in english
    assert "jamais sur la ligne de commande" in french and "never" not in french


def test_the_french_catalogue_has_no_fuzzy_entry_for_the_new_message() -> None:
    po = Path(i18n.__file__).parent / "locale" / "fr" / "LC_MESSAGES" / "veilleur_receive.po"
    text = po.read_text("utf-8")
    block = text.split("the pairing code is read from the terminal")[0].rsplit("\n\n", 1)[-1]
    assert "fuzzy" not in block


# --- R14: a code that is not text -----------------------------------------------------------------------------------


def _pair_process(tmp_path: Path, data: bytes, **env: str) -> subprocess.CompletedProcess[bytes]:
    base = {key: value for key, value in os.environ.items() if key in ("PATH", "LD_LIBRARY_PATH", "PYTHONPATH")}
    return subprocess.run(
        [sys.executable, "-m", "veilleur_receive", "--lang", "en", "--state-dir", str(tmp_path / "s"), "pair"],
        input=data,
        capture_output=True,
        check=False,
        env={**base, **env},
        timeout=60,
    )


@pytest.mark.parametrize(
    "env",
    [
        {"PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "0", "LC_ALL": "C.UTF-8"},
        {"PYTHONUTF8": "1"},  # UTF-8 mode: standard input with surrogateescape
        {"LC_ALL": "C", "PYTHONUTF8": "0", "PYTHONCOERCECLOCALE": "0"},
        {"PYTHONIOENCODING": "utf-8:surrogateescape"},
        {"PYTHONIOENCODING": "latin-1"},
    ],
)
@pytest.mark.parametrize(
    "data", [b"\xff\xfe\n", b"VEIL1:\xff\xfe\n", b"VEIL1:" + b"A" * 40 + b"\xc3\n", b"\x80" * 5000]
)
def test_a_code_that_is_not_text_is_refused_cleanly(tmp_path: Path, env: dict[str, str], data: bytes) -> None:
    done = _pair_process(tmp_path, data, **env)
    assert done.returncode == 1, done.stderr
    assert b"Traceback" not in done.stderr
    assert b"error:" in done.stderr
    assert not (tmp_path / "s" / store.STATE_FILE).exists()


def test_a_code_that_is_not_text_from_the_terminal_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The terminal path (`getpass`) fails the same way."""

    class Terminal(io.StringIO):
        def isatty(self) -> bool:
            return True

    def broken(prompt: str = "") -> str:
        raise UnicodeDecodeError("utf-8", b"\xff", 0, 1, "invalid start byte")

    monkeypatch.setattr("sys.stdin", Terminal())
    monkeypatch.setattr("getpass.getpass", broken)
    assert cli.main(["--lang", "en", "--state-dir", str(tmp_path / "s"), "pair"]) == 1
    assert "not valid" in capsys.readouterr().err


def test_after_a_refused_code_a_good_one_still_pairs(
    bench: Bench, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The refusal leaves nothing behind that would block the next attempt (no state, no stale lock)."""
    state = tmp_path / "again"
    monkeypatch.setattr("sys.stdin", io.TextIOWrapper(io.BytesIO(b"\xff\n"), encoding="utf-8"))
    assert cli.main(["--lang", "en", "--state-dir", str(state), "pair"]) == 1
    monkeypatch.setattr("sys.stdin", io.StringIO(bench.code + "\n"))
    assert cli.main(["--lang", "en", "--state-dir", str(state), "pair"]) == 0


# --- R02: a forged package is reported -------------------------------------------------------------------------------


@pytest.mark.xfail(
    strict=True,
    reason="minor (J8-L2 R02): a `delta` of the same number as a valid `state` is passed over as already received, "
    "without being opened: a forged one is ignored without being reported (receiver.py, `seq <= last`)",
)
def test_a_forged_delta_covered_by_a_state_is_reported(
    bench: Bench, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """PLAN J8-L2 step: a forged package is reported even when a `state` covers it; here a `state` of its number."""
    bench.subscribe()
    _report(bench, "a")
    assert bench.pull() == 0
    source = tmp_path / "usb"
    source.mkdir()
    (source / "a.veil").write_bytes(_forged(bench, 2, Kind.DELTA, SigningKey.generate()))
    (source / "b.veil").write_bytes(_sealed(bench, 2, Kind.STATE))
    capsys.readouterr()
    assert _read(bench, source) == 1
    err = capsys.readouterr().err
    assert f"subscription {UID}, package 2: refused (bad_signature)" in err
    assert "00000002-delta" not in bench.filed() and "00000002-state" in bench.filed()


@pytest.mark.xfail(
    strict=True,
    reason="minor (J8-L2 R02): a `delta` in a gap covered by a later `state` is passed over without being opened: "
    "a forged one is ignored without being reported (receiver.py, `newest_state > seq`)",
)
def test_a_forged_delta_in_a_gap_covered_by_a_later_state_is_reported(
    bench: Bench, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """PLAN J8-L2 step: a forged package is reported even when a `state` covers it; here a later `state`."""
    source = tmp_path / "usb"
    source.mkdir()
    (source / "a.veil").write_bytes(_forged(bench, 2, Kind.DELTA, SigningKey.generate()))
    (source / "b.veil").write_bytes(_sealed(bench, 3, Kind.STATE))
    capsys.readouterr()
    assert _read(bench, source) == 1
    assert f"subscription {UID}, package 2: refused (bad_signature)" in capsys.readouterr().err
    assert bench.filed() == ["00000003-state"]


def test_a_forged_package_is_reported_once(bench: Bench, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    source = tmp_path / "usb"
    source.mkdir()
    (source / "1.veil").write_bytes(_sealed(bench, 1, Kind.STATE, key=SigningKey.generate()))
    (source / "2.veil").write_bytes(_sealed(bench, 2, Kind.STATE))
    capsys.readouterr()
    assert _read(bench, source) == 1
    assert capsys.readouterr().err.count("bad_signature") == 1


def test_a_forged_package_is_reported_when_the_subscription_then_stops(
    bench: Bench, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A forged package skipped, then a later failure: both are told."""
    source = tmp_path / "usb"
    source.mkdir()
    (source / "1.veil").write_bytes(_sealed(bench, 1, Kind.STATE, key=SigningKey.generate()))
    (source / "2.veil").write_bytes(_sealed(bench, 2, Kind.STATE, key=SigningKey.generate()))
    capsys.readouterr()
    assert _read(bench, source) == 1
    err = capsys.readouterr().err
    assert "package 1: refused (bad_signature)" in err and "package 2: refused (bad_signature)" in err
    assert bench.filed() == []


def test_a_package_signed_by_the_given_up_key_is_not_reported(
    bench: Bench, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Protocol §6.3 / ADR-0019: an export holds the old packages beside the `state`; they are expected, not forged."""
    bench.subscribe()
    _report(bench, "a")
    assert bench.pull() == 0
    bench.core = _rotate(bench)
    _report(bench, "a", "b")
    assert bench.pull() == 0
    assert store.load(bench.state_dir).rotated
    _report(bench, "a", "b", "c")
    assert _export(bench, tmp_path / "usb") == 0
    capsys.readouterr()
    assert _read(bench, tmp_path / "usb") == 0
    assert "bad_signature" not in capsys.readouterr().err


def test_a_statement_from_a_given_up_key_for_a_thief_is_reported(
    bench: Bench, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A stolen old key vouches for a thief's key: the package is forged even though a given-up key is involved."""
    _two_reports(bench)
    assert bench.pull() == 0
    from veilleur.adapters import keys

    stolen = keys.load_signing_key(bench.world.app.config.state_dir)
    bench.core = _rotate(bench)
    bench.world.collector.set("news", ("z", {"title": "Z"}))
    bench.round()
    assert bench.pull() == 0 and store.load(bench.state_dir).given_up
    thief = SigningKey.generate()
    statement = make_rotation(stolen, thief.public_key, bench.world.clock.now())
    source = tmp_path / "usb"
    source.mkdir()
    (source / "1.veil").write_bytes(_forged(bench, 1, Kind.STATE, thief, statement, uid=OTHER))
    (source / "2.veil").write_bytes(_sealed(bench, 2, Kind.STATE, uid=OTHER, key=_server_key(bench)))
    capsys.readouterr()
    assert _read(bench, source) == 1
    assert f"subscription {OTHER}, package 1: refused (bad_signature)" in capsys.readouterr().err
    assert thief.public_key not in store.load(bench.state_dir).trusted_keys


def test_the_given_up_keys_survive_a_save_and_a_load(bench: Bench) -> None:
    _two_reports(bench)
    assert bench.pull() == 0
    old = bench.core.sealer.public_key
    bench.core = _rotate(bench)
    bench.world.collector.set("news", ("z", {"title": "Z"}))
    bench.round()
    assert bench.pull() == 0
    state = store.load(bench.state_dir)
    assert state.given_up == [old] and old not in state.trusted_keys
    assert (bench.state_dir / store.STATE_FILE).stat().st_mode & 0o077 == 0


@pytest.mark.parametrize("value", ["not a list", [1], ["!!"], [None]])
def test_a_corrupt_given_up_list_is_an_unreadable_state(
    bench: Bench, value: object, capsys: pytest.CaptureFixture[str]
) -> None:
    import json

    path = bench.state_dir / store.STATE_FILE
    document = json.loads(path.read_text())
    document["given_up"] = value
    path.write_text(json.dumps(document))
    capsys.readouterr()
    assert bench.pull() == 1
    err = capsys.readouterr().err
    assert "state file cannot be read" in err and "Traceback" not in err


@pytest.mark.xfail(
    strict=True,
    reason="minor (J8-L2 R02, regression from main): a legitimate rebuilt `state` skipped before the `delta` that "
    "makes its signer's predecessor trusted is reported as `bad_signature` (exit 1); main read the same export with "
    "exit 0. `signed_by_given_up_key` checks given-up keys only, not the keys adopted meanwhile",
)
def test_a_legitimate_export_after_two_rotations_raises_no_alarm(
    bench: Bench, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A member on key B reads an export written after two more rotations (C, then D) with one package under C.

    The rebuilt `state` (signed by D, statement C→D) comes before the `delta` of its number (signed by C, statement
    B→C): it is skipped, then the `delta` makes C trusted. Nothing here is forged.
    """
    bench.subscribe()
    _report(bench, "a")
    bench.core = _rotate(bench)
    _report(bench, "a", "b")
    assert _export(bench, tmp_path / "first") == 0
    assert _read(bench, tmp_path / "first") == 0 and bench.last() == 2
    bench.core = _rotate(bench)
    _report(bench, "a", "b", "c")
    bench.core = _rotate(bench)
    assert _export(bench, tmp_path / "second") == 0
    capsys.readouterr()
    code = _read(bench, tmp_path / "second")
    err = capsys.readouterr().err
    assert (code, err) == (0, ""), (code, err)
