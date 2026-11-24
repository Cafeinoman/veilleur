# SPDX-License-Identifier: EUPL-1.2
"""Independent check of lot J7-L3 (docs/PLAN.md): the frozen plugin API surface and the split of the provided plugins.

Written from the acceptance criteria of J7-L3, ADR-0028 and ADR-0029. Criterion 1 is checked by mutation: the package
is copied, one thing ADR-0028 forbids is changed, and `tests/test_plugin_api.py` must fail against the copy (and pass
against an allowed addition). The checks that compare with the code before the lot need the git history; they are
skipped on a shallow clone.
"""

from __future__ import annotations

import ast
import importlib
import importlib.util
import os
import re
import shutil
import subprocess
import sys
import tomllib
import types
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from importlib.metadata import entry_points
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "src" / "veilleur"
API_TEST = ROOT / "tests" / "test_plugin_api.py"
BASE = "c4e0298"  # main when the lot started (merge of PR #14).
PACKAGES = ("filters", "renderers", "notifiers")


def git(*args: str) -> str | None:
    result = subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, check=False)
    return result.stdout if result.returncode == 0 else None


def need_base() -> None:
    if git("rev-parse", "--verify", "--quiet", f"{BASE}^{{commit}}") is None:
        pytest.skip(f"commit {BASE} is not in this clone")


# --- Criterion 1: the surface test fails on a forbidden change, passes on an allowed one -------------------------


def _run_api_test(tmp_path: Path, mutate: Callable[[Path], None]) -> subprocess.CompletedProcess[str]:
    copy = tmp_path / "src"
    shutil.copytree(SOURCE, copy / "veilleur", ignore=shutil.ignore_patterns("__pycache__"))
    mutate(copy / "veilleur")
    env = {**os.environ, "PYTHONPATH": f"{copy}{os.pathsep}{os.environ.get('PYTHONPATH', '')}"}
    probe = subprocess.run(
        [sys.executable, "-c", "import veilleur; print(veilleur.__file__)"], env=env, capture_output=True, text=True
    )
    assert probe.stdout.strip().startswith(str(copy)), probe.stdout + probe.stderr  # the copy is the one under test
    return subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", str(API_TEST)],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
    )


def _replace(relative: str, old: str, new: str) -> Callable[[Path], None]:
    def mutate(package: Path) -> None:
        path = package / relative
        text = path.read_text(encoding="utf-8")
        assert text.count(old) == 1, (relative, old)
        path.write_text(text.replace(old, new), encoding="utf-8")

    return mutate


FORBIDDEN = {
    "rename_collected_item_field": _replace(
        "core/domain/model.py",
        "    fields: dict[str, Any]\n    key: str | None = None",
        "    values: dict[str, Any]\n    key: str | None = None",
    ),
    "remove_http_client_get": _replace(
        "core/ports/http.py",
        "    def get(self, url: str, *, accept: Sequence[str] = ()) -> HttpResponse:",
        "    def fetch(self, url: str, *, accept: Sequence[str] = ()) -> HttpResponse:",
    ),
    # Both fields given a default so that the module still imports: only the order differs.
    "swap_collected_fields": _replace(
        "core/domain/model.py",
        "    items: tuple[CollectedItem, ...]\n    complete: bool = True",
        "    complete: bool = True\n    items: tuple[CollectedItem, ...] = ()",
    ),
    "change_default_of_collected_item_key": _replace(
        "core/domain/model.py",
        "    key: str | None = None\n    url: str | None = None",
        "    key: str | None = ''\n    url: str | None = None",
    ),
    # ItemChange has no default at all, so a final field without one still imports: only the test can catch it.
    "final_field_without_default": _replace(
        "core/domain/model.py",
        "    fetched_at: datetime\n    url: str | None\n",
        "    fetched_at: datetime\n    url: str | None\n    extra: int\n",
    ),
    "rename_change_member": _replace("core/domain/model.py", '    GONE = "gone"', '    REMOVED = "gone"'),
    "rename_collect_parameter": _replace(
        "core/ports/plugins.py",
        "self, params: Mapping[str, Any], since: datetime | None, http: HttpClient",
        "self, params: Mapping[str, Any], since: datetime | None, client: HttpClient",
    ),
    "drop_keywords_reexport": _replace(
        "adapters/filters/__init__.py",
        "from veilleur.adapters.filters.keywords import KeywordsFilter\n",
        "",
    ),
}


@pytest.mark.parametrize("name", sorted(FORBIDDEN))
def test_the_surface_test_fails_on_a_forbidden_change(tmp_path: Path, name: str) -> None:
    result = _run_api_test(tmp_path, FORBIDDEN[name])
    assert result.returncode != 0, result.stdout[-2000:]
    assert "FAILED tests/test_plugin_api.py::" in result.stdout, result.stdout[-2000:]  # a check, not a crash


ALLOWED = {
    "final_field_with_default": _replace(
        "core/domain/model.py",
        "    key: str | None = None\n    url: str | None = None\n",
        "    key: str | None = None\n    url: str | None = None\n    extra: int = 0\n",
    ),
    "new_http_method": _replace(
        "core/ports/http.py",
        "    def get(self, url: str, *, accept: Sequence[str] = ()) -> HttpResponse:",
        "    def post_json(self, url: str, body: object) -> HttpResponse: ...\n\n"
        "    def get(self, url: str, *, accept: Sequence[str] = ()) -> HttpResponse:",
    ),
}


@pytest.mark.parametrize("name", sorted(ALLOWED))
def test_the_surface_test_lets_an_allowed_addition_through(tmp_path: Path, name: str) -> None:
    result = _run_api_test(tmp_path, ALLOWED[name])
    assert result.returncode == 0, result.stdout[-2000:]


def test_the_unchanged_copy_passes(tmp_path: Path) -> None:
    result = _run_api_test(tmp_path, lambda package: None)
    assert result.returncode == 0, result.stdout[-2000:]


# --- Criterion 2: the names stay importable, the entry points load the same classes ------------------------------

NAMES = {
    "veilleur.adapters.filters": ("KeywordsFilter", "RegexFilter", "DedupFilter"),
    "veilleur.adapters.renderers": ("MarkdownRenderer", "HtmlRenderer"),
    "veilleur.adapters.notifiers": ("NtfyNotifier", "WebhookNotifier"),
}


@pytest.mark.parametrize("module", sorted(NAMES))
def test_the_named_classes_stay_importable(module: str) -> None:
    namespace = importlib.import_module(module)
    for name in NAMES[module]:
        cls = getattr(namespace, name)
        assert isinstance(cls, type) and cls.__name__ == name


def _old(path: str) -> str:
    text = git("show", f"{BASE}:{path}")
    assert text is not None, path
    return text


def test_every_public_name_of_the_former_packages_is_still_exported() -> None:
    need_base()
    missing = []
    for package in PACKAGES:
        tree = ast.parse(_old(f"src/veilleur/adapters/{package}/__init__.py"))
        names = set()
        for node in tree.body:
            if isinstance(node, ast.FunctionDef | ast.ClassDef):
                names.add(node.name)
            elif isinstance(node, ast.Assign):
                names.update(t.id for t in node.targets if isinstance(t, ast.Name))
            elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                names.add(node.target.id)
        module = importlib.import_module(f"veilleur.adapters.{package}")
        missing += [f"{package}.{n}" for n in sorted(names) if not n.startswith("_") and not hasattr(module, n)]
    assert missing == []


def test_each_provided_entry_point_loads_the_same_class_as_before_the_lot() -> None:
    need_base()
    before = tomllib.loads(_old("pyproject.toml"))["project"]["entry-points"]
    for group in ("veilleur.collectors", "veilleur.filters", "veilleur.renderers", "veilleur.notifiers"):
        old = before.get(group, {})
        now = {e.name: e for e in entry_points(group=group) if e.value.startswith("veilleur.")}
        assert sorted(now) == sorted(old), group
        for name, value in old.items():
            module, _, attribute = value.partition(":")
            former = getattr(importlib.import_module(module), attribute)
            loaded = now[name].load()
            assert loaded is former, (group, name)
            assert loaded.__name__ == former.__name__


def test_the_installed_entry_points_match_pyproject() -> None:
    """The metadata the tests load comes from pyproject.toml, not from a stale install."""
    declared = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["entry-points"]
    for group, values in declared.items():
        if not group.startswith("veilleur."):
            continue
        installed = {e.name: e.value for e in entry_points(group=group) if e.value.startswith("veilleur.")}
        assert installed == values, group


@pytest.mark.xfail(
    strict=True,
    reason="ADR-0029 asks the split modules be re-exported from __init__ « pour les entry points » and says the "
    "import paths do not change; the lot points the filter and renderer entry points at the new submodules instead",
)
def test_the_entry_points_still_name_the_package_modules() -> None:
    need_base()
    before = tomllib.loads(_old("pyproject.toml"))["project"]["entry-points"]
    now = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["entry-points"]
    assert now == before


# --- No change of behaviour (ADR-0029): the former code and the split code give the same outputs ------------------


def _load_former(package: str) -> types.ModuleType:
    need_base()
    name = f"_former_{package}"
    module = types.ModuleType(name)
    module.__file__ = f"<{BASE}:{package}>"
    sys.modules[name] = module
    try:
        exec(compile(_old(f"src/veilleur/adapters/{package}/__init__.py"), module.__file__, "exec"), module.__dict__)
    finally:
        del sys.modules[name]
    return module


NOW = datetime(2026, 11, 17, 6, 0, tzinfo=UTC)


def _report(kind: Any) -> Any:
    from veilleur.core.domain.model import Change, ItemChange, SourceStatus
    from veilleur.core.ports.plugins import ReportView

    items = (
        ItemChange(
            "a", Change.NEW, "0" * 64, {"title": "First <b>&", "summary": "x" * 5000}, NOW, "https://example.org/a"
        ),
        ItemChange("b", Change.CHANGED, "1" * 64, {"name": "Second‮`*_", "n": 3}, NOW, "javascript:alert(1)"),
        ItemChange("c", Change.GONE, "2" * 64, {"other": ["l", {"d": None}]}, NOW, None),
    )
    sources = (
        SourceStatus("c1", "rss", NOW, NOW, None),
        SourceStatus("c2", "page", NOW, NOW - timedelta(days=3), "http_500"),
        SourceStatus("c3", "json_api", NOW, None, "network_unavailable"),
        SourceStatus("c4", "custom", None, None, None),
    )
    return ReportView("ab" * 16, 7, kind, NOW, NOW - timedelta(days=1), NOW, items, sources)


@pytest.mark.parametrize("language", ["en", "fr"])
@pytest.mark.parametrize("renderer", ["MarkdownRenderer", "HtmlRenderer"])
def test_the_renderers_render_as_before(renderer: str, language: str) -> None:
    from veilleur.adapters import renderers
    from veilleur.core.domain.model import Kind

    former = _load_former("renderers")
    for kind in Kind:
        report = _report(kind)
        assert getattr(renderers, renderer)().render(report, language) == getattr(former, renderer)().render(
            report, language
        )


def test_the_filters_filter_as_before() -> None:
    from veilleur.adapters import filters
    from veilleur.core.ports.plugins import FilterItem

    former = _load_former("filters")
    items = [
        FilterItem("1", {"title": "Café crème", "body": "Appel d'offres"}, "https://example.org/1"),
        FilterItem("2", {"title": "CAFE", "n": 4, "nested": {"t": "offre"}}, None),
        FilterItem("3", {"title": "Thé"}, "https://example.org/1"),
        FilterItem("4", {"title": " café  CRÈME "}, None),
    ]
    cases: list[tuple[str, dict[str, Any]]] = [
        ("KeywordsFilter", {"words": ["cafe"], "accent_sensitive": False}),
        ("KeywordsFilter", {"words": ["Café", "offres"], "match": "all", "case_sensitive": True}),
        ("KeywordsFilter", {"words": ["thé"], "exclude": True, "fields": ["title"]}),
        ("RegexFilter", {"pattern": r"caf[eé]\b", "accent_sensitive": False}),
        ("RegexFilter", {"pattern": "OFFRE", "case_sensitive": True}),
    ]
    for name, params in cases:
        new, old = getattr(filters, name)(), getattr(former, name)()
        assert [new.apply(i, params) for i in items] == [old.apply(i, params) for i in items], (name, params)
    for params in ({"fields": ["title"]}, {"by_url": True}, {}):
        new, old = filters.DedupFilter(), former.DedupFilter()
        assert new.check_params(params) == old.check_params(params)
        assert list(new.select(items, params)) == list(old.select(items, params))
    for name in ("KeywordsFilter", "RegexFilter", "DedupFilter"):
        assert getattr(filters, name).schema == getattr(former, name).schema
    assert filters.RegexFilter().check_params({"pattern": "(a)\\1"}) == former.RegexFilter().check_params(
        {"pattern": "(a)\\1"}
    )


def test_the_notifiers_send_as_before() -> None:
    from veilleur.adapters import notifiers
    from veilleur.core.ports.plugins import NotificationTarget, RoundCounts

    former = _load_former("notifiers")
    target = NotificationTarget("0123456789abcdef", "a" * 32)
    counts = RoundCounts(2, 5, 1)

    def run(module: types.ModuleType, status: int) -> list[Any]:
        posts: list[Any] = []

        def poster(url: str, body: bytes, headers: Any) -> int:
            posts.append((url, body, dict(headers)))
            return status

        for notifier in (
            module.NtfyNotifier("https://ntfy.example.org/", "tk", "fr", poster),
            module.WebhookNotifier("https://hook.example.org/", b"k" * 32, lambda: NOW, poster),
        ):
            try:
                notifier.notify(target, counts)
                posts.append("ok")
            except Exception as error:
                posts.append((type(error).__name__, str(error)))
        return posts

    for status in (200, 204, 302, 403, 500):
        assert run(notifiers, status) == run(former, status)
    for language in ("en", "fr"):
        assert notifiers.message(RoundCounts(1, 0, 3), language) == former.message(RoundCounts(1, 0, 3), language)
    assert notifiers.TIMEOUT == former.TIMEOUT and notifiers.SIGNATURE_HEADER == former.SIGNATURE_HEADER


# --- Criterion 3: the lot only adds test files --------------------------------------------------------------------

LOT = "J7-L3"
STATUS = re.compile(r"^- \*\*Statut\.\*\* (à faire|fait)\b", re.MULTILINE)


def _lot_done(plan: str) -> bool:
    start = plan.find(f"### {LOT} ")
    if start == -1:
        return False
    body = plan[start : plan.find("\n### ", start + 1)]
    match = STATUS.search(body)
    return bool(match and match.group(1) == "fait")


def _lot_end() -> str:
    """The commit that marks the lot done in the plan, or HEAD while the lot is under way; later lots may change the
    tests freely."""
    commits = git("log", "--reverse", "--format=%H", f"{BASE}..HEAD", "--", "docs/PLAN.md") or ""
    for commit in commits.split():
        if _lot_done(git("show", f"{commit}:docs/PLAN.md") or ""):
            return commit
    return "HEAD"


def _not_added() -> list[str]:
    changed = git("diff", "--name-status", f"{BASE}...{_lot_end()}", "--", "tests")
    assert changed is not None
    return [line for line in changed.splitlines() if line and not line.startswith("A")]


@pytest.mark.xfail(
    strict=True,
    reason="criterion 3 of J7-L3 is breached by tests/verif/test_j7_l2_pointers.py (commit 35c517d), "
    "admitted by decision D18 of docs/DECISIONS.md",
)
def test_the_lot_only_adds_test_files() -> None:
    need_base()
    assert _not_added() == []


D18_FILE = "tests/verif/test_j7_l2_pointers.py"


def test_the_only_modified_test_file_is_the_one_admitted_by_d18() -> None:
    need_base()
    assert [line.split()[-1] for line in _not_added()] == [D18_FILE]
    decisions = (ROOT / "docs" / "DECISIONS.md").read_text(encoding="utf-8")
    entry = decisions.split("## D18.", 1)[1].split("\n## ", 1)[0]
    assert D18_FILE.rsplit("/", 1)[1] in entry
    assert "critère 3 de J7-L3" in entry and "admis" in entry


# --- Criterion 4: the four import contracts are unchanged ---------------------------------------------------------


def test_the_import_contracts_are_unchanged() -> None:
    need_base()
    before = tomllib.loads(_old("pyproject.toml"))["tool"]["importlinter"]
    now = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["tool"]["importlinter"]
    assert len(now["contracts"]) == 4
    assert now == before


# --- Criterion 5 and step 3: both guides list the same public modules and the ADR-0028 surface --------------------

SURFACE = {
    "entry point groups": {"veilleur.collectors", "veilleur.filters", "veilleur.renderers", "veilleur.notifiers"},
    "veilleur.core.ports.http": {"HttpClient", "HttpResponse"},
    "veilleur.core.domain.model": {"Collected", "CollectedItem", "ItemChange", "SourceStatus", "Kind", "Change"},
    "veilleur.core.domain.errors": {"CollectorError"},
    "veilleur.core.domain.schema": {"validate"},
    "veilleur": {"__version__"},
}


def _table(language: str) -> list[tuple[str, set[str]]]:
    text = (ROOT / "docs" / language / "writing-a-collector.md").read_text(encoding="utf-8")
    rows = []
    for line in text.splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")] if line.startswith("| ") else []
        if len(cells) == 2 and "`" in cells[1]:
            rows.append((cells[0], set(re.findall(r"`([^`]+)`", cells[1]))))
    return rows


def test_both_guides_list_the_same_public_modules_and_names() -> None:
    english, french = _table("en"), _table("fr")
    assert english
    assert [names for _, names in english] == [names for _, names in french]
    modules_en = [re.findall(r"`([^`]+)`", first) for first, _ in english]
    modules_fr = [re.findall(r"`([^`]+)`", first) for first, _ in french]
    assert modules_en == modules_fr


def test_the_guides_list_every_name_of_the_adr_surface() -> None:
    from veilleur.core.ports import plugins

    listed: dict[str, set[str]] = {}
    for first, names in _table("en"):
        modules = re.findall(r"`([^`]+)`", first)
        listed[modules[0] if modules else "entry point groups"] = names
    expected = dict(SURFACE)
    expected["veilleur.core.ports.plugins"] = {
        n
        for n, v in vars(plugins).items()
        if not n.startswith("_") and getattr(v, "__module__", "") == plugins.__name__
    }
    for module, names in expected.items():
        assert names <= listed.get(module, set()), module


@pytest.mark.parametrize("language", ["en", "fr"])
def test_the_guides_state_the_compatibility_rule(language: str) -> None:
    text = (ROOT / "docs" / language / "writing-a-collector.md").read_text(encoding="utf-8")
    assert "DeprecationWarning" in text
    assert "tests/test_plugin_api.py" in text
    assert "veilleur.__version__" in text
