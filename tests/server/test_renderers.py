# SPDX-License-Identifier: EUPL-1.2
"""Renderings `markdown` and `html` (EF-43): both languages, hostile content, limits, and their place in a package."""

from __future__ import annotations

import re
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from html.parser import HTMLParser
from typing import Any

import pytest

from veilleur.adapters import plugins as plugin_loader
from veilleur.adapters.renderers import MAX_TEXT, MAX_VALUE, HtmlRenderer, MarkdownRenderer
from veilleur.core.domain.model import Change, ItemChange, Kind, SourceStatus
from veilleur.core.ports.plugins import Plugins, Renderer, ReportView
from veilleur.core.ports.sealer import PackageSpec, PackageTooLarge
from veilleur.core.services import jobs, pairing, subscriptions
from veilleur.core.services import round as rounds
from veilleur.core.services.context import Core
from veilleur_protocol import open_package

from .fakes import World

NOW = datetime(2026, 11, 17, 6, 0, tzinfo=UTC)
UID = "ab" * 16


def change(
    key: str, kind: Change = Change.NEW, url: str | None = None, extra: dict[str, Any] | None = None, **fields: Any
) -> ItemChange:
    return ItemChange(key, kind, "0" * 64, {**fields, **(extra or {})}, NOW, url)


def view(*items: ItemChange, kind: Kind = Kind.DELTA, sources: tuple[SourceStatus, ...] = ()) -> ReportView:
    return ReportView(UID, 7, kind, NOW, NOW - timedelta(days=1), NOW, items, sources)


def markdown(report: ReportView, language: str = "en") -> str:
    return MarkdownRenderer().render(report, language)["report.md"].decode("utf-8")


def page(report: ReportView, language: str = "en") -> str:
    return HtmlRenderer().render(report, language)["report.html"].decode("utf-8")


class _Tags(HTMLParser):
    """Every start tag of a page, with its attributes."""

    def __init__(self) -> None:
        super().__init__()
        self.tags: list[tuple[str, dict[str, str | None]]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.tags.append((tag, dict(attrs)))


def tags(text: str) -> list[tuple[str, dict[str, str | None]]]:
    parser = _Tags()
    parser.feed(text)
    return parser.tags


REPORT = view(
    change("a", title="First", summary="Text", url="https://example.org/a"),
    change("b", Change.CHANGED, title="Second"),
    change("c", Change.GONE, title="Third"),
    sources=(
        SourceStatus("c1", "rss", NOW, NOW, None),
        SourceStatus("c2", "page", NOW, NOW - timedelta(days=3), "http_500"),
        SourceStatus("c3", "json_api", NOW, None, "network_unavailable"),
        SourceStatus("c4", "custom", None, None, None),
    ),
)


def test_markdown_in_english() -> None:
    text = markdown(REPORT)
    assert text.startswith("# Report 7: changes since the previous report\n")
    assert "Period: from 2026\\-11\\-16 06:00 UTC to 2026\\-11\\-17 06:00 UTC" in text
    assert "**1 new item, 1 changed item, 1 gone item**" in text
    assert text.index("## New items") < text.index("## Changed items") < text.index("## Gone items")
    assert "### First" in text and "- summary: Text" in text
    assert "rss: working, last success" in text
    assert "page: failing \\(http\\_500\\), last success 2026\\-11\\-14 06:00 UTC" in text
    assert "json\\_api: failing \\(network\\_unavailable\\), last success never" in text
    assert "custom: not collected yet" in text


def test_html_in_french() -> None:
    text = page(REPORT, "fr")
    assert '<html lang="fr">' in text
    assert "<h1>Rapport 7 : changements depuis le rapport précédent</h1>" in text
    assert "1 élément nouveau, 1 élément modifié, 1 élément disparu" in text
    assert "<h2>Nouveaux éléments</h2>" in text and "<h2>Sources</h2>" in text
    assert "page : en panne (http_500), dernière réussite 2026-11-14 06:00 UTC" in text
    assert "Changes since" not in text and "New items" not in text


def test_markdown_in_french_uses_the_french_plural() -> None:
    text = markdown(view(change("a"), change("b")), "fr")
    assert "2 éléments nouveaux, 0 élément modifié, 0 élément disparu" in text


@pytest.mark.parametrize(
    ("kind", "english", "french"),
    [
        (Kind.DELTA, "changes since the previous report", "changements depuis le rapport précédent"),
        (Kind.STATE, "everything currently in force", "tout ce qui est en vigueur"),
        (Kind.HISTORY, "catch-up since a date", "rattrapage depuis une date"),
    ],
)
def test_every_kind_has_its_title(kind: Kind, english: str, french: str) -> None:
    assert english in page(view(kind=kind)) and french in page(view(kind=kind), "fr")


def test_a_report_without_period_start_or_item() -> None:
    report = replace(view(kind=Kind.STATE), period_from=None)
    assert "Period: until 2026-11-17 06:00 UTC" in page(report)
    assert "No item in this report." in page(report) and "Aucun élément dans ce rapport." in page(report, "fr")


def test_an_unknown_language_falls_back_to_english() -> None:
    assert '<html lang="en">' in page(REPORT, "de")


def test_the_page_holds_no_script_and_loads_nothing() -> None:
    found = tags(page(REPORT))
    names = {name for name, _ in found}
    assert not names & {"script", "img", "iframe", "object", "embed", "link", "form", "base", "video", "audio"}
    policy = next(a["content"] for n, a in found if n == "meta" and a.get("http-equiv") == "Content-Security-Policy")
    assert policy is not None and "default-src 'none'" in policy
    assert not any(attr.startswith("on") for _, attrs in found for attr in attrs)


HOSTILE = '<script>alert(1)</script><img src=x onerror=alert(2)>"\'&amp;'


def test_html_escapes_every_value() -> None:
    report = view(
        change(HOSTILE, url=f"https://example.org/{HOSTILE}", title=HOSTILE, extra={HOSTILE: HOSTILE}),
        sources=(SourceStatus("c", HOSTILE, NOW, NOW, HOSTILE),),
    )
    text = page(report)
    found = tags(text)
    assert not {"script", "img"} & {name for name, _ in found}
    assert "<script>alert" not in text and "&lt;script&gt;" in text


@pytest.mark.parametrize(
    "url",
    [
        "javascript:alert(1)",
        "JaVaScRiPt:alert(1)",
        "data:text/html,<script>alert(1)</script>",
        "file:///etc/passwd",
        "vbscript:x",
        "//example.org/a",
        "https://",
        "https:///path",
        "https://example.org/a b",
        "https://example.org/a\nb",
        'https://example.org/"onclick="x',
        "https://[bad/",
    ],
)
def test_only_a_well_formed_http_address_is_a_link(url: str) -> None:
    report = view(change("a", url=url, title="T"))
    assert not [attrs for name, attrs in tags(page(report)) if name == "a"]
    assert "](<" not in markdown(report)


def test_an_address_that_is_not_a_link_stays_readable_as_text() -> None:
    assert "javascript:alert(1)" in page(view(change("a", url="javascript:alert(1)")))


def test_an_http_address_is_a_link_that_tells_nothing_to_its_target() -> None:
    url = "https://example.org/a?x=1&y=(2)"
    report = view(change("a", url=url))
    (link,) = [attrs for name, attrs in tags(page(report)) if name == "a"]
    assert link["href"] == url and link["rel"] == "noopener noreferrer"
    assert f"](<{url}>)" in markdown(report)


@pytest.mark.parametrize(
    "value",
    [
        "# heading",
        "line\n# heading",
        "line\r\n\r\n## heading",
        "[link](https://example.org)",
        "![image](https://example.org/x.png)",
        "<script>alert(1)</script>",
        "`code`",
        "*bold* _em_ ~~gone~~",
        "| table |",
        "- list",
        "1. list",
        "&lt;script&gt;",
    ],
)
def test_markdown_values_cannot_change_the_structure(value: str) -> None:
    text = markdown(view(change("a", title=value, body=value, extra={value: value})))
    headings = [line for line in text.splitlines() if line.startswith("#")]
    assert len(headings) == 3, headings  # the title, the section and the item
    body = "\n".join(text.splitlines()[1:])
    assert not re.search(r"(?<!\\)[\[<`|]", body.replace("](<", "")), body
    assert "&lt;" not in body.replace("\\&lt;", "")


def test_control_characters_and_direction_overrides_are_removed() -> None:
    value = "a\x1b[31mb\x00c\u202ed\u2066e\ud800f"
    report = view(change("k", title=value, body=value))
    for text in (page(report), markdown(report)):
        assert not re.search("[\x00\x1b\u202e\u2066\ud800]", text)


def test_a_lone_surrogate_does_not_lose_the_rendering() -> None:
    assert MarkdownRenderer().render(view(change("k", title="\udfff")), "en")["report.md"]


def test_non_text_values_are_shown_as_json() -> None:
    text = page(view(change("a", count=3, on=True, none=None, nested={"b": [1, "é"]})))
    assert "<dd>3</dd>" in text and "<dd>true</dd>" in text and "<dd>null</dd>" in text
    assert "<dd>{&quot;b&quot;: [1, &quot;é&quot;]}</dd>" in text


def test_the_heading_falls_back_on_name_then_key() -> None:
    assert "<h3>Named</h3>" in page(view(change("a", name="Named")))
    assert "<h3>the-key</h3>" in page(view(change("the-key", title="  ", other=1)))
    assert "<h3>the-key</h3>" in page(view(change("the-key", title=12)))


def test_long_values_are_shortened() -> None:
    text = page(view(change("a", body="x" * (MAX_VALUE + 50))))
    assert "x" * MAX_VALUE + "…" in text and "x" * (MAX_VALUE + 1) not in text
    assert "items.jsonl" in text


def test_a_huge_report_is_cut_and_says_so() -> None:
    count = MAX_TEXT // MAX_VALUE + 5
    items = [change(f"k{i:06d}", body="x" * MAX_VALUE) for i in range(count)]
    text = page(view(*items))
    assert re.search(r"\d+ more items are only in items\.jsonl\.", text)
    assert f"{count} new items" in text  # the summary still counts everything
    assert len(text.encode()) < 7 * MAX_TEXT


def test_a_rendering_is_reproducible() -> None:
    assert page(REPORT) == page(REPORT) and markdown(REPORT) == markdown(REPORT)


def test_the_renderers_are_installed_plugins() -> None:
    assert set(plugin_loader.installed().renderers) >= {"markdown", "html"}


def _with_renderers(world: World) -> Core:
    plugins = world.app.core.plugins
    renderers: dict[str, Renderer] = {"markdown": MarkdownRenderer(), "html": HtmlRenderer()}
    return replace(world.app.core, plugins=Plugins(plugins.collectors, plugins.filters, renderers))


def test_renderings_reach_the_package_in_the_subscription_language(world: World) -> None:
    core = _with_renderers(world)
    created = pairing.create_pairing(core, "desk 1")
    world.collector.set("t", ("a", {"title": "Élément"}))
    document = {"collector": "fake", "params": {"topic": "t"}, "language": "fr", "renderings": ["markdown", "html"]}
    subscriptions.put_subscription(core, created.key_id, UID, 0, document)
    rounds.run_round(core)
    jobs.run_pending(core)
    data = world.app.store.get_package(created.key_id, UID, 1)
    assert data is not None
    opened = open_package(data, secret=created.secret, uid=UID, trusted_keys=[world.app.core.sealer.public_key])
    assert set(opened.renderings) == {"report.md", "report.html"}
    assert "Rapport 1" in opened.renderings["report.md"].decode()
    assert "Élément" in opened.renderings["report.html"].decode()


def test_a_package_too_large_with_its_renderings_is_sealed_without_them(world: World) -> None:
    core = _with_renderers(world)
    created = pairing.create_pairing(core, "desk 1")
    world.collector.set("t", ("a", {"title": "A"}))
    document = {"collector": "fake", "params": {"topic": "t"}, "renderings": ["html"]}
    subscriptions.put_subscription(core, created.key_id, UID, 0, document)
    sealer = core.sealer
    sealed: list[int] = []

    class Picky:
        public_key = sealer.public_key

        def seal_package(self, secret: bytes, spec: PackageSpec) -> bytes:
            sealed.append(len(spec.renderings))
            if spec.renderings:
                raise PackageTooLarge("too large")
            return sealer.seal_package(secret, spec)

        def open_subscription(self, secret: bytes, uid: str, body: bytes) -> tuple[int, dict[str, Any]]:
            return sealer.open_subscription(secret, uid, body)

    picky = replace(core, sealer=Picky())
    rounds.run_round(picky)
    jobs.run_pending(picky)
    assert sealed == [1, 0]
    data = world.app.store.get_package(created.key_id, UID, 1)
    assert data is not None
    assert open_package(data, secret=created.secret, uid=UID, trusted_keys=[sealer.public_key]).renderings == {}


@pytest.mark.parametrize("mark", ["\u202e", "\u2066", "\u200f", "\x90"])
def test_an_address_with_a_direction_or_control_character_is_no_link(mark: str) -> None:
    """Such a character makes an address read differently from where it leads: `gnp.exe` shown as `exe.png`."""
    report = view(change("k", url=f"https://example.org/{mark}gnp.exe", title="T"))
    for text in (markdown(report), page(report)):
        assert mark not in text
    assert "<a " not in page(report) and "](<" not in markdown(report)
    assert "gnp.exe" in page(report), "the address stays readable, as text"
