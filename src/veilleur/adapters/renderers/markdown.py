# SPDX-License-Identifier: EUPL-1.2
"""The `markdown` rendering."""

from __future__ import annotations

import re
from collections.abc import Mapping

from veilleur.adapters.renderers.common import Page, build_page
from veilleur.core.ports.plugins import ReportView

_MARKDOWN = re.compile(r"([\\`*_{}\[\]()<>#+\-.!|~&])")


def _md(text: str) -> str:
    """One line of plain text: no line break or markup of the source can change the structure of the document."""
    return _MARKDOWN.sub(r"\\\1", " ".join(text.split()))


def _markdown(page: Page) -> str:
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


class MarkdownRenderer:
    name = "markdown"

    def render(self, report: ReportView, language: str) -> Mapping[str, bytes]:
        return {"report.md": _markdown(build_page(report, language)).encode("utf-8")}
