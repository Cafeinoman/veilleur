# SPDX-License-Identifier: EUPL-1.2
"""Independent checks of batch G4: renderings (EF-43) and the reference receiver (EF-50, EF-51, spec §10)."""

from __future__ import annotations

import hashlib
import http.client
import io
import json
import re
import ssl
import subprocess
import sys
from collections.abc import Iterator
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

import pytest

from tests.receiver.test_end_to_end import (
    OTHER,
    UID,
    Bench,
    WsgiTransport,
    _pair,
    _rotate,
    _sealed,
    _two_reports,
)
from tests.server.fakes import make_world
from veilleur.adapters.renderers import MAX_TEXT, MAX_VALUE, HtmlRenderer, MarkdownRenderer
from veilleur.apps.server import cli as server_cli
from veilleur.apps.server.wsgi import Api, RateLimiter
from veilleur.core.domain.model import Change, CollectedItem, ItemChange, Kind
from veilleur.core.ports.plugins import Plugins, Renderer, ReportView
from veilleur.core.services import pairing
from veilleur_protocol import PairingCode
from veilleur_protocol.envelope import Kind as EnvelopeKind
from veilleur_receive import cli
from veilleur_receive import receiver as receiver_module
from veilleur_receive.deposit import deposit
from veilleur_receive.transport import Reply, _connect

NOW = datetime(2026, 11, 17, 6, 0, tzinfo=UTC)


@pytest.fixture(name="bench")
def _bench(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Bench]:
    world = make_world(tmp_path / "server")
    plugins = world.app.core.plugins
    renderers: dict[str, Renderer] = {"markdown": MarkdownRenderer(), "html": HtmlRenderer()}
    core = replace(world.app.core, plugins=Plugins(plugins.collectors, plugins.filters, renderers))
    created = pairing.create_pairing(core, "desk 1")
    code = PairingCode("https://veille.example.org", created.key_id, created.secret, core.sealer.public_key).encode()
    transport = WsgiTransport(Api(core, limiter=RateLimiter(limit=100_000)))
    result = Bench(world, core, created, code, transport, tmp_path / "receiver", tmp_path / "reports")
    assert _pair(result, monkeypatch) == 0
    yield result
    world.app.close()


def _export(bench: Bench, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, uid: str, target: Path) -> None:
    monkeypatch.setattr(bench.world.app.store, "close", lambda: None)
    argv = ["--lang", "en", "--state-dir", str(tmp_path / "server"), "export", uid, "--folder", str(target)]
    assert server_cli.main(argv, opener=lambda config: bench.world.app) == 0


def _view(*items: ItemChange) -> ReportView:
    return ReportView("ab" * 16, 7, Kind.DELTA, NOW, NOW - timedelta(days=1), NOW, items, ())


def _item(key: str = "k", url: str | None = None, **fields: Any) -> ItemChange:
    return ItemChange(key, Change.NEW, "0" * 64, fields, NOW, url)


def _md(report: ReportView, language: str = "en") -> str:
    return MarkdownRenderer().render(report, language)["report.md"].decode("utf-8")


def _html(report: ReportView, language: str = "en") -> str:
    return HtmlRenderer().render(report, language)["report.html"].decode("utf-8")


class _Page(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.tags: list[tuple[str, dict[str, str | None]]] = []
        self.link_text: list[str] = []
        self._in_link = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.tags.append((tag, dict(attrs)))
        self._in_link = tag == "a"

    def handle_endtag(self, tag: str) -> None:
        if tag == "a":
            self._in_link = False

    def handle_data(self, data: str) -> None:
        if self._in_link:
            self.link_text.append(data)


def _parsed(text: str) -> _Page:
    page = _Page()
    page.feed(text)
    return page


# --- Renderings -------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("mark", ["‮", "‭", "⁦", "‏", "\x90", "\x9b"])
def test_an_address_keeps_no_control_or_direction_character(mark: str) -> None:
    """Spec §10 (G4): every collected value loses its control and direction characters, the address included."""
    report = _view(_item(url=f"https://example.org/{mark}gnp.exe", title="T"))
    assert mark not in _md(report)
    assert mark not in _html(report)


@pytest.mark.xfail(strict=True, reason="minor: U+061C (arabic letter mark) is a direction mark that is not removed")
def test_the_arabic_letter_mark_is_removed() -> None:
    assert "؜" not in _html(_view(_item(title="a؜b")))


@pytest.mark.xfail(strict=True, reason="minor: an address is neither shortened nor counted against the rendering cap")
def test_addresses_count_against_the_cap_of_a_rendering() -> None:
    """Spec §10 (G4): a rendering is capped at 2 million characters of items."""
    items = [_item(f"k{n}", url="https://example.org/" + "a" * 200_000) for n in range(30)]
    assert len(_html(_view(*items))) < 2 * MAX_TEXT + 100_000


@pytest.mark.xfail(strict=True, reason="minor: the text of a link is not shortened to 4,000 characters")
def test_the_text_of_a_link_is_shortened() -> None:
    page = _parsed(_html(_view(_item(url="https://example.org/" + "a" * (MAX_VALUE * 2)))))
    assert all(len(text) <= MAX_VALUE + 1 for text in page.link_text)


@pytest.mark.parametrize(
    "value",
    [
        "<script>alert(1)</script>",
        '"><img src=x onerror=alert(1)>',
        "</style><svg onload=alert(1)>",
        "<a href='javascript:alert(1)'>x</a>",
        "<iframe src=https://example.net/></iframe>",
        "<link rel=stylesheet href=https://example.net/a.css>",
    ],
)
def test_no_collected_value_adds_a_tag_or_an_attribute(value: str) -> None:
    report = _view(_item(value, url=value, title=value, **{value: value}))
    allowed = {"html", "head", "meta", "title", "style", "body", "h1", "h2", "h3", "p", "strong", "dl", "dt", "dd"}
    allowed |= {"footer", "ul", "li", "a"}
    page = _parsed(_html(report))
    assert {tag for tag, _attrs in page.tags} <= allowed
    assert not [tag for tag, attrs in page.tags if tag == "a"], "this address is not a link"
    assert not [name for _tag, attrs in page.tags for name in attrs if name.startswith("on")]


@pytest.mark.parametrize(
    "url",
    [
        "javascript:alert(1)",
        "data:text/html,x",
        "file:///etc/passwd",
        "//example.net/x",
        "https://example.org/>)[x](javascript:alert(1)",
        "https://example.org/ x",
        "https://",
    ],
)
def test_only_a_clean_http_address_becomes_a_link(url: str) -> None:
    report = _view(_item(url=url, title="T"))
    assert not [tag for tag, _attrs in _parsed(_html(report)).tags if tag == "a"]
    assert "](<" not in _md(report)


@pytest.mark.parametrize("language", ["en", "fr"])
def test_the_page_is_self_contained_in_both_languages(language: str) -> None:
    text = _html(_view(_item(url="https://example.org/a", title="T")), language)
    page = _parsed(text)
    assert f'lang="{language}"' in text
    assert not [tag for tag, _attrs in page.tags if tag in {"script", "img", "link", "iframe", "object", "embed"}]
    assert not [name for _tag, attrs in page.tags for name in attrs if name in {"src", "srcset", "action"}]
    assert not re.search(r"url\(|@import", text)
    policy = [attrs["content"] for tag, attrs in page.tags if attrs.get("http-equiv") == "Content-Security-Policy"]
    assert policy and "default-src 'none'" in str(policy[0])


# --- Delivery by folder (EF-51) ---------------------------------------------------------------------------------


def test_a_rotation_does_not_block_another_subscription_read_from_a_folder(
    bench: Bench, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """EF-51 and ES-05: a member without network access follows a key rotation without being paired again.

    Over HTTP such a package is replaced by a `state`; a folder offers no way to ask for one.
    """
    bench.world.collector.set("news", ("a", {"title": "A"}))
    bench.world.collector.set("other", ("x", {"title": "X"}))
    bench.subscribe(UID, "news")
    bench.subscribe(OTHER, "other")
    bench.round()  # package 1 of each subscription, signed by the old key
    bench.core = _rotate(bench)
    bench.world.collector.set("news", ("a", {"title": "A"}), ("b", {"title": "B"}))
    bench.round()  # package 2 of UID, signed by the new key
    source = tmp_path / "usb"
    _export(bench, monkeypatch, tmp_path, UID, source)
    _export(bench, monkeypatch, tmp_path, OTHER, source)
    capsys.readouterr()
    code = bench.receive("pull", "--folder", str(bench.folder), "--from", str(source))
    err = capsys.readouterr().err
    assert code == 0, err
    assert bench.filed(OTHER) == ["00000001-state"]


def test_a_new_export_gets_a_subscription_past_a_rotation(
    bench: Bench, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The administrator has no other means: `veilleur export` only writes a `state` once packages are purged."""
    bench.world.collector.set("news", ("a", {"title": "A"}))
    bench.world.collector.set("other", ("x", {"title": "X"}))
    bench.subscribe(UID, "news")
    bench.subscribe(OTHER, "other")
    bench.round()
    bench.core = _rotate(bench)
    bench.world.collector.set("news", ("a", {"title": "A"}), ("b", {"title": "B"}))
    bench.round()
    first = tmp_path / "usb1"
    _export(bench, monkeypatch, tmp_path, UID, first)
    assert bench.receive("pull", "--folder", str(bench.folder), "--from", str(first)) == 0  # the key is adopted
    bench.world.collector.set("other", ("x", {"title": "X"}), ("y", {"title": "Y"}))
    bench.round()
    second = tmp_path / "usb2"
    _export(bench, monkeypatch, tmp_path, OTHER, second)
    assert bench.receive("pull", "--folder", str(bench.folder), "--from", str(second)) == 0
    assert bench.last(OTHER) == 2


def test_a_hostile_address_reaches_the_filed_report_unchanged_end_to_end(bench: Bench) -> None:
    """The same defect through the whole chain: collector, package, receiver."""
    bench.world.collector.items["news"] = [
        CollectedItem({"title": "T"}, key="k", url="https://example.org/\u202egnp.exe")
    ]
    bench.subscribe(renderings=["markdown", "html"])
    bench.round()
    assert bench.pull() == 0
    report = bench.folder / UID / "00000001-state"
    assert "\u202e" not in (report / "report.html").read_text("utf-8")
    assert "\u202e" not in (report / "report.md").read_text("utf-8")


def test_a_folder_pairing_reads_an_export_end_to_end(
    bench: Bench, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    code = PairingCode("folder:", bench.pairing.key_id, bench.pairing.secret, bench.core.sealer.public_key).encode()
    state = tmp_path / "folder-state"
    monkeypatch.setattr("sys.stdin", io.StringIO(code + "\n"))
    assert cli.main(["--lang", "en", "--state-dir", str(state), "pair"]) == 0
    _two_reports(bench)
    source = tmp_path / "usb"
    _export(bench, monkeypatch, tmp_path, UID, source)
    argv = ["--lang", "en", "--state-dir", str(state), "pull", "--folder", str(bench.folder), "--from", str(source)]
    assert cli.main(argv) == 0
    assert bench.filed() == ["00000001-state", "00000002-delta"]


def test_an_export_after_a_purge_is_covered_by_its_state(
    bench: Bench, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _two_reports(bench)
    bench.world.clock.advance(days=91)
    bench.round()
    bench.world.collector.set("news", ("a", {"title": "A"}), ("c", {"title": "C"}))
    bench.round()
    source = tmp_path / "usb"
    _export(bench, monkeypatch, tmp_path, UID, source)
    assert bench.receive("pull", "--folder", str(bench.folder), "--from", str(source)) == 0
    assert any(name.endswith("-state") for name in bench.filed())
    assert bench.last() == bench.core.store.package_bounds(bench.pairing.key_id, UID).last


def test_a_symbolic_link_in_the_source_folder_is_not_followed(bench: Bench, tmp_path: Path) -> None:
    outside = tmp_path / "outside.veil"
    outside.write_bytes(_sealed(bench, 1, EnvelopeKind.STATE))
    source = tmp_path / "usb"
    source.mkdir()
    (source / "1.veil").symlink_to(outside)
    assert bench.receive("pull", "--folder", str(bench.folder), "--from", str(source)) == 0
    assert bench.filed() == []


# --- What is filed ----------------------------------------------------------------------------------------------


def test_the_filed_items_are_those_the_manifest_vouches_for(bench: Bench) -> None:
    fields = {"title": "Élément “é”", "n": 1.5, "nested": {"b": 1, "a": [1, 2]}}
    bench.world.collector.set("news", ("clé é", fields))
    bench.subscribe(language="fr", renderings=["markdown", "html"])
    bench.round()
    assert bench.pull() == 0
    report = bench.folder / UID / "00000001-state"
    manifest = json.loads((report / "manifest.json").read_text("utf-8"))
    for name in ("items.jsonl", "report.md", "report.html"):
        assert hashlib.sha256((report / name).read_bytes()).hexdigest() == manifest["files"][name]


def test_an_interrupted_pull_resumes_without_loss(bench: Bench, monkeypatch: pytest.MonkeyPatch) -> None:
    _two_reports(bench)
    real = deposit
    calls: list[int] = []

    def failing(folder: Path, opened: Any) -> Path:
        calls.append(opened.seq)
        if len(calls) == 2:
            raise OSError("disk full")
        return real(folder, opened)

    monkeypatch.setattr(receiver_module, "deposit", failing)
    assert bench.pull() == 1
    assert bench.last() == 1 and bench.filed() == ["00000001-state"]
    monkeypatch.setattr(receiver_module, "deposit", real)
    assert bench.pull() == 0
    assert bench.last() == 2 and bench.filed() == ["00000001-state", "00000002-delta"]


# --- A server that cannot be trusted ----------------------------------------------------------------------------


def _listing(last: int, **packages: bytes) -> Reply:
    entries = [
        {"seq": int(seq[1:]), "size": len(data), "sha256": hashlib.sha256(data).hexdigest()}
        for seq, data in packages.items()
    ]
    return Reply(200, json.dumps({"packages": entries, "oldest": None, "last": last}).encode())


def test_a_package_served_under_another_number_is_refused(
    bench: Bench, capsys: pytest.CaptureFixture[str]
) -> None:
    bench.subscribe()
    data = _sealed(bench, 2, EnvelopeKind.DELTA)
    bench.transport.replies[f"/v1/subscriptions/{UID}/reports?after=0"] = _listing(1, n1=data)
    bench.transport.replies[f"/v1/subscriptions/{UID}/reports/1"] = Reply(200, data)
    assert bench.pull() == 1
    assert "seq_mismatch" in capsys.readouterr().err and bench.filed() == [] and bench.last() == 0


def test_a_package_of_another_subscription_is_refused(bench: Bench, capsys: pytest.CaptureFixture[str]) -> None:
    bench.subscribe()
    data = _sealed(bench, 1, EnvelopeKind.STATE, uid=OTHER)
    bench.transport.replies[f"/v1/subscriptions/{UID}/reports?after=0"] = _listing(1, n1=data)
    bench.transport.replies[f"/v1/subscriptions/{UID}/reports/1"] = Reply(200, data)
    assert bench.pull() == 1
    assert "uid_mismatch" in capsys.readouterr().err and bench.filed() == [] and bench.filed(OTHER) == []


def test_only_a_state_covers_a_gap(bench: Bench, capsys: pytest.CaptureFixture[str]) -> None:
    bench.subscribe()
    bench.transport.replies[f"/v1/subscriptions/{UID}/reports?after=0"] = _listing(3)
    bench.transport.replies[f"/v1/subscriptions/{UID}/state"] = Reply(200, _sealed(bench, 3, EnvelopeKind.DELTA))
    assert bench.pull() == 1
    assert "kind_mismatch" in capsys.readouterr().err and bench.filed() == [] and bench.last() == 0


def test_a_state_that_does_not_move_forward_is_refused(bench: Bench, capsys: pytest.CaptureFixture[str]) -> None:
    _two_reports(bench)
    assert bench.pull() == 0
    bench.transport.replies[f"/v1/subscriptions/{UID}/reports?after=2"] = _listing(3)
    bench.transport.replies[f"/v1/subscriptions/{UID}/state"] = Reply(200, _sealed(bench, 2, EnvelopeKind.STATE))
    assert bench.pull() == 1
    assert "seq_mismatch" in capsys.readouterr().err and bench.last() == 2


@pytest.mark.xfail(
    strict=True, raises=RecursionError, reason="out of spec: a very deep JSON answer ends in a traceback"
)
def test_a_very_deep_answer_is_a_refusal(bench: Bench, capsys: pytest.CaptureFixture[str]) -> None:
    bench.transport.replies["/v1/subscriptions"] = Reply(200, b"[" * 200_000)
    assert bench.pull() == 1
    assert "bad_response" in capsys.readouterr().err


# --- Command line -----------------------------------------------------------------------------------------------


@pytest.mark.xfail(strict=True, reason="minor: a pairing code that is not UTF-8 ends in a traceback")
def test_a_pairing_code_that_is_not_text_is_refused_cleanly(tmp_path: Path) -> None:
    done = subprocess.run(
        [sys.executable, "-m", "veilleur_receive", "--lang", "en", "--state-dir", str(tmp_path / "s"), "pair"],
        input=b"\xff\xfe\n",
        capture_output=True,
        check=False,
        env={"PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"},
    )
    assert done.returncode == 1
    assert b"Traceback" not in done.stderr


@pytest.mark.xfail(strict=True, reason="out of spec: a code given as an argument is refused but echoed on stderr")
def test_a_code_given_as_an_argument_is_not_repeated(bench: Bench, capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit):
        cli.main(["--lang", "en", "--state-dir", str(bench.state_dir), "pair", bench.code])
    assert bench.code not in capsys.readouterr().err


def test_the_secret_is_never_printed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, bench: Bench) -> None:
    captured = io.StringIO()
    monkeypatch.setattr("sys.stdout", captured)
    monkeypatch.setattr("sys.stderr", captured)
    monkeypatch.setattr("sys.stdin", io.StringIO(bench.code + "\n"))
    assert cli.main(["--lang", "en", "--state-dir", str(tmp_path / "second"), "pair"]) == 0
    assert bench.code not in captured.getvalue()
    assert bench.pairing.secret.hex() not in captured.getvalue()


def test_the_french_help_and_errors_are_french(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit):
        cli.main(["--lang", "fr", "pull", "--help"])
    out = capsys.readouterr().out
    assert "utilisation" in out
    for english in ("usage:", "options:", "show this help", "where to file", "read the packages"):
        assert english not in out
    with pytest.raises(SystemExit):
        cli.main(["--lang", "fr", "pull"])
    err = capsys.readouterr().err
    assert "the following arguments" not in err and "error:" not in err


def test_the_receiver_runs_without_the_server_package() -> None:
    script = "import sys; sys.modules['veilleur'] = None; import veilleur_receive.cli"
    subprocess.run([sys.executable, "-c", script], check=True, capture_output=True)


def test_the_real_connection_checks_certificates() -> None:
    connection = _connect("veille.example.org", None)
    assert isinstance(connection, http.client.HTTPSConnection)
    context = connection._context  # type: ignore[attr-defined]
    assert context.verify_mode == ssl.CERT_REQUIRED and context.check_hostname
