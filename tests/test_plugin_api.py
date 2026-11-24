# SPDX-License-Identifier: EUPL-1.2
"""The public surface of the plugin API, version 1 (ADR-0028), written out in full.

Plugins maintained elsewhere (`veilleur-marches`) import these names. A rename, a removal or a change of order breaks
them, so it fails here; what ADR-0028 allows in a 0.x minor version passes: a final field with a default, a new
method, a new enumeration member, a new public name. Changing what this file expects is a decision, visible in a PR.
Names and order are frozen, not docstrings nor annotations.
"""

from __future__ import annotations

import dataclasses
import importlib
import inspect
from importlib.metadata import entry_points
from typing import Any

import pytest

import veilleur

NO_DEFAULT = "<no default>"

PUBLIC_NAMES = {
    "veilleur.core.ports.plugins": {
        "Collector",
        "ParamsCheck",
        "FilterItem",
        "Filter",
        "SetFilter",
        "ReportView",
        "Renderer",
        "RoundCounts",
        "NotificationTarget",
        "Notifier",
        "Plugins",
        # Imported there, used by plugins through this module.
        "Collected",
        "CollectedItem",
        "ItemChange",
        "Kind",
        "SourceStatus",
        "HttpClient",
    },
    "veilleur.core.ports.http": {"HttpClient", "HttpResponse"},
    "veilleur.core.domain.model": {"Collected", "CollectedItem", "ItemChange", "SourceStatus", "Kind", "Change"},
    "veilleur.core.domain.errors": {"CollectorError"},
    "veilleur.core.domain.schema": {"validate"},
}

# Data objects: (field, default) in declaration order.
DATA_OBJECTS: dict[str, list[tuple[str, Any]]] = {
    "veilleur.core.domain.model:CollectedItem": [("fields", NO_DEFAULT), ("key", None), ("url", None)],
    "veilleur.core.domain.model:Collected": [("items", NO_DEFAULT), ("complete", True)],
    "veilleur.core.domain.model:ItemChange": [
        ("key", NO_DEFAULT),
        ("change", NO_DEFAULT),
        ("hash", NO_DEFAULT),
        ("fields", NO_DEFAULT),
        ("fetched_at", NO_DEFAULT),
        ("url", NO_DEFAULT),
    ],
    "veilleur.core.domain.model:SourceStatus": [
        ("collection_id", NO_DEFAULT),
        ("collector", NO_DEFAULT),
        ("last_attempt", NO_DEFAULT),
        ("last_success", NO_DEFAULT),
        ("error", NO_DEFAULT),
        ("failing_since", None),
    ],
    "veilleur.core.ports.http:HttpResponse": [
        ("status", NO_DEFAULT),
        ("url", NO_DEFAULT),
        ("headers", NO_DEFAULT),
        ("body", NO_DEFAULT),
    ],
    "veilleur.core.ports.plugins:FilterItem": [("key", NO_DEFAULT), ("fields", NO_DEFAULT), ("url", NO_DEFAULT)],
    "veilleur.core.ports.plugins:ReportView": [
        ("uid", NO_DEFAULT),
        ("seq", NO_DEFAULT),
        ("kind", NO_DEFAULT),
        ("created_at", NO_DEFAULT),
        ("period_from", NO_DEFAULT),
        ("period_to", NO_DEFAULT),
        ("items", NO_DEFAULT),
        ("sources", NO_DEFAULT),
    ],
    "veilleur.core.ports.plugins:RoundCounts": [
        ("reports", NO_DEFAULT),
        ("new_items", NO_DEFAULT),
        ("failing_sources", NO_DEFAULT),
    ],
    "veilleur.core.ports.plugins:NotificationTarget": [("key_id", NO_DEFAULT), ("topic", NO_DEFAULT)],
    "veilleur.core.ports.plugins:Plugins": [
        ("collectors", NO_DEFAULT),
        ("filters", NO_DEFAULT),
        ("renderers", NO_DEFAULT),
    ],
}

# Protocols: member -> parameters of the method (name, kind, default), or None for a property.
_P = inspect.Parameter
PROTOCOLS: dict[str, dict[str, list[tuple[str, Any, Any]] | None]] = {
    "veilleur.core.ports.plugins:Collector": {
        "name": None,
        "schema": None,
        "follows_client_urls": None,
        "collect": [
            ("params", _P.POSITIONAL_OR_KEYWORD, NO_DEFAULT),
            ("since", _P.POSITIONAL_OR_KEYWORD, NO_DEFAULT),
            ("http", _P.POSITIONAL_OR_KEYWORD, NO_DEFAULT),
        ],
    },
    "veilleur.core.ports.plugins:ParamsCheck": {
        "check_params": [("params", _P.POSITIONAL_OR_KEYWORD, NO_DEFAULT)],
    },
    "veilleur.core.ports.plugins:Filter": {
        "name": None,
        "schema": None,
        "apply": [("item", _P.POSITIONAL_OR_KEYWORD, NO_DEFAULT), ("params", _P.POSITIONAL_OR_KEYWORD, NO_DEFAULT)],
    },
    "veilleur.core.ports.plugins:SetFilter": {
        "select": [("items", _P.POSITIONAL_OR_KEYWORD, NO_DEFAULT), ("params", _P.POSITIONAL_OR_KEYWORD, NO_DEFAULT)],
    },
    "veilleur.core.ports.plugins:Renderer": {
        "name": None,
        "render": [
            ("report", _P.POSITIONAL_OR_KEYWORD, NO_DEFAULT),
            ("language", _P.POSITIONAL_OR_KEYWORD, NO_DEFAULT),
        ],
    },
    "veilleur.core.ports.plugins:Notifier": {
        "name": None,
        "notify": [
            ("target", _P.POSITIONAL_OR_KEYWORD, NO_DEFAULT),
            ("counts", _P.POSITIONAL_OR_KEYWORD, NO_DEFAULT),
        ],
    },
    "veilleur.core.ports.http:HttpClient": {
        "get": [("url", _P.POSITIONAL_OR_KEYWORD, NO_DEFAULT), ("accept", _P.KEYWORD_ONLY, ())],
    },
}

ENUMS = {
    "veilleur.core.domain.model:Kind": {"DELTA": "delta", "STATE": "state", "HISTORY": "history"},
    "veilleur.core.domain.model:Change": {"NEW": "new", "CHANGED": "changed", "GONE": "gone"},
}

GROUPS = ("veilleur.collectors", "veilleur.filters", "veilleur.renderers", "veilleur.notifiers")

# Entry points this distribution provides: name -> `__name__` of the loaded class.
PROVIDED_ENTRY_POINTS = {
    "veilleur.collectors": {"rss": "RssCollector", "json_api": "JsonApiCollector", "page": "PageCollector"},
    "veilleur.filters": {"keywords": "KeywordsFilter", "regex": "RegexFilter", "dedup": "DedupFilter"},
    "veilleur.renderers": {"markdown": "MarkdownRenderer", "html": "HtmlRenderer"},
}

# Not in the ADR-0028 surface, but imported by the configuration, the tests and possibly embedders: the packages of
# the provided plugins keep re-exporting them, whatever module holds them (ADR-0029, D5).
PROVIDED_PACKAGES = {
    "veilleur.adapters.filters": {"KeywordsFilter", "RegexFilter", "DedupFilter", "compile_pattern", "MAX_TEXT"},
    "veilleur.adapters.renderers": {"MarkdownRenderer", "HtmlRenderer", "MAX_TEXT", "MAX_VALUE"},
    "veilleur.adapters.notifiers": {
        "NtfyNotifier",
        "WebhookNotifier",
        "NotificationFailed",
        "message",
        "sign",
    },
}


def _resolve(path: str) -> Any:
    module, _, name = path.partition(":")
    return getattr(importlib.import_module(module), name)


def _default(f: dataclasses.Field[Any]) -> Any:
    if f.default is not dataclasses.MISSING:
        return f.default
    if f.default_factory is not dataclasses.MISSING:
        return f.default_factory()
    return NO_DEFAULT


@pytest.mark.parametrize("module", sorted(PUBLIC_NAMES))
def test_public_names_are_there(module: str) -> None:
    namespace = vars(importlib.import_module(module))
    assert sorted(PUBLIC_NAMES[module] - namespace.keys()) == []


@pytest.mark.parametrize("path", sorted(DATA_OBJECTS))
def test_data_objects_keep_their_fields_order_and_defaults(path: str) -> None:
    """The frozen fields come first, in order, with their defaults; a field added after them must have a default,
    or every plugin that builds the object would break."""
    cls = _resolve(path)
    assert dataclasses.is_dataclass(cls)
    actual = [(f.name, _default(f)) for f in dataclasses.fields(cls) if f.init]
    expected = DATA_OBJECTS[path]
    assert actual[: len(expected)] == expected
    assert [name for name, default in actual[len(expected) :] if default is NO_DEFAULT] == []


def test_source_status_keeps_its_ok_property() -> None:
    status = _resolve("veilleur.core.domain.model:SourceStatus")
    assert isinstance(inspect.getattr_static(status, "ok"), property)


@pytest.mark.parametrize("path", sorted(PROTOCOLS))
def test_protocols_keep_their_members_and_parameters(path: str) -> None:
    protocol = _resolve(path)
    for member, expected in PROTOCOLS[path].items():
        attribute = inspect.getattr_static(protocol, member, None)
        assert attribute is not None, f"{path} lost {member}"
        if expected is None:
            assert isinstance(attribute, property), f"{path}.{member} is no longer a property"
            continue
        assert inspect.isfunction(attribute), f"{path}.{member} is no longer a method"
        parameters = list(inspect.signature(attribute).parameters.values())[1:]  # without self
        actual = [(p.name, p.kind, NO_DEFAULT if p.default is _P.empty else p.default) for p in parameters]
        assert actual == expected, f"{path}.{member}"


@pytest.mark.parametrize("path", sorted(ENUMS))
def test_enumerations_keep_their_members(path: str) -> None:
    actual = {member.name: member.value for member in _resolve(path)}
    assert {name: actual.get(name) for name in ENUMS[path]} == ENUMS[path]


def test_collector_error_takes_a_code() -> None:
    error_class = _resolve("veilleur.core.domain.errors:CollectorError")
    assert issubclass(error_class, Exception)
    assert error_class("network_unavailable").code == "network_unavailable"


def test_validate_keeps_its_signature() -> None:
    parameters = inspect.signature(_resolve("veilleur.core.domain.schema:validate")).parameters
    assert [(p.name, NO_DEFAULT if p.default is _P.empty else p.default) for p in parameters.values()] == [
        ("value", NO_DEFAULT),
        ("schema", NO_DEFAULT),
        ("path", ""),
    ]


def test_the_version_is_a_dotted_string() -> None:
    assert isinstance(veilleur.__version__, str)
    assert all(part.isdigit() for part in veilleur.__version__.split(".")[:2])


def test_the_server_looks_in_the_four_entry_point_groups() -> None:
    from veilleur.adapters import plugins

    assert plugins.GROUPS == GROUPS


@pytest.mark.parametrize("group", sorted(PROVIDED_ENTRY_POINTS))
def test_provided_entry_points_load_the_same_classes(group: str) -> None:
    provided = {e.name: e for e in entry_points(group=group) if e.value.startswith("veilleur.")}
    assert sorted(provided) == sorted(PROVIDED_ENTRY_POINTS[group])
    for name, class_name in PROVIDED_ENTRY_POINTS[group].items():
        loaded = provided[name].load()
        assert isinstance(loaded, type)
        assert loaded.__name__ == class_name
        assert loaded().name == name


@pytest.mark.parametrize("package", sorted(PROVIDED_PACKAGES))
def test_provided_plugin_packages_keep_their_exports(package: str) -> None:
    namespace = vars(importlib.import_module(package))
    assert sorted(PROVIDED_PACKAGES[package] - namespace.keys()) == []
