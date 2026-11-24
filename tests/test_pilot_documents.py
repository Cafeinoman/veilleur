# SPDX-License-Identifier: EUPL-1.2
"""The pilot documents agree with each other (docs/TEST-STRATEGY.md, section 4).

Nothing of the former pilot documents disappears without a destination: every requirement identifier lands in the
specification, every cited ADR exists with a status, every reservation is a row of the plan, every strict `xfail` of
`tests/verif/` is tied to a reservation, and every lot of the plan follows the template. Each check is a function of
the texts, run on the real documents, then on altered copies to show that it notices a removal.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"
REQUIREMENT = re.compile(r"\b(?:EF|ES|ENF)-\d{2}[a-z]?\b")
ADR = re.compile(r"\bADR-(\d{4})\b")
RESERVATION = re.compile(r"\bR\d{2}\b")
LOT = re.compile(r"^### (J\d+-L\d+)\b", re.MULTILINE)
STATUS = re.compile(r"^- \*\*Statut :\*\* (Proposé|Accepté|Rejeté)\b", re.MULTILINE)
RUBRICS = ("Objectif.", "Critères d'acceptation.", "Références.", "Effort.", "Statut.")
LOT_STATUS = re.compile(r"^- \*\*Statut\.\*\* (à faire|fait)\b", re.MULTILINE)


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def section(text: str, start: str, end: str | None) -> str:
    """The text from the heading `start` to the heading `end` (or to the next heading of the same level)."""
    begin = text.index(start)
    if end is not None:
        return text[begin : text.index(end, begin)]
    level = start.split(" ", 1)[0]
    following = re.search(rf"^{level} ", text[begin + len(start) :], flags=re.MULTILINE)
    return text[begin:] if following is None else text[begin : begin + len(start) + following.start()]


def former_requirements(takeover: str) -> set[str]:
    """Identifiers of the column « Ancien » of the correspondence table, sections 2.2 to 2.5."""
    table = section(takeover, "### 2.2 ", "### 2.6 ")
    cells = [line.split("|")[1] for line in table.splitlines() if line.startswith("|")]
    return {identifier for cell in cells for identifier in REQUIREMENT.findall(cell)}


def missing_requirements(identifiers: set[str], specification: str) -> list[str]:
    present = set(REQUIREMENT.findall(specification))
    return sorted(identifiers - present)


def missing_adr_files(texts: list[str], adr_directory: Path) -> list[str]:
    cited = {number for text in texts for number in ADR.findall(text)}
    return sorted(f"ADR-{n}" for n in cited if not list(adr_directory.glob(f"{n}-*.md")))


def adr_without_status(adr_directory: Path) -> list[str]:
    return sorted(path.name for path in adr_directory.glob("*.md") if not STATUS.search(read(path)))


def reservations_section(plan: str) -> str:
    return section(plan, "## Réserves", None)


def reservation_rows(plan: str) -> set[str]:
    rows = (line.split("|")[1].strip() for line in reservations_section(plan).splitlines() if line.startswith("|"))
    return {row for row in rows if RESERVATION.fullmatch(row)}


def missing_reservations(takeover: str, plan: str) -> list[str]:
    return sorted(set(RESERVATION.findall(takeover)) - reservation_rows(plan))


def is_xfail(decorator: ast.expr) -> bool:
    target = decorator.func if isinstance(decorator, ast.Call) else decorator
    return isinstance(target, ast.Attribute) and target.attr == "xfail"


def xfail_tests(directory: Path) -> set[str]:
    names = set()
    for path in directory.rglob("*.py"):
        for node in ast.walk(ast.parse(read(path))):
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef) and any(map(is_xfail, node.decorator_list)):
                names.add(node.name)
    return names


def unreserved_xfails(names: set[str], plan: str) -> list[str]:
    reserved = reservations_section(plan)
    return sorted(name for name in names if not re.search(rf"\b{re.escape(name)}\b", reserved))


def lot_problems(plan: str) -> list[str]:
    problems = []
    matches = list(LOT.finditer(plan))
    identifiers = [match.group(1) for match in matches]
    problems += [
        f"{identifier}: not unique" for identifier in sorted(set(identifiers)) if identifiers.count(identifier) > 1
    ]
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else plan.find("\n## ", match.end())
        body = plan[match.start() : end if end != -1 else len(plan)]
        body = body.split("\n## ", 1)[0]
        problems += [f"{match.group(1)}: no {rubric}" for rubric in RUBRICS if f"- **{rubric}**" not in body]
        if f"- **{RUBRICS[-1]}**" in body and not LOT_STATUS.search(body):
            problems.append(f"{match.group(1)}: status is neither « à faire » nor « fait »")
    return problems


TAKEOVER = read(DOCS / "REPRISE.md")
SPECIFICATION = read(DOCS / "SPEC.md")
PLAN = read(DOCS / "PLAN.md")


# The real documents.


def test_the_correspondence_table_lists_requirements() -> None:
    found = former_requirements(TAKEOVER)
    assert {"EF-01", "ES-13", "ENF-03b"} <= found
    assert len(found) >= 50


def test_every_former_requirement_is_in_the_specification() -> None:
    assert missing_requirements(former_requirements(TAKEOVER), SPECIFICATION) == []


def test_every_requirement_of_the_former_specification_is_in_the_new_one() -> None:
    former = ROOT / "docs" / "REPRISE.md"
    identifiers = set(REQUIREMENT.findall(read(former)))
    assert identifiers
    assert missing_requirements(identifiers, SPECIFICATION) == []


def test_every_cited_adr_has_its_file() -> None:
    assert missing_adr_files([SPECIFICATION, TAKEOVER, PLAN], DOCS / "adr") == []


def test_every_adr_has_a_status() -> None:
    assert list((DOCS / "adr").glob("*.md"))
    assert adr_without_status(DOCS / "adr") == []


def test_every_reservation_of_the_takeover_is_a_row_of_the_plan() -> None:
    assert len(reservation_rows(PLAN)) >= 26
    assert missing_reservations(TAKEOVER, PLAN) == []


def test_every_xfail_of_the_verifier_is_tied_to_a_reservation() -> None:
    names = xfail_tests(ROOT / "tests" / "verif")
    assert names
    assert unreserved_xfails(names, PLAN) == []


def test_every_lot_follows_the_template() -> None:
    assert len(LOT.findall(PLAN)) >= 27
    assert lot_problems(PLAN) == []


# Altered copies: each check notices a removal.


@pytest.mark.parametrize("identifier", ["EF-06", "ES-13", "ENF-03b"])
def test_a_requirement_removed_from_the_specification_is_noticed(identifier: str) -> None:
    altered = re.sub(rf"\b{identifier}\b", "XX-00", SPECIFICATION)
    assert identifier in missing_requirements(former_requirements(TAKEOVER), altered)


def test_a_cited_adr_without_its_file_is_noticed(tmp_path: Path) -> None:
    for path in (DOCS / "adr").glob("*.md"):
        if not path.name.startswith("0022-"):
            (tmp_path / path.name).write_text(read(path), encoding="utf-8")
    assert missing_adr_files([SPECIFICATION, TAKEOVER, PLAN], tmp_path) == ["ADR-0022"]


def test_an_adr_without_a_known_status_is_noticed(tmp_path: Path) -> None:
    (tmp_path / "0001-example.md").write_text("# ADR-0001\n\n- **Statut :** En discussion\n", encoding="utf-8")
    (tmp_path / "0002-example.md").write_text("# ADR-0002\n\n- **Statut :** Rejeté\n", encoding="utf-8")
    assert adr_without_status(tmp_path) == ["0001-example.md"]


def test_a_reservation_removed_from_the_plan_is_noticed() -> None:
    altered = re.sub(r"^\| R07 \|.*\n", "", PLAN, flags=re.MULTILINE)
    assert missing_reservations(TAKEOVER, altered) == ["R07"]


def test_a_reservation_cited_only_outside_the_table_is_noticed() -> None:
    altered = re.sub(r"^\| R07 \|", "| R7x |", PLAN, flags=re.MULTILINE) + "\nR07 cited in passing.\n"
    assert missing_reservations(TAKEOVER, altered) == ["R07"]


def test_an_xfail_cited_in_no_reservation_is_noticed(tmp_path: Path) -> None:
    (tmp_path / "test_example.py").write_text(
        "import pytest\n\n\n"
        "@pytest.mark.xfail(strict=True, reason='example')\n"
        "def test_not_reserved_anywhere() -> None:\n    assert False\n\n\n"
        "@pytest.mark.xfail\n"
        "def test_the_unit_that_draws_the_tokens_is_hardened() -> None:\n    assert False\n\n\n"
        "def test_without_marker() -> None:\n    pass\n",
        encoding="utf-8",
    )
    names = xfail_tests(tmp_path)
    assert names == {"test_not_reserved_anywhere", "test_the_unit_that_draws_the_tokens_is_hardened"}
    assert unreserved_xfails(names, PLAN) == ["test_not_reserved_anywhere"]


def test_an_xfail_named_outside_the_reservations_is_noticed() -> None:
    name = "test_the_unit_that_draws_the_tokens_is_hardened"
    altered = PLAN.replace(f"`test_g5_verif.py::{name}`", "aucun") + f"\n\n## Annexe\n\n{name}\n"
    assert unreserved_xfails({name}, altered) == [name]


def test_a_lot_without_a_rubric_is_noticed() -> None:
    lot = section(PLAN, "### J8-L2 ", None)
    altered = PLAN.replace(lot, lot.replace("- **Effort.**", "- Effort :"))
    assert lot_problems(altered) == ["J8-L2: no Effort."]


def test_a_lot_with_another_status_is_noticed() -> None:
    lot = section(PLAN, "### J8-L2 ", None)
    altered = PLAN.replace(lot, lot.replace("- **Statut.** à faire", "- **Statut.** en cours"))
    assert lot_problems(altered) == ["J8-L2: status is neither « à faire » nor « fait »"]


def test_a_lot_identifier_used_twice_is_noticed() -> None:
    altered = PLAN.replace("### J8-L3 ", "### J8-L2 ", 1)
    assert "J8-L2: not unique" in lot_problems(altered)
