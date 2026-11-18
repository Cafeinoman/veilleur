# SPDX-License-Identifier: EUPL-1.2
"""Repository rules: licence header in every source file, same documentation in both languages."""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

import veilleur_receive

ROOT = Path(__file__).resolve().parent.parent
SPDX = "# SPDX-License-Identifier: EUPL-1.2"


def test_every_python_file_has_the_licence_header() -> None:
    files = [p for d in ("src", "tests", "tools", "protocol", "receiver") for p in (ROOT / d).rglob("*.py")]
    assert files
    missing = [str(p.relative_to(ROOT)) for p in files if not p.read_text(encoding="utf-8").startswith(SPDX)]
    assert not missing, f"first line must be {SPDX!r}: {missing}"


def test_every_github_action_is_pinned_to_a_commit() -> None:
    workflows = list((ROOT / ".github" / "workflows").glob("*.yml"))
    assert workflows
    used = [m for p in workflows for m in re.findall(r"uses:\s*(\S+)", p.read_text(encoding="utf-8"))]
    assert used
    loose = [action for action in used if not re.fullmatch(r"[\w.-]+/[\w./-]+@[0-9a-f]{40}", action)]
    assert not loose, f"pin these actions to a full commit hash: {loose}"


def test_dependabot_watches_the_actions_and_the_lock_file() -> None:
    text = (ROOT / ".github" / "dependabot.yml").read_text(encoding="utf-8")
    assert set(re.findall(r"package-ecosystem:\s*(\S+)", text)) == {"github-actions", "uv"}


def test_the_three_packages_share_one_version() -> None:
    versions = {
        tomllib.loads((ROOT / d / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]
        for d in (".", "protocol", "receiver")
    }
    assert versions == {veilleur_receive.__version__}


def test_the_current_version_has_release_notes_in_both_languages() -> None:
    version = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]
    for language in ("en", "fr"):
        notes = (ROOT / "docs" / language / "release-notes.md").read_text(encoding="utf-8")
        assert f"## {version}\n" in notes


def test_the_security_policy_points_to_private_reporting() -> None:
    policy = (ROOT / "SECURITY.md").read_text(encoding="utf-8")
    assert "https://github.com/Cafeinoman/veilleur/security/advisories/new" in policy


def test_the_contributing_guide_exists_in_both_languages() -> None:
    assert (ROOT / "CONTRIBUTING.md").is_file()
    assert (ROOT / "CONTRIBUTING.fr.md").is_file()


def test_documentation_exists_in_both_languages() -> None:
    en = {p.relative_to(ROOT / "docs" / "en") for p in (ROOT / "docs" / "en").rglob("*.md")}
    fr = {p.relative_to(ROOT / "docs" / "fr") for p in (ROOT / "docs" / "fr").rglob("*.md")}
    assert en
    assert en == fr, f"only in English: {sorted(map(str, en - fr))}; only in French: {sorted(map(str, fr - en))}"
