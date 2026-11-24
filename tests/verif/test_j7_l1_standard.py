# SPDX-License-Identifier: EUPL-1.2
"""Verifier of lot J7-L1 (docs/PLAN.md): justfile, CI job, CI load monitor, CLAUDE.md, pilot documents.

Written from the plan, ADR-0029 and decisions D3, D4, D6, D16 only. No network: `gh` and `uv` are replaced by
recorded answers or fake executables.
"""

from __future__ import annotations

import importlib.util
import os
import re
import shutil
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[2]
JUSTFILE = ROOT / "justfile"
CI = ROOT / ".github" / "workflows" / "ci.yml"
CI_LOAD = ROOT / ".github" / "workflows" / "ci-load.yml"
SCRIPT = ROOT / "tools" / "ci_load.py"

SIX_COMMANDS = [
    "uv run --locked pytest",
    "uv run --locked ruff check src tests tools protocol receiver",
    "uv run --locked mypy",
    "uv run --locked lint-imports",
    "uv run --locked python tools/check_vectors.py",
    "uv run --locked python tools/protocol_vectors.py --check",
]

needs_just = pytest.mark.skipif(shutil.which("just") is None, reason="just is only in the Nix development shell")


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


# Step 1 and criteria 1, 2: the justfile.


@needs_just
def test_the_dry_run_shows_the_six_commands_in_order() -> None:
    done = subprocess.run(
        ["just", "--justfile", str(JUSTFILE), "--working-directory", str(ROOT), "--dry-run", "test"],
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )
    assert done.returncode == 0, done.stderr
    shown = [line.strip() for line in (done.stdout + done.stderr).splitlines() if line.strip()]
    assert shown == SIX_COMMANDS


def fake_uv(directory: Path, failing: str | None) -> Path:
    """A `uv` that logs its arguments and fails when they contain `failing`."""
    log = directory / "calls.log"
    script = directory / "uv"
    script.write_text(
        f"#!{sys.executable}\n"
        "import sys\n"
        f"with open({str(log)!r}, 'a', encoding='utf-8') as handle:\n"
        "    handle.write(' '.join(sys.argv[1:]) + '\\n')\n"
        f"sys.exit(3 if {failing!r} is not None and {failing!r} in ' '.join(sys.argv[1:]) else 0)\n",
        encoding="utf-8",
    )
    script.chmod(0o755)
    return log


def run_just_test(tmp_path: Path, failing: str | None) -> tuple[int, list[str]]:
    bin_directory = tmp_path / "bin"
    bin_directory.mkdir()
    log = fake_uv(bin_directory, failing)
    work = tmp_path / "work"
    work.mkdir()
    environment = {**os.environ, "PATH": f"{bin_directory}{os.pathsep}{os.environ.get('PATH', '')}"}
    done = subprocess.run(
        ["just", "--justfile", str(JUSTFILE), "--working-directory", str(work), "test"],
        capture_output=True,
        text=True,
        env=environment,
        check=False,
        timeout=60,
    )
    calls = log.read_text(encoding="utf-8").splitlines() if log.exists() else []
    return done.returncode, calls


@needs_just
def test_every_check_passing_gives_a_zero_code(tmp_path: Path) -> None:
    code, calls = run_just_test(tmp_path, None)
    assert code == 0
    assert ["uv " + call for call in calls] == SIX_COMMANDS


@needs_just
@pytest.mark.parametrize("failing", ["ruff check", "pytest", "mypy", "lint-imports", "check_vectors", "--check"])
def test_a_failing_check_fails_just_test(tmp_path: Path, failing: str) -> None:
    code, calls = run_just_test(tmp_path, failing)
    assert code != 0
    assert failing in calls[-1]


def test_no_env_recipes_and_the_other_recipes_are_there() -> None:
    text = read(JUSTFILE)
    recipes = set(re.findall(r"^([\w-]+)\s*:", text, flags=re.MULTILINE))
    assert {"test", "fmt", "vm", "ci-load"} <= recipes
    assert not {"env-up", "env-down"} & recipes
    fmt = text.split("\nfmt:", 1)[1].split("\n\n", 1)[0]
    assert fmt.index("ruff format") < fmt.index("ruff check --fix")
    vm = text.split("\nvm:", 1)[1].split("\n\n", 1)[0]
    assert "nix flake check -L" in vm


# Step 2: just in the development shell.


def test_just_is_in_the_default_development_shell() -> None:
    flake = read(ROOT / "flake.nix")
    shell = flake.split("devShells", 1)[1].split("checks.", 1)[0]
    assert re.search(r"packages\s*=\s*\[[^\]]*pkgs\.just\b", shell)


# Step 3 and criterion 3: the CI.


def test_the_ci_has_a_just_test_job_and_keeps_the_former_names() -> None:
    text = read(CI)
    assert "run: nix develop -c just test" in text
    names = re.findall(r"^    name: (.+)$", text, flags=re.MULTILINE)
    assert "Tests and checks (Python ${{ matrix.python }})" in names
    assert "NixOS modules and virtual machine tests" in names
    assert 'python: ["3.12", "3.13"]' in text


def test_the_monitor_knows_the_real_job_names_of_the_ci() -> None:
    """If a job of ci.yml is renamed, the monitor must not silently stop checking the ratio (D16)."""
    module = load_ci_load()
    names = re.findall(r"^    name: (.+)$", read(CI), flags=re.MULTILINE)
    assert module.JUST_TEST_JOB in names
    matrix = [name for name in names if "${{ matrix.python }}" in name]
    assert len(matrix) == 1
    assert matrix[0].replace("${{ matrix.python }})", "").startswith(module.MATRIX_PREFIX)
    assert CI.name == module.WORKFLOW


# Step 4 and criterion 8: the scheduled workflow.


def test_the_weekly_workflow_is_weekly_pinned_and_reads_actions_only() -> None:
    text = read(CI_LOAD)
    cron = re.search(r'cron:\s*"([^"]+)"', text)
    assert cron is not None
    _minute, _hour, day, month, weekday = cron.group(1).split()
    assert (day, month) == ("*", "*")
    assert re.fullmatch(r"[0-6]", weekday)
    assert re.findall(r"^[ \t]*permissions:", text, flags=re.MULTILINE) == ["permissions:"]
    assert re.findall(r"^  (\w[\w-]*): (\w+)$", text.split("\npermissions:\n", 1)[1].split("\n\n", 1)[0], re.M) == [
        ("actions", "read")
    ]
    used = re.findall(r"uses:\s*(\S+)", text)
    assert used
    assert all(re.fullmatch(r"[\w.-]+/[\w./-]+@[0-9a-f]{40}", action) for action in used)
    assert "tools/ci_load.py" in text
    assert "secrets." not in text


# Step 4: tools/ci_load.py on recorded answers.


def load_ci_load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("ci_load_verif", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def stamp(second: int) -> str:
    return f"2026-11-23T{6 + second // 3600:02d}:{second // 60 % 60:02d}:{second % 60:02d}Z"


class Recorded:
    def __init__(self, runs: Sequence[tuple[int, list[tuple[str, int, str]]]]) -> None:
        self.calls: list[list[str]] = []
        self.list = [
            {"databaseId": 500 + index, "startedAt": stamp(0), "updatedAt": stamp(total), "conclusion": "success"}
            for index, (total, _) in enumerate(runs)
        ]
        self.views = {
            str(500 + index): {
                "jobs": [
                    {"name": name, "conclusion": conclusion, "startedAt": stamp(1), "completedAt": stamp(1 + length)}
                    for name, length, conclusion in jobs
                ]
            }
            for index, (_, jobs) in enumerate(runs)
        }

    def __call__(self, arguments: Sequence[str]) -> Any:
        self.calls.append(list(arguments))
        if list(arguments[:2]) == ["run", "list"]:
            return self.list
        return self.views[arguments[2]]


MATRIX = [("Tests and checks (Python 3.12)", 300, "success"), ("Tests and checks (Python 3.13)", 320, "success")]
NIX = ("NixOS modules and virtual machine tests", 600, "success")


def test_by_default_the_last_20_runs_of_main_are_read() -> None:
    module = load_ci_load()
    fake = Recorded([(700, [*MATRIX, ("just test (nix develop)", 400, "success"), NIX])])
    assert module.main([], fake) == 0
    listing = fake.calls[0]
    assert listing[listing.index("--limit") + 1] == "20"
    assert listing[listing.index("--branch") + 1] == "main"


def test_the_ratio_compares_with_the_longest_matrix_job_not_the_nix_job() -> None:
    module = load_ci_load()
    # 2 x 320 s = 640 s: 700 s is beyond, even though the Nix job takes 600 s.
    fake = Recorded([(900, [*MATRIX, ("just test (nix develop)", 700, "success"), NIX])])
    assert module.main([], fake) == 1


def test_one_second_above_20_minutes_fails() -> None:
    module = load_ci_load()
    assert module.main([], Recorded([(1201, [*MATRIX, NIX])])) == 1


@pytest.mark.xfail(
    strict=True,
    reason="minor: above 20 minutes the alert names the workflow, not the job in cause (ADR-0029); "
    "stdout lists every job's median",
)
def test_a_workflow_above_20_minutes_names_the_job_in_cause(capsys: pytest.CaptureFixture[str]) -> None:
    module = load_ci_load()
    slow_nix = ("NixOS modules and virtual machine tests", 1250, "success")
    assert module.main([], Recorded([(1300, [*MATRIX, ("just test (nix develop)", 400, "success"), slow_nix])])) == 1
    assert "NixOS modules and virtual machine tests" in capsys.readouterr().err


@pytest.mark.xfail(
    strict=True,
    reason="minor: only successful runs are read (ADR-0029 says the last 20 runs); runs that time out are never "
    "counted, so a CI slow enough to time out raises no alert",
)
def test_runs_that_timed_out_still_count() -> None:
    module = load_ci_load()
    fake = Recorded([(3600, [*MATRIX, ("just test (nix develop)", 3600, "cancelled"), NIX])])
    fake.list[0]["conclusion"] = "failure"

    def without_status_filter(arguments: Sequence[str]) -> Any:
        if list(arguments[:2]) == ["run", "list"] and "--status" in arguments:
            return []  # GitHub answers no successful run: every recent run failed.
        return fake(arguments)

    assert module.main([], without_status_filter) != 0


def test_the_job_name_is_in_the_alert_and_no_token_is_printed(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GH_TOKEN", "ghs_verifierSecretValue0000")
    module = load_ci_load()
    assert module.main([], Recorded([(700, [*MATRIX, ("just test (nix develop)", 641, "success"), NIX])])) == 1
    captured = capsys.readouterr()
    assert "just test (nix develop)" in captured.err
    assert "ghs_verifierSecretValue0000" not in captured.out + captured.err


def test_a_missing_gh_is_an_error_not_a_success(tmp_path: Path) -> None:
    environment = {**os.environ, "PATH": str(tmp_path)}
    done = subprocess.run(
        [sys.executable, str(SCRIPT)], capture_output=True, text=True, env=environment, check=False, timeout=60
    )
    assert done.returncode not in (0, 1)
    assert "gh" in done.stderr


# Step 5 and criterion 4: CLAUDE.md.


def table_rows(text: str) -> list[str]:
    return [
        re.sub(r"\s+", " ", line.strip())
        for line in text.splitlines()
        if line.strip().startswith("| ") and "Read" in line
    ]


def test_claude_md_names_the_documents_the_command_and_the_lot_rule() -> None:
    text = read(ROOT / "CLAUDE.md")
    authority = text.split("## Documents qui font foi", 1)[1].split("\n## ", 1)[0]
    for document in ("`docs/PLAN.md`", "`docs/SPEC.md`", "`docs/adr/`"):
        assert document in authority
    first_paragraph = authority.split("\n\n")[1]
    assert "cahier_des_charges.MD" not in first_paragraph
    assert "plan.md`" not in first_paragraph
    assert "just test" in text
    assert "J<n>-L<m>" in text
    assert "claude/<identifiant>-<sujet>" in text
    assert "docs/DECISIONS.md" in text
    assert "v0.2.0" in text


def test_claude_md_keeps_the_token_table_of_the_former_plan() -> None:
    former = [row.replace("(`gh run watch`, `gh pr checks`)", "") for row in table_rows(read(ROOT / "plan.md"))]
    current = [re.sub(r"\(`gh run watch`.*?\)", "", row) for row in table_rows(read(ROOT / "CLAUDE.md"))]
    for right in ("Contents", "Pull requests", "Workflows", "Actions", "Commit statuses", "Administration", "Metadata"):
        assert [row for row in former if row.startswith(f"| {right} |")] == [
            row for row in current if row.startswith(f"| {right} |")
        ], right


# Step 7: the contributing guides.


@pytest.mark.parametrize("guide", ["CONTRIBUTING.md", "CONTRIBUTING.fr.md"])
def test_the_guides_cite_just_test_and_check_vectors(guide: str) -> None:
    text = read(ROOT / guide)
    assert "just test" in text
    assert "tools/check_vectors.py" in text


# Step 8: the correspondence table against the former specification (TEST-STRATEGY section 4).


def test_every_identifier_of_the_former_specification_is_in_the_correspondence_table() -> None:
    requirement = re.compile(r"\b(?:EF|ES|ENF)-\d{2}[a-z]?\b")
    former = set(requirement.findall(read(ROOT / "cahier_des_charges.MD")))
    takeover = read(ROOT / "docs" / "REPRISE.md")
    table = takeover[takeover.index("### 2.2 ") : takeover.index("### 2.6 ")]
    column = {
        identifier
        for line in table.splitlines()
        if line.startswith("|")
        for identifier in requirement.findall(line.split("|")[1])
    }
    assert former
    assert former <= column
