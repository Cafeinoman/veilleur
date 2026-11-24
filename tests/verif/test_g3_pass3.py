# SPDX-License-Identifier: EUPL-1.2
"""Independent check of milestone G3, third pass: the `regex` filter searches with RE2 (spec §10 of 2026-11-18,
user's decision): linear search, no pattern can stall the round; RE2 syntax (no back-references nor look-around,
refused on reception); `\\w`, `\\d`, `\\b` ASCII only, `\\pL` for any letter.

Timed searches run in a child process killed after a few seconds, so that a slow one cannot hang the session.
"""

from __future__ import annotations

import random
import subprocess
import sys
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from tests.server.fakes import World, make_world
from veilleur.adapters.filters import MAX_TEXT, RegexFilter, compile_pattern
from veilleur.core.domain.errors import VeilleurError
from veilleur.core.domain.model import CollectedItem
from veilleur.core.ports.plugins import FilterItem, Plugins
from veilleur.core.services import round
from veilleur.core.services.pairing import create_pairing
from veilleur.core.services.subscriptions import parse_spec, put_subscription


@pytest.fixture
def world(tmp_path: Path) -> Iterator[World]:
    w = make_world(tmp_path / "state")
    yield w
    w.app.close()


def test_the_engine_is_re2() -> None:
    """§10: the engine is RE2 (google-re2), not `re`."""
    compiled = compile_pattern("abc", case=False)
    assert type(compiled).__module__.split(".")[0] == "re2"


# --- linear search: patterns that are catastrophic under `re` are harmless -----------------------------------------

_HOSTILE_UNDER_RE = [
    (r"(.*a){20}", "a" * (MAX_TEXT - 1) + "!"),
    (r"(\w+\s?)+$", "word " * (MAX_TEXT // 5 - 1) + "!"),
    (r"(a|a)*c", "a" * MAX_TEXT),
    (r"(?:a*)*b", "a" * MAX_TEXT),
    (r"^(([a-z])+.)+[A-Z]([a-z])+$", "a" * MAX_TEXT),
    (
        r"^([a-zA-Z0-9])(([\-.]|[_]+)?([a-zA-Z0-9]+))*(@){1}[a-z0-9]+[.]{1}(([a-z]{2,3})|([a-z]{2,3}[.]{1}[a-z]{2,3}))$",
        "a" * MAX_TEXT + "!",
    ),
    (r"(x+x+)+y", "x" * MAX_TEXT),
    (r"\pL*\pL*\pL*\pL*\pL*=", "é" * MAX_TEXT),
]

_TIMED = """
import sys, time
from veilleur.adapters.filters import RegexFilter
from veilleur.core.ports.plugins import FilterItem
pattern, text, case, accents = sys.argv[1], sys.argv[2], sys.argv[3] == "1", sys.argv[4] == "1"
params = {"pattern": pattern, "case_sensitive": case, "accent_sensitive": accents}
assert RegexFilter().check_params(params) is None, "refused"
item = FilterItem("k", {"a": text, "b": [text], "c": {"d": text}}, None)
start = time.monotonic()
RegexFilter().apply(item, params)
print(time.monotonic() - start)
"""


@pytest.mark.parametrize(("case", "accents"), [(False, True), (True, True), (False, False)])
@pytest.mark.parametrize(("pattern", "text"), _HOSTILE_UNDER_RE)
def test_patterns_catastrophic_under_re_are_accepted_and_fast(
    pattern: str, text: str, case: bool, accents: bool
) -> None:
    """§10: accepted (RE2 supports them) and searched on three fields of MAX_TEXT characters well within 5 s."""
    done = subprocess.run(
        [sys.executable, "-c", _TIMED, pattern, text, "1" if case else "0", "1" if accents else "0"],
        capture_output=True, text=True, timeout=5, check=True,
    )  # fmt: skip
    assert float(done.stdout) < 2.0


# --- RE2 syntax: what RE2 does not support is refused on reception, with ValueError only --------------------------


@pytest.mark.parametrize(
    "pattern",
    [r"(a)\1", r"(?P<x>a)(?P=x)", r"a(?=b)", r"a(?!b)", r"(?<=a)b", r"(?<!a)b", r"(?(1)a|b)", r"a++", r"(?>a)"],
)
def test_unsupported_syntax_is_refused_on_reception(world: World, pattern: str) -> None:
    plugins = Plugins(world.app.core.plugins.collectors, {"regex": RegexFilter()}, {})
    filters = [{"name": "regex", "params": {"pattern": pattern}}]
    document = {"collector": "fake", "params": {"topic": "t"}, "filters": filters}
    with pytest.raises(VeilleurError) as caught:
        parse_spec(document, plugins)
    assert caught.value.code == "invalid_params"
    assert caught.value.params == {"path": "filters/0/params/pattern", "keyword": "check"}


@pytest.mark.parametrize("pattern", ["\ud800", "a\udfffb", "[\ud800-\udbff]"])
def test_lone_surrogates_in_a_pattern_are_refused_not_raised(pattern: str) -> None:
    assert RegexFilter().check_params({"pattern": pattern}) == "/pattern"


def test_pattern_length_boundary() -> None:
    assert RegexFilter().check_params({"pattern": "a" * 500}) is None
    assert RegexFilter().check_params({"pattern": "a" * 501}) == "/pattern"


def test_random_patterns_raise_nothing_but_value_error() -> None:
    """Whatever a receiving tool sends, `check_params` answers None or "/pattern" (never an internal exception)."""
    rng = random.Random(20261118)
    alphabet = [*"ab.*+?{}[]()|^$\\-,:=!<>PpLdwsbBzAZ0123456789é中", "{0,1000}", "(?:", "(?P<n>", "\\p{"]
    for _ in range(3000):
        pattern = "".join(rng.choice(alphabet) for _ in range(rng.randint(1, 30)))
        for case in (False, True):
            for accents in (False, True):
                params = {"pattern": pattern, "case_sensitive": case, "accent_sensitive": accents}
                assert RegexFilter().check_params(params) in (None, "/pattern"), pattern


def test_huge_programs_are_refused() -> None:
    """RE2's memory budget refuses patterns whose program would be huge, instead of compiling them."""
    for pattern in [r"(?:a{1000}){1000}", r"(?:.{0,1000}){10}=", r"[\pL\pN]{1000}=", r"(?:\pL{0,1000}){5}"]:
        assert RegexFilter().check_params({"pattern": pattern}) == "/pattern", pattern


# --- documented semantics: \w, \d, \b ASCII only; \pL any letter; case folding --------------------------------------


def test_ascii_classes_and_unicode_letters() -> None:
    assert not compile_pattern(r"^\w+$", case=True).search("été")
    assert compile_pattern(r"^\pL+$", case=True).search("été")
    assert not compile_pattern(r"^\d$", case=True).search("٣")  # ARABIC-INDIC DIGIT THREE
    assert compile_pattern(r"\bvote\b", case=True).search("le vote est")


def test_case_and_accent_options() -> None:
    item = FilterItem("k", {"t": "L'ÉLECTION du Conseil"}, None)
    f = RegexFilter()
    assert f.apply(item, {"pattern": "élection"}) is not None
    assert f.apply(item, {"pattern": "élection", "case_sensitive": True}) is None
    assert f.apply(item, {"pattern": "election", "accent_sensitive": False}) is not None
    assert f.apply(item, {"pattern": "élection", "accent_sensitive": False}) is not None
    assert f.apply(item, {"pattern": "élection", "exclude": True}) is None


# --- §6: nothing of a parameter reaches stderr (RE2 logs errors there by default) ----------------------------------

_QUIET = r"""
from veilleur.adapters.filters import compile_pattern
for p in [r"(a)\1SECRETPARAM", r"(?:a{1000}){1000}SECRETPARAM", r"[SECRETPARAM", r"(?=SECRETPARAM)"]:
    try:
        compile_pattern(p, case=False)
    except ValueError:
        pass
rx = compile_pattern(r"(.{0,1000})(.{0,1000})=SECRETPARAM", case=False)  # exhausts the DFA budget
rx.search("a" * 20000)
"""


def test_nothing_is_written_to_stderr() -> None:
    done = subprocess.run([sys.executable, "-c", _QUIET], capture_output=True, text=True, timeout=60, check=True)
    assert "SECRETPARAM" not in done.stderr + done.stdout
    assert done.stderr == ""


# --- in a round ---------------------------------------------------------------------------------------------------


def test_a_regex_catastrophic_under_re_does_not_stall_the_round(world: World) -> None:
    core = world.app.core
    plugins = Plugins(core.plugins.collectors, {"regex": RegexFilter()}, core.plugins.renderers)
    object.__setattr__(core, "plugins", plugins)
    pairing = create_pairing(core, "desk")
    filters = [{"name": "regex", "params": {"pattern": r"^(\w+\s?)+$"}}]
    document = {"collector": "fake", "params": {"topic": "t"}, "filters": filters, "frequency": "every_round"}
    put_subscription(core, pairing.key_id, "0" * 32, 0, document)
    world.collector.items["t"] = [CollectedItem({"t": "word " * 3_000 + "!"}, key=f"bad{i}") for i in range(20)] + [
        CollectedItem({"t": "two words"}, key="good")
    ]
    start = time.monotonic()
    round.run_round(core)
    assert time.monotonic() - start < 10
    assert set(world.app.store.reported_items(pairing.key_id, "0" * 32)) == {"good"}


# --- hors specification -------------------------------------------------------------------------------------------


@pytest.mark.xfail(
    strict=True,
    reason="hors specification: RegexFilter keeps every compiled pattern for the life of the process "
    "(about 0.25 MB each, several MB once searched); a paired tool replacing its pattern grows memory",
)
def test_the_compiled_pattern_cache_is_bounded() -> None:
    f = RegexFilter()
    for i in range(1_000):
        assert f.check_params({"pattern": f"x{i}"}) is None
    cache: Any = f._compiled
    assert len(cache) < 1_000
