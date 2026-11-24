# SPDX-License-Identifier: EUPL-1.2
"""Batch G6 (release 0.1.0), checked from the plan and the specification. No test reaches the network."""

from __future__ import annotations

import contextlib
import re
import subprocess
import tomllib
from importlib import metadata
from pathlib import Path
from typing import Any

import pytest

import veilleur
import veilleur_receive
from veilleur.apps.server.cli import main
from veilleur_receive.cli import main as receive_main

ROOT = Path(__file__).resolve().parents[2]
PROJECTS = {"veilleur": ".", "veilleur-protocol": "protocol", "veilleur-receive": "receiver"}
ADVISORY = "https://github.com/Cafeinoman/veilleur/security/advisories/new"
LANGUAGES = ("en", "fr")
GUIDES = {"en": "CONTRIBUTING.md", "fr": "CONTRIBUTING.fr.md"}
READMES = {"en": "README.md", "fr": "README.fr.md"}


def read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def project(directory: str) -> dict[str, Any]:
    document: dict[str, Any] = tomllib.loads(read(f"{directory}/pyproject.toml"))["project"]
    return document


def version() -> str:
    return str(project(".")["version"])


def tracked() -> list[str]:
    result = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True)
    return result.stdout.splitlines()


def links(relative: str) -> list[str]:
    return re.findall(r"\]\(([^)\s]+)\)", read(relative))


def slug(heading: str) -> str:
    return re.sub(r"[^\w\- ]", "", heading.strip().lower()).replace(" ", "-")


def bullets(text: str) -> list[str]:
    return re.findall(r"^- (.+)$", text, flags=re.MULTILINE)


def tokens(text: str) -> list[str]:
    return re.findall(r"`([^`]+)`", text)


# Version


@pytest.mark.parametrize(("name", "directory"), PROJECTS.items())
def test_the_installed_package_has_the_version_of_its_project(name: str, directory: str) -> None:
    assert metadata.version(name) == project(directory)["version"] == version()


@pytest.mark.parametrize("name", PROJECTS)
def test_the_lock_file_records_the_version(name: str) -> None:
    packages = tomllib.loads(read("uv.lock"))["package"]
    assert [p["version"] for p in packages if p["name"] == name] == [version()]


def test_the_version_is_not_older_than_the_first_release() -> None:
    assert tuple(int(part) for part in version().split(".")) >= (0, 1, 0)


@pytest.mark.parametrize("directory", PROJECTS.values())
def test_no_project_is_still_declared_as_planning(directory: str) -> None:
    status = [c for c in project(directory)["classifiers"] if c.startswith("Development Status")]
    assert status == ["Development Status :: 3 - Alpha"]


@pytest.mark.parametrize("language", LANGUAGES)
def test_the_server_command_prints_the_release(language: str, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["--lang", language, "version"]) == 0
    assert capsys.readouterr().out.startswith(f"Veilleur {version()}, ")
    assert veilleur.__version__ == version()


@pytest.mark.parametrize("language", LANGUAGES)
def test_the_receiver_command_prints_the_release(language: str, capsys: pytest.CaptureFixture[str]) -> None:
    assert receive_main(["--lang", language, "version"]) == 0
    assert capsys.readouterr().out == f"veilleur-receive {version()}\n"
    assert veilleur_receive.__version__ == version()


@pytest.mark.parametrize(
    "example", ["deploy/nixos/examples/host-module.nix", "deploy/nixos/examples/vps/flake.nix"]
)
def test_the_deployment_examples_name_the_tag_of_the_release(example: str) -> None:
    assert f"v{version()}" in read(example)


# Continuous integration


def workflow_lines() -> list[str]:
    files = [*(ROOT / ".github/workflows").glob("*.yml"), *(ROOT / ".github/workflows").glob("*.yaml")]
    assert files
    return [line.strip() for path in files for line in path.read_text(encoding="utf-8").splitlines()]


def test_every_action_is_pinned_and_says_which_release_it_is() -> None:
    used = [line for line in workflow_lines() if re.match(r"(- )?uses:", line)]
    assert len(used) >= 3
    pinned = r"(- )?uses: [\w.-]+/[\w.-]+@[0-9a-f]{40} # v\d+\.\d+\.\d+"
    assert [line for line in used if not re.fullmatch(pinned, line)] == []


def test_one_action_is_pinned_to_one_commit() -> None:
    pins: dict[str, set[str]] = {}
    for action, commit in re.findall(r"uses: ([\w./-]+)@(\w+)", "\n".join(workflow_lines())):
        pins.setdefault(action, set()).add(commit)
    assert pins
    assert {action: commits for action, commits in pins.items() if len(commits) != 1} == {}


def test_dependabot_follows_the_actions_and_the_lock_file_every_week() -> None:
    entries = re.split(r"^\s*- package-ecosystem:\s*", read(".github/dependabot.yml"), flags=re.MULTILINE)[1:]
    found = {entry.split()[0]: entry for entry in entries}
    assert set(found) == {"github-actions", "uv"}
    for entry in found.values():
        assert re.search(r"^\s*directory:\s*/\s*$", entry, flags=re.MULTILINE)
        assert re.search(r"^\s*interval:\s*weekly\s*$", entry, flags=re.MULTILINE)
    assert "uv.lock" in tracked()


# Secret scanning


def allowlists() -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = tomllib.loads(read(".gitleaks.toml"))["allowlists"]
    return found


def test_gitleaks_keeps_its_default_rules() -> None:
    assert tomllib.loads(read(".gitleaks.toml"))["extend"] == {"useDefault": True}


def test_the_scan_excludes_paths_only() -> None:
    assert [sorted(entry) for entry in allowlists()] == [["description", "paths"]]


def test_the_scan_excludes_the_test_vectors_and_nothing_else() -> None:
    pattern = re.compile(allowlists()[0]["paths"][0])
    excluded = {name for name in tracked() if pattern.search(name)}
    vectors = {name for name in tracked() if re.fullmatch(r"protocol/vectors/[^/]+\.json", name)}
    assert vectors
    assert excluded == vectors


@pytest.mark.parametrize(
    "path",
    [
        "src/veilleur/settings.json",
        "protocol/vectors/nested/keys.json",
        "protocol/vectors/keys.json.bak",
        "protocol/vectors/keys.txt",
        "other/protocol/vectors/keys.json",
        ".env",
    ],
)
def test_the_exclusion_does_not_reach_other_paths(path: str) -> None:
    assert re.search(allowlists()[0]["paths"][0], path) is None


def test_no_finding_is_silenced_outside_the_configuration() -> None:
    marker = "gitleaks" + ":allow"
    assert ".gitleaksignore" not in tracked()
    silenced = [
        name
        for name in tracked()
        if (ROOT / name).is_file() and marker in (ROOT / name).read_bytes().decode("utf-8", "replace")
    ]
    assert silenced == []


def test_the_development_shell_provides_gitleaks() -> None:
    assert "pkgs.gitleaks" in read("flake.nix")


# Security policy


def policy_sections() -> list[str]:
    sections = read("SECURITY.md").split("\n---\n")
    assert len(sections) == 2
    return sections


@pytest.mark.parametrize("index", [0, 1])
def test_each_language_of_the_policy_gives_the_private_channel(index: int) -> None:
    assert ADVISORY in policy_sections()[index]


def test_the_policy_offers_no_public_channel() -> None:
    policy = read("SECURITY.md")
    assert "/issues" not in policy
    assert "mailto:" not in policy
    assert re.search(r"[\w.+-]+@[\w-]+\.[\w.]+", policy) is None


def test_the_policy_says_not_to_report_in_public() -> None:
    english, french = policy_sections()
    assert "Do not open a public issue" in english
    assert "N'ouvrez ni ticket" in french


def test_the_policy_covers_the_released_series() -> None:
    series = ".".join(version().split(".")[:2]) + ".x"
    for section in policy_sections():
        assert re.search(rf"^\| {re.escape(series)} \| (yes|oui) \|$", section, flags=re.MULTILINE)


def test_the_language_link_of_the_policy_reaches_a_heading() -> None:
    headings = {slug(h) for h in re.findall(r"^#+ (.+)$", read("SECURITY.md"), flags=re.MULTILINE)}
    anchors = [link[1:] for link in links("SECURITY.md") if link.startswith("#")]
    assert anchors
    assert set(anchors) <= headings


# Contribution guides


@pytest.mark.parametrize("language", LANGUAGES)
def test_the_guide_gives_the_checks_of_the_project(language: str) -> None:
    guide = read(GUIDES[language])
    for command in (
        "uv sync --locked",
        "uv run pytest",
        "uv run ruff check src tests tools protocol receiver",
        "uv run mypy",
        "uv run lint-imports",
        "uv run python tools/i18n.py all",
        "gitleaks git --redact .",
    ):
        assert command in guide


@pytest.mark.parametrize("language", LANGUAGES)
def test_the_guide_lists_every_check_of_the_ci(language: str) -> None:
    commands = re.findall(r"run: uv run --locked (.+)", read(".github/workflows/ci.yml"))
    assert commands
    assert [c for c in commands if f"uv run {c}" not in read(GUIDES[language])] == []


@pytest.mark.parametrize(
    ("language", "words"),
    [
        ("en", ("branch", "pull request", "translat", "Checks")),
        ("fr", ("branche", "pull request", "traduisez", "Contrôles")),
    ],
)
def test_the_guide_covers_the_topics_of_the_plan(language: str, words: tuple[str, ...]) -> None:
    guide = read(GUIDES[language])
    assert [word for word in words if word not in guide] == []


def test_the_two_guides_have_the_same_structure() -> None:
    english, french = read(GUIDES["en"]), read(GUIDES["fr"])
    assert len(re.findall(r"^## ", english, flags=re.MULTILINE)) == len(re.findall(r"^## ", french, flags=re.MULTILINE))
    assert len(bullets(english)) == len(bullets(french))
    fence = r"```bash\n(.*?)```"
    assert re.findall(fence, english, flags=re.DOTALL) == re.findall(fence, french, flags=re.DOTALL)


@pytest.mark.parametrize("language", LANGUAGES)
def test_the_guide_links_to_the_documentation_of_its_language(language: str) -> None:
    documentation = [link for link in links(GUIDES[language]) if link.startswith("docs/")]
    assert documentation
    assert all(link.startswith(f"docs/{language}/") for link in documentation)


@pytest.mark.parametrize(
    "document",
    [
        "SECURITY.md",
        *GUIDES.values(),
        *READMES.values(),
        "docs/en/release-notes.md",
        "docs/fr/release-notes.md",
    ],
)
def test_the_links_of_the_release_documents_resolve(document: str) -> None:
    base = (ROOT / document).parent
    local = [link.split("#")[0] for link in links(document) if not link.startswith(("http", "#"))]
    assert local
    assert [link for link in local if not (base / link).exists()] == []


# Release notes


def notes(language: str) -> str:
    return read(f"docs/{language}/release-notes.md")


def entry_points(group: str) -> set[str]:
    return set(project(".")["entry-points"][group])


@pytest.mark.parametrize("language", LANGUAGES)
def test_the_notes_describe_the_first_release_as_an_alpha(language: str) -> None:
    section = notes(language).split("## 0.1.0\n", 1)[1]
    assert "alpha" in section.split("###")[0]


def test_the_two_notes_have_the_same_structure() -> None:
    english, french = notes("en"), notes("fr")
    heading = re.compile(r"^###? ", flags=re.MULTILINE)
    assert len(heading.findall(english)) == len(heading.findall(french))
    assert [tokens(line) for line in bullets(english)] == [tokens(line) for line in bullets(french)]


@pytest.mark.parametrize("language", LANGUAGES)
def test_the_notes_name_exactly_the_provided_collectors(language: str) -> None:
    assert set(tokens(bullets(notes(language))[0])) == entry_points("veilleur.collectors")


@pytest.mark.parametrize("language", LANGUAGES)
def test_the_notes_name_exactly_the_provided_filters_and_renderings(language: str) -> None:
    named = set(tokens(bullets(notes(language))[1])) - {"delta", "state", "history"}
    assert named == entry_points("veilleur.filters") | entry_points("veilleur.renderers")


def test_the_commands_named_by_the_notes_exist(capsys: pytest.CaptureFixture[str]) -> None:
    with contextlib.suppress(SystemExit):
        main(["--lang", "en", "pairing", "--help"])
    assert "revoke" in capsys.readouterr().out
    with contextlib.suppress(SystemExit):
        main(["--lang", "en", "key", "--help"])
    assert "rotate" in capsys.readouterr().out


# Status of the project and distribution


@pytest.mark.parametrize(("language", "words"), [("en", "Status: alpha"), ("fr", "État : alpha")])
def test_the_readme_gives_the_alpha_status(language: str, words: str) -> None:
    readme = read(READMES[language])
    assert words in readme
    assert f"docs/{language}/release-notes.md" in readme
    assert "SECURITY.md" in readme
    assert GUIDES[language] in readme


def test_no_document_installs_veilleur_from_pypi() -> None:
    command = re.compile(r"\b(pip3?|pipx|uv pip|uv tool|uv add)\b[^\n`]*\bveilleur(-protocol|-receive)?\b")
    documents = [name for name in tracked() if name.lower().endswith(".md") and name != "plan.md"]
    assert [name for name in documents if command.search(read(name))] == []


def test_the_specification_records_the_decisions_of_the_release() -> None:
    decisions = read("docs/adr/0021-publication-et-distribution.md").split("## Décision", 1)[1]
    assert "pas de publication sur PyPI" in decisions
    assert "`v0.1.0`" in decisions
    assert "le nom **Veilleur** est conservé" in decisions
