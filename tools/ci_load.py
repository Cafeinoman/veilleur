# SPDX-License-Identifier: EUPL-1.2
"""Watch the load of the CI and fail when it grows too much (ADR-0029, decisions D3 and D16).

Reads the last successful runs of the CI workflow on `main` with the GitHub CLI (`gh run list`, `gh run view --json
jobs`), takes the median duration of the workflow and of each job, and exits with a non-zero code, naming the culprit,
when:

- the workflow takes more than 20 minutes; or
- the `just test` job takes more than twice the longest job of the uv matrix.

Standard library only: the weekly scheduled workflow runs it with the runner's Python and `gh`.

    python tools/ci_load.py [--limit 20]
"""

from __future__ import annotations

import argparse
import json
import statistics
import subprocess
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

WORKFLOW = "ci.yml"
BRANCH = "main"
RUNS = 20
WORKFLOW_LIMIT_SECONDS = 20 * 60
JUST_TEST_RATIO = 2.0
JUST_TEST_JOB = "just test (nix develop)"
MATRIX_PREFIX = "Tests and checks (Python "

Gh = Callable[[Sequence[str]], Any]


class GhError(Exception):
    """The GitHub CLI failed or answered something unreadable."""


@dataclass(frozen=True)
class Report:
    runs: int
    workflow: float
    jobs: dict[str, float]
    problems: list[str]


def gh(arguments: Sequence[str]) -> Any:
    """Run `gh` with `arguments` and return its JSON answer."""
    try:
        done = subprocess.run(["gh", *arguments], capture_output=True, text=True, check=False)
    except OSError as error:
        raise GhError(f"cannot run gh: {error}") from error
    if done.returncode != 0:
        raise GhError(f"gh {arguments[0]} {arguments[1]} failed: {done.stderr.strip()}")
    try:
        return json.loads(done.stdout)
    except json.JSONDecodeError as error:
        raise GhError(f"gh {arguments[0]} {arguments[1]} did not answer JSON") from error


def seconds(start: str, end: str) -> float:
    return (datetime.fromisoformat(end) - datetime.fromisoformat(start)).total_seconds()


def measure(run_gh: Gh, limit: int = RUNS) -> Report:
    runs = run_gh(
        [
            "run", "list",
            "--workflow", WORKFLOW,
            "--branch", BRANCH,
            "--status", "success",
            "--limit", str(limit),
            "--json", "databaseId,startedAt,updatedAt",
        ]
    )  # fmt: skip
    workflow: list[float] = []
    jobs: dict[str, list[float]] = {}
    for run in runs:
        workflow.append(seconds(run["startedAt"], run["updatedAt"]))
        view = run_gh(["run", "view", str(run["databaseId"]), "--json", "jobs"])
        for job in view["jobs"]:
            if job.get("conclusion") == "success" and job.get("startedAt") and job.get("completedAt"):
                jobs.setdefault(job["name"], []).append(seconds(job["startedAt"], job["completedAt"]))
    medians = {name: statistics.median(values) for name, values in sorted(jobs.items())}
    median = statistics.median(workflow) if workflow else 0.0
    return Report(len(runs), median, medians, problems(median, medians))


def problems(workflow: float, jobs: dict[str, float]) -> list[str]:
    found = []
    if workflow > WORKFLOW_LIMIT_SECONDS:
        found.append(f"workflow {WORKFLOW}: median {minutes(workflow)} is above {minutes(WORKFLOW_LIMIT_SECONDS)}")
    matrix = [duration for name, duration in jobs.items() if name.startswith(MATRIX_PREFIX)]
    if JUST_TEST_JOB in jobs and matrix:
        limit = JUST_TEST_RATIO * max(matrix)
        if jobs[JUST_TEST_JOB] > limit:
            found.append(
                f"job {JUST_TEST_JOB!r}: median {minutes(jobs[JUST_TEST_JOB])} is above"
                f" {JUST_TEST_RATIO:g} times the longest matrix job ({minutes(limit)})"
            )
    return found


def minutes(duration: float) -> str:
    whole = round(duration)
    return f"{whole // 60} min {whole % 60:02d} s"


def main(argv: Sequence[str] | None = None, run_gh: Gh = gh) -> int:
    parser = argparse.ArgumentParser(description="Fail when the CI takes too long (ADR-0029).")
    parser.add_argument("--limit", type=int, default=RUNS, help="number of recent successful runs to read")
    options = parser.parse_args(argv)
    try:
        report = measure(run_gh, options.limit)
    except (GhError, KeyError, TypeError, ValueError) as error:
        print(f"ci_load: {error}", file=sys.stderr)
        return 2
    if not report.runs:
        print(f"ci_load: no successful run of {WORKFLOW} on {BRANCH} yet")
        return 0
    print(f"{report.runs} successful runs of {WORKFLOW} on {BRANCH}; median durations:")
    print(f"  workflow: {minutes(report.workflow)}")
    for name, duration in report.jobs.items():
        print(f"  {name}: {minutes(duration)}")
    if JUST_TEST_JOB not in report.jobs:
        print(f"  ({JUST_TEST_JOB!r} has not run yet: its ratio is not checked)")
    for problem in report.problems:
        print(f"ci_load: too slow: {problem}", file=sys.stderr)
    return 1 if report.problems else 0


if __name__ == "__main__":
    sys.exit(main())
