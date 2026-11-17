# SPDX-License-Identifier: EUPL-1.2
"""The `veilleur` command, in both languages."""

from __future__ import annotations

import pytest

from veilleur import __version__
from veilleur.apps.server.cli import main


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
