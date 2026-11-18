# SPDX-License-Identifier: EUPL-1.2
"""Provided renderings (cahier EF-43): `markdown` and `html`, in the subscription's language.

Everything in a report comes from third-party sources, so every value is treated as hostile: it is cleaned of control
characters, escaped for its format, and only an `http(s)` address becomes a link. The HTML page holds no script and
loads nothing; its content security policy forbids both, should escaping ever fail.

A rendering is optional and derived: long values are shortened and a huge report is cut, `items.jsonl` holds it all.
"""

from __future__ import annotations

import html
import json
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlsplit

from veilleur import i18n
from veilleur.core.domain.model import Change, ItemChange, Kind, SourceStatus
from veilleur.core.ports.plugins import ReportView

MAX_VALUE = 4000
"""Characters shown of one value."""
MAX_TEXT = 2_000_000
"""Characters of item content in one rendering; the items beyond it are counted, not shown."""
_TITLE_FIELDS = ("title", "name")
_UNSAFE = re.compile(r"[\x00-\x08\x0b-\x1f\x7f-\x9f\u200e\u200f\u202a-\u202e\u2066-\u2069\ud800-\udfff]")
"""Control characters, direction overrides (they make a text read differently from what it is), lone surrogates."""
_URL = re.compile(r"https?://[^\s<>\"\\\x00-\x1f\x7f]+", re.IGNORECASE)
_MARKDOWN = re.compile(r"([\\`*_{}\[\]()<>#+\-.!|~&])")
_STYLE = """
:root { color-scheme: light dark; }
body { font-family: system-ui, sans-serif; line-height: 1.5; margin: 0 auto; max-width: 48rem; padding: 1rem; }
h1 { font-size: 1.5rem; } h2 { font-size: 1.2rem; margin-top: 2rem; } h3 { font-size: 1rem; margin-bottom: .25rem; }
dl { display: grid; gap: .1rem 1rem; grid-template-columns: minmax(5rem, max-content) 1fr; margin: 0; }
dt { font-weight: 600; } dd { margin: 0; overflow-wrap: anywhere; white-space: pre-wrap; }
footer { font-size: .875rem; margin-top: 2rem; }
""".strip()
_POLICY = "default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'"


@dataclass(frozen=True)
class _Entry:
    heading: str
    url: str | None
    """An address safe to link to; another one stays among `rows`, as text."""
    rows: tuple[tuple[str, str], ...]


@dataclass(frozen=True)
class _Section:
    title: str
    entries: tuple[_Entry, ...]


@dataclass(frozen=True)
class _Page:
    """A report in words, independent of the format."""

    language: str
    title: str
    facts: tuple[str, ...]
    summary: str
    sections: tuple[_Section, ...]
    notes: tuple[str, ...]
    address_label: str
    sources_title: str
    sources: tuple[str, ...]
    footer: str


def _clean(text: str) -> str:
    return _UNSAFE.sub(" ", text.replace("\r\n", "\n").replace("\r", "\n"))


def _value(value: Any) -> str:
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, sort_keys=True)
    text = _clean(text)
    return text if len(text) <= MAX_VALUE else text[:MAX_VALUE] + "…"


def _safe_url(url: str | None) -> str | None:
    if url is None or _URL.fullmatch(url) is None:
        return None
    try:
        return url if urlsplit(url).hostname else None
    except ValueError:
        return None


def _time(moment: datetime) -> str:
    return moment.astimezone(UTC).strftime("%Y-%m-%d %H:%M UTC")


def _heading(item: ItemChange) -> tuple[str, str | None]:
    """What names the item, and the field it comes from."""
    for name in _TITLE_FIELDS:
        value = item.fields.get(name)
        if isinstance(value, str) and (text := " ".join(_value(value).split())):
            return text, name
    return " ".join(_value(item.key).split()) or "-", None


def _entry(item: ItemChange, key_label: str, address_label: str) -> _Entry:
    heading, used = _heading(item)
    url = _safe_url(item.url)
    rows = [(key_label, _value(item.key))]
    if item.url is not None and url is None:
        rows.append((address_label, _value(item.url)))
    rows += [(_value(name), _value(item.fields[name])) for name in sorted(item.fields) if name != used]
    return _Entry(heading, url, tuple(rows))


def _source_line(status: SourceStatus, _: Callable[[str], str]) -> str:
    collector = _clean(status.collector)
    if status.ok and status.last_success is not None:
        return _("{collector}: working, last success {time}").format(
            collector=collector, time=_time(status.last_success)
        )
    if status.error is None:
        return _("{collector}: not collected yet").format(collector=collector)
    time = _("never") if status.last_success is None else _time(status.last_success)
    return _("{collector}: failing ({code}), last success {time}").format(
        collector=collector, code=_clean(status.error), time=time
    )


def _page(report: ReportView, language: str) -> _Page:
    language = language if language in i18n.LANGUAGES else i18n.SOURCE_LANGUAGE
    catalogue = i18n.translations(language)
    _ = catalogue.gettext
    ngettext = catalogue.ngettext
    leads = {
        Kind.DELTA: _("Report {seq}: changes since the previous report"),
        Kind.STATE: _("Report {seq}: everything currently in force"),
        Kind.HISTORY: _("Report {seq}: catch-up since a date"),
    }
    if report.period_from is None:
        period = _("Period: until {end}").format(end=_time(report.period_to))
    else:
        period = _("Period: from {start} to {end}").format(
            start=_time(report.period_from), end=_time(report.period_to)
        )
    counts = {change: sum(1 for item in report.items if item.change is change) for change in Change}
    summary = ", ".join(
        (
            ngettext("{count} new item", "{count} new items", counts[Change.NEW]).format(count=counts[Change.NEW]),
            ngettext("{count} changed item", "{count} changed items", counts[Change.CHANGED]).format(
                count=counts[Change.CHANGED]
            ),
            ngettext("{count} gone item", "{count} gone items", counts[Change.GONE]).format(count=counts[Change.GONE]),
        )
    )
    titles = {
        Change.NEW: _("New items"),
        Change.CHANGED: _("Changed items"),
        Change.GONE: _("Gone items (last known content)"),
    }
    key_label, address_label = _("Key"), _("Address")
    spent = omitted = 0
    sections: list[_Section] = []
    for change, title in titles.items():
        entries: list[_Entry] = []
        for item in report.items:
            if item.change is not change:
                continue
            entry = _entry(item, key_label, address_label)
            cost = len(entry.heading) + sum(len(name) + len(value) for name, value in entry.rows)
            if spent + cost > MAX_TEXT:
                omitted += 1
                continue
            spent += cost
            entries.append(entry)
        if entries:
            sections.append(_Section(title, tuple(entries)))
    notes: list[str] = []
    if not report.items:
        notes.append(_("No item in this report."))
    if omitted:
        notes.append(
            ngettext(
                "{count} more item is only in items.jsonl.", "{count} more items are only in items.jsonl.", omitted
            ).format(count=omitted)
        )
    return _Page(
        language,
        leads[report.kind].format(seq=report.seq),
        (period, _("Produced: {time}").format(time=_time(report.created_at))),
        summary,
        tuple(sections),
        tuple(notes),
        address_label,
        _("Sources"),
        tuple(_source_line(status, _) for status in report.sources),
        _("Values may be shortened here: items.jsonl, the authoritative data, holds them in full."),
    )


# --- Markdown ---------------------------------------------------------------------------------------------------


def _md(text: str) -> str:
    """One line of plain text: no line break or markup of the source can change the structure of the document."""
    return _MARKDOWN.sub(r"\\\1", " ".join(text.split()))


def _markdown(page: _Page) -> str:
    lines = [f"# {_md(page.title)}", "", *(f"{_md(fact)}  " for fact in page.facts), "", f"**{_md(page.summary)}**", ""]
    for section in page.sections:
        lines += [f"## {_md(section.title)}", ""]
        for entry in section.entries:
            lines += [f"### {_md(entry.heading)}", ""]
            if entry.url is not None:
                lines.append(f"- {_md(page.address_label)}: [{_md(entry.url)}](<{entry.url}>)")
            lines += [f"- {_md(name)}: {_md(value)}" for name, value in entry.rows]
            lines.append("")
    for note in page.notes:
        lines += [_md(note), ""]
    if page.sources:
        lines += [f"## {_md(page.sources_title)}", "", *(f"- {_md(source)}" for source in page.sources), ""]
    lines += ["---", "", _md(page.footer), ""]
    return "\n".join(lines)


# --- HTML -------------------------------------------------------------------------------------------------------


def _h(text: str) -> str:
    return html.escape(text, quote=True)


def _html_entry(entry: _Entry, address_label: str) -> list[str]:
    rows: list[str] = []
    if entry.url is not None:
        link = f'<a href="{_h(entry.url)}" rel="noopener noreferrer">{_h(entry.url)}</a>'
        rows.append(f"<dt>{_h(address_label)}</dt><dd>{link}</dd>")
    rows += [f"<dt>{_h(name)}</dt><dd>{_h(value)}</dd>" for name, value in entry.rows]
    return [f"<h3>{_h(entry.heading)}</h3>", "<dl>", *rows, "</dl>"]


def _html(page: _Page) -> str:
    lines = [
        "<!doctype html>",
        f'<html lang="{_h(page.language)}">',
        "<head>",
        '<meta charset="utf-8">',
        f'<meta http-equiv="Content-Security-Policy" content="{_h(_POLICY)}">',
        '<meta name="referrer" content="no-referrer">',
        '<meta name="viewport" content="width=device-width, initial-scale=1">',
        f"<title>{_h(page.title)}</title>",
        f"<style>\n{_STYLE}\n</style>",
        "</head>",
        "<body>",
        f"<h1>{_h(page.title)}</h1>",
        *(f"<p>{_h(fact)}</p>" for fact in page.facts),
        f"<p><strong>{_h(page.summary)}</strong></p>",
    ]
    for section in page.sections:
        lines.append(f"<h2>{_h(section.title)}</h2>")
        for entry in section.entries:
            lines += _html_entry(entry, page.address_label)
    lines += [f"<p>{_h(note)}</p>" for note in page.notes]
    if page.sources:
        lines += [f"<h2>{_h(page.sources_title)}</h2>", "<ul>", *(f"<li>{_h(s)}</li>" for s in page.sources), "</ul>"]
    lines += [f"<footer>{_h(page.footer)}</footer>", "</body>", "</html>", ""]
    return "\n".join(lines)


class MarkdownRenderer:
    name = "markdown"

    def render(self, report: ReportView, language: str) -> Mapping[str, bytes]:
        return {"report.md": _markdown(_page(report, language)).encode("utf-8")}


class HtmlRenderer:
    name = "html"

    def render(self, report: ReportView, language: str) -> Mapping[str, bytes]:
        return {"report.html": _html(_page(report, language)).encode("utf-8")}
