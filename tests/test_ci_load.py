# SPDX-License-Identifier: EUPL-1.2
"""The CI load monitor (tools/ci_load.py) on recorded answers of `gh`, without network (ADR-0029, D16)."""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "tools" / "ci_load.py"
MATRIX_312 = "Tests and checks (Python 3.12)"
MATRIX_313 = "Tests and checks (Python 3.13)"
JUST = "just test (nix develop)"
NIX = "NixOS modules and virtual machine tests"


def load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("ci_load", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


ci_load = load()


def at(second: int) -> str:
    """A GitHub timestamp, `second` seconds after a fixed instant."""
    return f"2026-11-24T{8 + second // 3600:02d}:{second // 60 % 60:02d}:{second % 60:02d}Z"


def job(name: str, duration: int, conclusion: str = "success") -> dict[str, Any]:
    return {"name": name, "conclusion": conclusion, "startedAt": at(3), "completedAt": at(3 + duration)}


def recorded(workflow: Sequence[int], jobs: Sequence[Sequence[dict[str, Any]]]) -> dict[str, Any]:
    """Answers of `gh run list` and `gh run view`, as GitHub gives them."""
    runs = [
        {"databaseId": 1000 + index, "startedAt": at(0), "updatedAt": at(duration)}
        for index, duration in enumerate(workflow)
    ]
    return {"list": runs, "view": {str(1000 + index): {"jobs": list(found)} for index, found in enumerate(jobs)}}


class FakeGh:
    def __init__(self, answers: dict[str, Any]) -> None:
        self.answers = answers
        self.calls: list[list[str]] = []

    def __call__(self, arguments: Sequence[str]) -> Any:
        self.calls.append(list(arguments))
        if list(arguments[:2]) == ["run", "list"]:
            return self.answers["list"]
        assert list(arguments[:2]) == ["run", "view"]
        return self.answers["view"][arguments[2]]


def normal_jobs(just: int = 100) -> list[dict[str, Any]]:
    return [job(MATRIX_312, 60), job(MATRIX_313, 65), job(JUST, just), job(NIX, 240)]


def test_under_the_thresholds_the_exit_code_is_zero(capsys: pytest.CaptureFixture[str]) -> None:
    fake = FakeGh(recorded([250, 260, 240], [normal_jobs()] * 3))
    assert ci_load.main([], fake) == 0
    out = capsys.readouterr()
    assert "workflow: 4 min 10 s" in out.out
    assert f"{JUST}: 1 min 40 s" in out.out
    assert out.err == ""


def test_it_reads_the_successful_runs_of_the_ci_on_main() -> None:
    fake = FakeGh(recorded([250], [normal_jobs()]))
    ci_load.main(["--limit", "7"], fake)
    listing = fake.calls[0]
    assert listing[:2] == ["run", "list"]
    for option, value in (("--workflow", "ci.yml"), ("--branch", "main"), ("--status", "success"), ("--limit", "7")):
        assert listing[listing.index(option) + 1] == value
    assert fake.calls[1] == ["run", "view", "1000", "--json", "jobs"]


def test_a_workflow_above_20_minutes_fails_and_is_named(capsys: pytest.CaptureFixture[str]) -> None:
    fake = FakeGh(recorded([1300, 1250, 100], [normal_jobs()] * 3))
    assert ci_load.main([], fake) == 1
    err = capsys.readouterr().err
    assert "ci.yml" in err
    assert "20 min 50 s" in err


def test_exactly_20_minutes_is_accepted() -> None:
    assert ci_load.main([], FakeGh(recorded([1200], [normal_jobs()]))) == 0


def test_just_test_above_twice_the_longest_matrix_job_fails_and_is_named(capsys: pytest.CaptureFixture[str]) -> None:
    fake = FakeGh(recorded([250, 250, 250], [normal_jobs(just=131)] * 3))
    assert ci_load.main([], fake) == 1
    err = capsys.readouterr().err
    assert JUST in err
    assert "2 min 10 s" in err


def test_just_test_at_twice_the_longest_matrix_job_is_accepted() -> None:
    assert ci_load.main([], FakeGh(recorded([250], [normal_jobs(just=130)]))) == 0


def test_the_median_is_used_not_one_slow_run() -> None:
    fake = FakeGh(recorded([250, 250, 3000], [normal_jobs(), normal_jobs(), normal_jobs(just=900)]))
    assert ci_load.main([], fake) == 0


def test_both_problems_are_reported_together(capsys: pytest.CaptureFixture[str]) -> None:
    assert ci_load.main([], FakeGh(recorded([1500], [normal_jobs(just=500)]))) == 1
    err = capsys.readouterr().err
    assert "ci.yml" in err
    assert JUST in err


def test_failed_and_skipped_jobs_are_not_measured() -> None:
    jobs = [*normal_jobs(), job(JUST, 5000, conclusion="failure"), job(JUST, 5000, conclusion="skipped")]
    assert ci_load.main([], FakeGh(recorded([250], [jobs]))) == 0


def test_before_the_just_test_job_exists_only_the_workflow_is_checked(capsys: pytest.CaptureFixture[str]) -> None:
    jobs = [job(MATRIX_312, 60), job(MATRIX_313, 65), job(NIX, 240)]
    assert ci_load.main([], FakeGh(recorded([250], [jobs]))) == 0
    assert "has not run yet" in capsys.readouterr().out


def test_no_run_yet_is_not_an_alert(capsys: pytest.CaptureFixture[str]) -> None:
    assert ci_load.main([], FakeGh({"list": [], "view": {}})) == 0
    assert "no successful run" in capsys.readouterr().out


def test_an_unreadable_answer_is_an_error(capsys: pytest.CaptureFixture[str]) -> None:
    assert ci_load.main([], FakeGh({"list": [{"databaseId": 1}], "view": {}})) == 2
    assert capsys.readouterr().err.startswith("ci_load:")


@pytest.fixture
def fake_gh_on_path(tmp_path: Path) -> Path:
    """A `gh` executable that answers from recorded files, first on PATH."""
    answers = recorded([1300], [normal_jobs()])
    (tmp_path / "list.json").write_text(json.dumps(answers["list"]), encoding="utf-8")
    (tmp_path / "view.json").write_text(json.dumps(answers["view"]["1000"]), encoding="utf-8")
    fake = tmp_path / "gh"
    fake.write_text(
        f"#!{sys.executable}\n"
        "import pathlib, sys\n"
        "here = pathlib.Path(__file__).parent\n"
        "if sys.argv[1:3] == ['run', 'list']:\n"
        "    print((here / 'list.json').read_text())\n"
        "elif sys.argv[1:3] == ['run', 'view']:\n"
        "    print((here / 'view.json').read_text())\n"
        "else:\n"
        "    sys.exit('unexpected call')\n",
        encoding="utf-8",
    )
    fake.chmod(0o755)
    return tmp_path


def test_the_script_calls_gh_and_fails_with_a_non_zero_code(fake_gh_on_path: Path) -> None:
    environment = {**os.environ, "PATH": f"{fake_gh_on_path}{os.pathsep}{os.environ.get('PATH', '')}"}
    done = subprocess.run(
        [sys.executable, str(SCRIPT)], capture_output=True, text=True, env=environment, check=False, timeout=60
    )
    assert done.returncode == 1
    assert "ci.yml" in done.stderr


def test_a_failing_gh_is_an_error(tmp_path: Path) -> None:
    fake = tmp_path / "gh"
    fake.write_text(f"#!{sys.executable}\nimport sys\nsys.exit('HTTP 403')\n", encoding="utf-8")
    fake.chmod(0o755)
    environment = {**os.environ, "PATH": f"{tmp_path}{os.pathsep}{os.environ.get('PATH', '')}"}
    done = subprocess.run(
        [sys.executable, str(SCRIPT)], capture_output=True, text=True, env=environment, check=False, timeout=60
    )
    assert done.returncode == 2
    assert "HTTP 403" in done.stderr


def test_the_script_uses_the_standard_library_only() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    imported = {
        line.split()[1].split(".")[0]
        for line in source.splitlines()
        if line.startswith(("import ", "from ")) and not line.startswith("from __future__")
    }
    assert imported <= set(sys.stdlib_module_names)


def test_the_weekly_workflow_runs_the_script_with_the_right_to_read_actions_only() -> None:
    workflow = (ROOT / ".github" / "workflows" / "ci-load.yml").read_text(encoding="utf-8")
    assert "schedule:" in workflow
    assert "run: python3 tools/ci_load.py" in workflow
    granted = workflow.split("\npermissions:\n", 1)[1].split("\n\n", 1)[0]
    assert granted.strip() == "actions: read"
    assert workflow.count("permissions:") == 1
