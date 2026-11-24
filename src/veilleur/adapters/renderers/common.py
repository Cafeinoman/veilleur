# SPDX-License-Identifier: EUPL-1.2
"""What the provided renderings share: a report put in words, independent of the format, with every value
cleaned and shortened."""

from __future__ import annotations

import json
import re
from collections.abc import Callable
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


@dataclass(frozen=True)
class Entry:
    heading: str
    url: str | None
    """An address safe to link to; another one stays among `rows`, as text."""
    rows: tuple[tuple[str, str], ...]


@dataclass(frozen=True)
class Section:
    title: str
    entries: tuple[Entry, ...]


@dataclass(frozen=True)
class Page:
    """A report in words, independent of the format."""

    language: str
    title: str
    facts: tuple[str, ...]
    summary: str
    sections: tuple[Section, ...]
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
    # Refused rather than cleaned: without these characters it would no longer be the address the source gave.
    if url is None or _UNSAFE.search(url) is not None or _URL.fullmatch(url) is None:
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


def _entry(item: ItemChange, key_label: str, address_label: str) -> Entry:
    heading, used = _heading(item)
    url = _safe_url(item.url)
    rows = [(key_label, _value(item.key))]
    if item.url is not None and url is None:
        rows.append((address_label, _value(item.url)))
    rows += [(_value(name), _value(item.fields[name])) for name in sorted(item.fields) if name != used]
    return Entry(heading, url, tuple(rows))


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


def build_page(report: ReportView, language: str) -> Page:
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
        period = _("Period: from {start} to {end}").format(start=_time(report.period_from), end=_time(report.period_to))
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
    sections: list[Section] = []
    for change, title in titles.items():
        entries: list[Entry] = []
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
            sections.append(Section(title, tuple(entries)))
    notes: list[str] = []
    if not report.items:
        notes.append(_("No item in this report."))
    if omitted:
        notes.append(
            ngettext(
                "{count} more item is only in items.jsonl.", "{count} more items are only in items.jsonl.", omitted
            ).format(count=omitted)
        )
    return Page(
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
