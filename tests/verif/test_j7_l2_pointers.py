# SPDX-License-Identifier: EUPL-1.2
"""Independent check of lot J7-L2 (docs/PLAN.md): the former pilot documents become pointers, nothing is lost.

Written from the acceptance criteria of J7-L2 and decision D17 of docs/DECISIONS.md. The checks that compare with
commits c576de4 and c307a5c need the git history; they are skipped on a shallow clone (the CI checks out one commit).
"""

from __future__ import annotations

import ast
import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
REQUIREMENT = re.compile(r"\b(?:EF|ES|ENF)-\d{2}[a-z]?\b")
# The word is split so that this file passes criterion 4 itself.
WORD = "ca" + "hier"
FORMER_SPEC = f"{WORD}_des_charges.MD"
BASE = "c576de4"  # main when the lot started; the former documents are whole there.
END = "c307a5c"  # last commit of the lot; later lots may change the tests freely.


def read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def git(*args: str) -> str | None:
    try:
        done = subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, check=False, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return None
    return done.stdout if done.returncode == 0 else None


def at_base(path: str) -> str:
    text = git("show", f"{BASE}:{path}")
    if text is None:
        pytest.skip(f"commit {BASE} is not in this clone")
    return text


# Criterion 1 and step 1.


@pytest.mark.parametrize("pointer", [FORMER_SPEC, "plan.md"])
def test_the_former_documents_are_short_pointers(pointer: str) -> None:
    text = read(pointer)
    assert len(text.splitlines()) < 15
    for target in ("docs/SPEC.md", "docs/PLAN.md", "docs/adr/", "docs/REPRISE.md"):
        assert target in text, target
    # A pointer, not a copy: no requirement is restated in it.
    assert not REQUIREMENT.search(text)


# Criterion 4.


def test_no_former_word_left_in_code_tests_and_public_docs() -> None:
    hits = []
    for folder in ("src", "tests", "tools", "protocol", "receiver", "deploy", "docs/en", "docs/fr"):
        for path in (ROOT / folder).rglob("*"):
            if not path.is_file() or any(part in {"__pycache__", ".venv"} for part in path.parts):
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue
            hits += [
                f"{path.relative_to(ROOT)}:{n}" for n, line in enumerate(text.splitlines(), 1) if WORD in line.lower()
            ]
    assert hits == []


# Criterion 5 and step 3.


def _introduction(text: str) -> str:
    return text.split("\n## ", 1)[0]


@pytest.mark.parametrize(
    ("path", "future", "today"),
    [
        ("docs/en/design.md", r"\bwill be\b", r"exists? today"),
        ("docs/fr/design.md", r"\bsera\b", r"existen?t? aujourd'hui"),
    ],
)
def test_the_design_introduction_describes_the_published_version(path: str, future: str, today: str) -> None:
    text = read(path)
    intro = _introduction(text)
    assert not re.search(future, intro, flags=re.IGNORECASE)
    assert not re.search(today, text, flags=re.IGNORECASE)
    assert "0.1.0" in intro
    assert "docs/SPEC.md" in intro


@pytest.mark.parametrize("path", ["docs/en/design.md", "docs/fr/design.md"])
def test_the_roadmap_points_to_the_plan_after_g6(path: str) -> None:
    rows = [line for line in read(path).splitlines() if line.startswith("| ")]
    g6 = next(i for i, row in enumerate(rows) if row.startswith("| G6 |"))
    assert any("docs/PLAN.md" in row for row in rows[g6 + 1 :])


# Step 5: docs/REPRISE.md is the frozen reference; it must carry every identifier of the former specification.


def test_the_takeover_table_carries_every_former_identifier() -> None:
    former = set(REQUIREMENT.findall(at_base(FORMER_SPEC)))
    assert len(former) == 57
    assert former - set(REQUIREMENT.findall(read("docs/REPRISE.md"))) == set()


# Decision D17: the frozen constants of test_j7_l1_standard.py are the former content, not a weaker copy.


def test_the_frozen_identifiers_are_those_of_the_former_specification() -> None:
    from tests.verif import test_j7_l1_standard as l1

    former = set(REQUIREMENT.findall(at_base(FORMER_SPEC)))
    assert set(REQUIREMENT.findall(l1.FORMER_SPECIFICATION_TEXT)) == former


def test_the_frozen_token_table_is_that_of_the_former_plan() -> None:
    from tests.verif import test_j7_l1_standard as l1

    rows = [
        re.sub(r"\s+", " ", line.strip())
        for line in at_base("plan.md").splitlines()
        if line.strip().startswith("| ") and "Read" in line
    ]
    assert rows == l1.FORMER_PLAN_TOKEN_ROWS


# Criterion 3, with the exemptions of D17: apart from docstrings and comments, the tests changed only where expected.

# Textual substitutions that turn the code at the base into the code of the lot, file by file. Anything else that
# changed outside docstrings and comments makes the ASTs differ.
ALLOWED = {
    "tests/verif/test_design_follows_spec.py": [(f'(ROOT / "{FORMER_SPEC}")', '(ROOT / "docs/SPEC.md")')],
    "tests/verif/test_g6_release.py": [
        (
            f'read("{FORMER_SPEC}").split("## 10. Décisions", 1)',
            'read("docs/adr/0021-publication-et-distribution.md").split("## Décision", 1)',
        )
    ],
    "tests/test_pilot_documents.py": [(f'ROOT / "{FORMER_SPEC}"', 'ROOT / "docs" / "REPRISE.md"')],
    "tests/verif/test_g4_verif_pass3.py": [(f"({WORD} §10,", "(spec §10,")],
    "tests/verif/test_g5_pass2.py": [(f"{WORD} section 10", "spec section 10")],
}
# Rewritten under D17; checked above against the former documents.
EXEMPT = {"tests/verif/test_j7_l1_standard.py"}


class _StripDocstrings(ast.NodeTransformer):
    def _strip(self, node: ast.AST) -> ast.AST:
        self.generic_visit(node)
        body: list[ast.stmt] = getattr(node, "body", [])
        first = body[0] if body else None
        if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) and isinstance(first.value.value, str):
            setattr(node, "body", body[1:] or [ast.Pass()])  # noqa: B010
        return node

    visit_Module = visit_FunctionDef = visit_AsyncFunctionDef = visit_ClassDef = _strip


def _shape(source: str) -> str:
    return ast.dump(_StripDocstrings().visit(ast.parse(source)))


def test_tests_changed_only_in_docstrings_comments_and_the_redirected_paths() -> None:
    for commit in (BASE, END):
        if git("rev-parse", "--verify", "--quiet", f"{commit}^{{commit}}") is None:
            pytest.skip(f"commit {commit} is not in this clone")
    changed = git("diff", "--name-only", f"{BASE}...{END}", "--", "tests")
    assert changed is not None
    unexpected = []
    for path in changed.split():
        if not path.endswith(".py") or path in EXEMPT or Path(path).name.startswith("test_j7_l2_"):
            continue
        before = git("show", f"{BASE}:{path}")
        if before is None:  # new file
            unexpected.append(f"{path}: new")
            continue
        for old, new in ALLOWED.get(path, []):
            assert old in before, (path, old)
            before = before.replace(old, new)
        after = git("show", f"{END}:{path}")
        assert after is not None, path
        if _shape(before) != _shape(after):
            unexpected.append(path)
    assert unexpected == []
