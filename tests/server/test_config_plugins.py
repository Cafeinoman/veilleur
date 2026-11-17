# SPDX-License-Identifier: EUPL-1.2
"""Configuration file, plugin discovery and the worker thread."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from veilleur.adapters import plugins as plugin_module
from veilleur.apps.server import config
from veilleur.apps.server.service import Worker
from veilleur.core.domain.errors import VeilleurError
from veilleur.core.services import pairing, subscriptions

from .fakes import FakeCollector, World


def test_load_a_configuration_file(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_text(
        """
state_dir = "/srv/veilleur"
public_url = "https://veille.example.org/"
language = "fr"
port = 9000

[[subscriptions]]
name = "team_news"
collector = "rss"
params = { url = "https://example.org/feed.xml" }
pairings = ["desk 1", "desk 2"]
frequency = "weekly"
""",
        encoding="utf-8",
    )
    loaded = config.load(path, environ={})
    assert loaded.state_dir == Path("/srv/veilleur") and loaded.public_url == "https://veille.example.org"
    assert (loaded.language, loaded.port, loaded.listen) == ("fr", 9000, "127.0.0.1")
    (team,) = loaded.subscriptions
    assert team.pairings == ("desk 1", "desk 2")
    assert team.document == {
        "collector": "rss",
        "params": {"url": "https://example.org/feed.xml"},
        "frequency": "weekly",
    }
    overridden = config.load(path, environ={"VEILLEUR_STATE_DIR": str(tmp_path)})
    assert overridden.state_dir == tmp_path
    assert config.load(environ={"VEILLEUR_CONFIG": str(path)}).port == 9000


@pytest.mark.parametrize(
    ("data", "member"),
    [
        ({"unknown": 1}, "unknown"),
        ({"state_dir": "relative"}, "state_dir"),
        ({"public_url": "http://example.org"}, "public_url"),
        ({"language": "de"}, "language"),
        ({"port": 0}, "port"),
        ({"port": "80"}, "port"),
        ({"subscriptions": {}}, "subscriptions"),
        ({"subscriptions": [{"name": "x"}]}, "subscriptions[0].pairings"),
        ({"subscriptions": [{"name": "x", "pairings": ["a"], "secret": 1}]}, "subscriptions[0]"),
        ({"subscriptions": [{"name": "x", "pairings": ["a"]}, {"name": "x", "pairings": ["b"]}]}, "subscriptions.name"),
    ],
)
def test_invalid_configurations(data: dict[str, Any], member: str) -> None:
    with pytest.raises(VeilleurError) as refused:
        config.parse(data)
    assert refused.value.params == {"member": member}


def test_unreadable_configuration(tmp_path: Path) -> None:
    (tmp_path / "bad.toml").write_text("x = [", encoding="utf-8")
    for path in (tmp_path / "bad.toml", tmp_path / "missing.toml"):
        with pytest.raises(VeilleurError, match="invalid_config"):
            config.load(path, environ={})


class _EntryPoint:
    def __init__(self, name: str, value: Any) -> None:
        self.name, self._value = name, value

    def load(self) -> Any:
        if isinstance(self._value, Exception):
            raise self._value
        return self._value


def test_plugins_are_found_by_entry_point(monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
    good = FakeCollector(name="good")
    found = {
        "veilleur.collectors": [
            _EntryPoint("good", good),
            _EntryPoint("broken", ImportError("x")),
            _EntryPoint("misnamed", FakeCollector(name="other")),
            _EntryPoint("badschema", FakeCollector(name="badschema", schema={"oneOf": []})),
            _EntryPoint("Upper", FakeCollector(name="Upper")),
        ],
        "veilleur.filters": [],
        "veilleur.renderers": [],
    }
    monkeypatch.setattr(plugin_module, "entry_points", lambda group: found[group])
    installed = plugin_module.installed()
    assert list(installed.collectors) == ["good"]
    assert caplog.text.count("left out") == 4


def test_plugins_given_directly_are_checked() -> None:
    from veilleur.core.ports.plugins import Plugins

    with pytest.raises(ValueError):
        plugin_module.validated(Plugins({"x": FakeCollector(name="y")}, {}, {}))
    with pytest.raises(ValueError):
        plugin_module.validated(Plugins({"x": FakeCollector(name="x", schema={"type": "date"})}, {}, {}))


def test_worker_runs_jobs_when_woken(world: World) -> None:
    p = pairing.create_pairing(world.app.core, "desk 1")
    world.collector.set("news", ("a", {"title": "A"}))
    worker = Worker(world.app.core, period=3600)
    worker.start()
    try:
        subscriptions.put_subscription(
            world.app.core, p.key_id, "a" * 32, 0, {"collector": "fake", "params": {"topic": "news"}}
        )
        worker.wake()
        for _ in range(200):
            if world.app.store.package_bounds(p.key_id, "a" * 32).last:
                break
            import time

            time.sleep(0.01)
    finally:
        worker.stop()
    assert world.app.store.package_bounds(p.key_id, "a" * 32).last == 1
