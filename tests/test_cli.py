# SPDX-License-Identifier: EUPL-1.2
"""The `veilleur` command, in both languages."""

from __future__ import annotations

import os
import re
import subprocess
import sys

import pytest

from veilleur import __version__
from veilleur.apps.server.cli import _language_option, main


def test_version_in_english(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["--lang", "en", "version"]) == 0
    assert capsys.readouterr().out == f"Veilleur {__version__}, watch server under the EUPL-1.2 licence\n"


def test_version_in_french(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["--lang", "fr", "version"]) == 0
    assert capsys.readouterr().out == f"Veilleur {__version__}, serveur de veille sous licence EUPL-1.2\n"


def test_language_from_environment(capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VEILLEUR_LANG", "fr")
    main(["version"])
    assert "serveur de veille" in capsys.readouterr().out


def test_help_is_fully_translated(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit):
        main(["--lang", "fr", "--help"])
    out = capsys.readouterr().out
    assert out.startswith("utilisation : veilleur")
    assert "affiche cette aide et quitte" in out
    assert "options :" in out


def test_errors_are_translated(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exit_info:
        main(["--lang", "fr", "unknown"])
    assert exit_info.value.code == 2
    assert "erreur : argument commande : choix invalide" in capsys.readouterr().err


@pytest.mark.parametrize(
    ("argv", "expected"),
    [
        ([], None),
        (["--lang", "fr"], "fr"),
        (["--lang=fr"], "fr"),
        (["--lan", "fr"], "fr"),
        (["--la=fr", "version"], "fr"),
        (["version", "--lang", "fr"], "fr"),
        (["--lang", "fr", "--lang"], "fr"),
        (["--lang", "fr", "--lang", "xx"], "fr"),
        (["--lang", "fr", "--lang", "en"], "en"),
        (["--lang", "xx"], None),
        (["--", "--lang", "fr"], None),
        (["--l", "fr"], "fr"),
        (["-l", "fr"], None),
        (["--language", "fr"], None),
    ],
)
def test_language_option_scan(argv: list[str], expected: str | None) -> None:
    assert _language_option(argv) == expected


ENGLISH_WORDS = ("usage", "error", "expected", "ignored", "invalid", "unrecognized", "required")


@pytest.mark.parametrize(
    "argv",
    [
        ["--lang", "fr", "--lang"],
        ["--lang", "fr", "--help=x"],
        ["--lang", "fr", "version", "--help=y"],
        ["--lang", "fr", "--lang", "xx"],
        ["--lang", "fr", "unknown"],
        ["--lang", "fr", "version", "extra"],
    ],
)
def test_errors_are_french_in_a_fresh_process(argv: list[str]) -> None:
    # A fresh process: `argparse_i18n.install()` patches `argparse` for the whole process, which would hide
    # errors raised before it runs.
    env = {k: v for k, v in os.environ.items() if k not in ("VEILLEUR_LANG", "LANGUAGE", "LC_ALL", "LC_MESSAGES")}
    env["LANG"] = "en_US.UTF-8"
    result = subprocess.run([sys.executable, "-m", "veilleur", *argv], capture_output=True, text=True, env=env)
    assert result.returncode == 2
    assert result.stderr.startswith("utilisation : veilleur")
    assert " : erreur : " in result.stderr
    assert not [word for word in ENGLISH_WORDS if re.search(rf"\b{word}\b", result.stderr)], result.stderr
