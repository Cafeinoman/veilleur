# SPDX-License-Identifier: EUPL-1.2
"""Notifiers `ntfy` and `webhook` (spec EF-52) and their configuration: counts only, never content."""

from __future__ import annotations

import hashlib
import hmac
import json
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path

import pytest

from veilleur.adapters.http import OfflineHttpClient
from veilleur.adapters.notifiers import NotificationFailed, NtfyNotifier, WebhookNotifier, message, sign
from veilleur.apps.server import cli
from veilleur.apps.server import config as config_module
from veilleur.apps.server.context import App, configured_notifiers, open_app
from veilleur.core.domain.errors import VeilleurError
from veilleur.core.ports.plugins import NotificationTarget, RoundCounts
from veilleur.core.services import round
from veilleur.core.services.subscriptions import put_subscription
from veilleur_protocol import decode_pairing_code

from .fakes import FakeClock, FakeCollector, plugins

TARGET = NotificationTarget("0123456789abcdef", "a" * 32)


class Recorder:
    def __init__(self, status: int = 200) -> None:
        self.status = status
        self.posts: list[tuple[str, bytes, dict[str, str]]] = []

    def __call__(self, url: str, body: bytes, headers: Mapping[str, str]) -> int:
        self.posts.append((url, body, dict(headers)))
        return self.status


def test_ntfy_posts_counts_to_the_pairing_topic() -> None:
    poster = Recorder()
    NtfyNotifier("http://127.0.0.1:2586/", "tk", "en", poster).notify(TARGET, RoundCounts(2, 5, 1))
    url, body, headers = poster.posts[0]
    assert url == "http://127.0.0.1:2586/" + "a" * 32
    assert body.decode() == "2 new reports, 5 new items, 1 source failing for more than two days"
    assert headers["Authorization"] == "Bearer tk"


def test_ntfy_message_in_french() -> None:
    assert message(RoundCounts(1, 0, 0), "fr") == "1 nouveau rapport, 0 élément nouveau"


def test_ntfy_without_token_and_failure() -> None:
    poster = Recorder(status=403)
    with pytest.raises(NotificationFailed):
        NtfyNotifier("https://ntfy.example.org", None, "en", poster).notify(TARGET, RoundCounts(1, 1, 0))
    assert "Authorization" not in poster.posts[0][2]


def test_webhook_is_signed_and_carries_counts_only() -> None:
    poster = Recorder()
    key = b"k" * 32
    now = datetime(2026, 11, 18, 6, 0, tzinfo=UTC)
    WebhookNotifier("https://hooks.example.org/v", key, lambda: now, poster).notify(TARGET, RoundCounts(3, 4, 0))
    url, body, headers = poster.posts[0]
    assert url == "https://hooks.example.org/v"
    assert json.loads(body) == {
        "event": "round",
        "topic": "a" * 32,
        "reports": 3,
        "new_items": 4,
        "failing_sources": 0,
        "sent_at": "2026-11-18T06:00:00Z",
    }
    expected = "sha256=" + hmac.new(key, body, hashlib.sha256).hexdigest()
    assert headers["X-Veilleur-Signature"] == expected == sign(key, body)
    assert headers["Content-Type"] == "application/json"


def _config(tmp_path: Path, extra: str) -> config_module.Config:
    path = tmp_path / "config.toml"
    path.write_text(f'state_dir = "{tmp_path / "state"}"\npublic_url = "https://veille.example.org"\n{extra}')
    return config_module.load(path, environ={})


def test_configuration_of_notifiers(tmp_path: Path) -> None:
    (tmp_path / "publish").write_text("pub-token\n")
    config = _config(
        tmp_path,
        f'[ntfy]\nurl = "http://127.0.0.1:2586"\npublic_url = "https://veille.example.org:8443"\n'
        f'token_file = "{tmp_path / "publish"}"\n[webhook]\nurl = "https://hooks.example.org/v"\n',
    )
    assert config.ntfy is not None and config.ntfy.public_url == "https://veille.example.org:8443"
    config.state_dir.mkdir(mode=0o700)
    found = configured_notifiers(config)
    assert [n.name for n in found] == ["ntfy", "webhook"]
    ntfy, webhook = found
    assert isinstance(ntfy, NtfyNotifier) and ntfy.token == "pub-token"
    key_file = config.state_dir / "webhook.key"
    assert key_file.stat().st_mode & 0o777 == 0o600
    assert isinstance(webhook, WebhookNotifier) and webhook.key == key_file.read_bytes()
    assert configured_notifiers(config)[1].key == webhook.key  # type: ignore[attr-defined]


@pytest.mark.parametrize(
    "extra",
    [
        '[ntfy]\nurl = "ftp://x"\n',
        '[ntfy]\nurl = "http://127.0.0.1:2586"\npublic_url = "http://insecure.example.org"\n',
        '[ntfy]\nurl = "https://ntfy.example.org"\ntoken_file = "relative"\n',
        '[ntfy]\nurl = "https://ntfy.example.org"\ntoken = "inline secrets are refused"\n',
        '[webhook]\nkey_file = "/x"\n',
        "offline = 1\n",
    ],
)
def test_bad_notifier_configuration(tmp_path: Path, extra: str) -> None:
    with pytest.raises(VeilleurError):
        _config(tmp_path, extra)


def test_missing_secret_file(tmp_path: Path) -> None:
    config = _config(tmp_path, f'[ntfy]\nurl = "https://ntfy.example.org"\ntoken_file = "{tmp_path / "absent"}"\n')
    with pytest.raises(VeilleurError) as caught:
        configured_notifiers(config)
    assert caught.value.params == {"member": "ntfy.token_file"}


def test_pairing_code_carries_ntfy(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    (tmp_path / "read").write_text("read-token")
    config = _config(
        tmp_path,
        f'[ntfy]\nurl = "http://127.0.0.1:2586"\npublic_url = "https://veille.example.org:8443"\n'
        f'client_token_file = "{tmp_path / "read"}"\n',
    )
    collector = FakeCollector()
    poster = Recorder()

    def opener(c: config_module.Config) -> App:
        app = open_app(
            c, plugins=plugins(collector, FakeCollector(name="fetch")), clock=FakeClock(), http=OfflineHttpClient()
        )
        assert isinstance(app.core.notifiers[0], NtfyNotifier)
        app.core.notifiers[0].poster = poster
        return app

    assert cli.main(["--config", str(config.source), "pairing", "new", "--label", "desk 1"], opener=opener) == 0
    code = decode_pairing_code(capsys.readouterr().out.strip().splitlines()[-1])
    assert code.ntfy is not None
    assert code.ntfy.url == "https://veille.example.org:8443"
    assert code.ntfy.token == "read-token"
    assert len(code.ntfy.topic) == 32
    app = opener(config)
    try:
        put_subscription(app.core, code.key_id, "0" * 32, 0, {"collector": "fake", "params": {"topic": "t"}})
        collector.set("t", ("x", {"title": "secret title"}))
        round.run_round(app.core)
    finally:
        app.close()
    assert [p[0] for p in poster.posts] == ["http://127.0.0.1:2586/" + code.ntfy.topic]
    assert b"secret" not in poster.posts[0][1]


def test_failing_notifier_does_not_stop_the_round(tmp_path: Path) -> None:
    config = _config(tmp_path, "")
    collector = FakeCollector()
    poster = Recorder(status=500)
    app = open_app(
        config,
        plugins=plugins(collector, FakeCollector(name="fetch")),
        clock=FakeClock(),
        http=OfflineHttpClient(),
        notifiers=[NtfyNotifier("http://127.0.0.1", None, "en", poster)],
    )
    try:
        from veilleur.core.services.pairing import create_pairing

        pairing = create_pairing(app.core, "desk")
        put_subscription(app.core, pairing.key_id, "0" * 32, 0, {"collector": "fake", "params": {"topic": "t"}})
        summary = round.run_round(app.core)
        assert summary.states == 1 and summary.notifications_failed == 1
    finally:
        app.close()
