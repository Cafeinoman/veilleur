# SPDX-License-Identifier: EUPL-1.2
"""The `html` rendering: a page that holds no script and loads nothing."""

from __future__ import annotations

import html
from collections.abc import Mapping

from veilleur.adapters.renderers.common import Entry, Page, build_page
from veilleur.core.ports.plugins import ReportView

_STYLE = """
:root { color-scheme: light dark; }
body { font-family: system-ui, sans-serif; line-height: 1.5; margin: 0 auto; max-width: 48rem; padding: 1rem; }
h1 { font-size: 1.5rem; } h2 { font-size: 1.2rem; margin-top: 2rem; } h3 { font-size: 1rem; margin-bottom: .25rem; }
dl { display: grid; gap: .1rem 1rem; grid-template-columns: minmax(5rem, max-content) 1fr; margin: 0; }
dt { font-weight: 600; } dd { margin: 0; overflow-wrap: anywhere; white-space: pre-wrap; }
footer { font-size: .875rem; margin-top: 2rem; }
""".strip()
_POLICY = "default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'"


def _h(text: str) -> str:
    return html.escape(text, quote=True)


def _html_entry(entry: Entry, address_label: str) -> list[str]:
    rows: list[str] = []
    if entry.url is not None:
        link = f'<a href="{_h(entry.url)}" rel="noopener noreferrer">{_h(entry.url)}</a>'
        rows.append(f"<dt>{_h(address_label)}</dt><dd>{link}</dd>")
    rows += [f"<dt>{_h(name)}</dt><dd>{_h(value)}</dd>" for name, value in entry.rows]
    return [f"<h3>{_h(entry.heading)}</h3>", "<dl>", *rows, "</dl>"]


def _html(page: Page) -> str:
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


class HtmlRenderer:
    name = "html"

    def render(self, report: ReportView, language: str) -> Mapping[str, bytes]:
        return {"report.html": _html(build_page(report, language)).encode("utf-8")}
