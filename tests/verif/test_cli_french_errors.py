# SPDX-License-Identifier: EUPL-1.2
"""Independent check: with --lang fr, help and errors are entirely French, even in a fresh process."""

from __future__ import annotations

import io
import itertools
import os
import random
import subprocess
import sys
from contextlib import redirect_stderr, redirect_stdout

import pytest

from veilleur import i18n
from veilleur.apps.server.cli import _language_option, build_parser

ENGLISH = ("usage:", "error:", "expected", "ignored explicit", "invalid choice", "unrecognized", "choose from")


def _run(argv: list[str], lang_env: str = "en_US.UTF-8") -> subprocess.CompletedProcess[str]:
    env = {k: v for k, v in os.environ.items() if k not in ("VEILLEUR_LANG", "LANGUAGE", "LC_ALL", "LC_MESSAGES")}
    env["LANG"] = lang_env
    return subprocess.run([sys.executable, "-m", "veilleur", *argv], capture_output=True, text=True, env=env)


@pytest.mark.parametrize("argv", [
    ["--lang", "fr", "--lang"], ["--lang", "fr", "--help=x"], ["--lang", "fr", "version", "--help=y"],
    ["--lang", "fr", "--lang", "xx"], ["--la=fr", "unknown"], ["--lang", "fr", "version", "extra"],
    ["--lang", "fr", "--bogus"],
])
def test_errors_fully_french_in_fresh_process(argv: list[str]) -> None:
    r = _run(argv)
    assert r.returncode == 2
    assert r.stderr.startswith("utilisation : veilleur")
    assert not [w for w in ENGLISH if w in r.stderr], r.stderr


def test_system_french_without_value_is_french() -> None:
    r = _run(["--lang"], lang_env="fr_FR.UTF-8")
    assert r.returncode == 2
    assert "erreur : argument --lang : un argument attendu" in r.stderr


def test_language_scan_agrees_with_argparse() -> None:
    i18n.setup("en")
    alphabet = ["--lang", "--la", "--l", "--lan", "fr", "en", "xx", "version", "--", "--lang=fr", "--la=en",
                "--lang=", "x=y"]
    rng = random.Random(0)
    seqs = itertools.chain((list(p) for n in range(4) for p in itertools.product(alphabet, repeat=n)),
                           ([rng.choice(alphabet) for _ in range(rng.randint(4, 7))] for _ in range(20000)))
    parsed, mismatches = 0, []
    for argv in seqs:
        try:
            with redirect_stderr(io.StringIO()), redirect_stdout(io.StringIO()):
                ns = build_parser().parse_args(argv)
        except SystemExit:
            continue
        parsed += 1
        if ns.lang != _language_option(argv):
            mismatches.append(argv)
    assert parsed > 50
    assert not mismatches, mismatches[:10]
