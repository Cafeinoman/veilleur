# Veilleur

*[Version française](README.fr.md)*

Veilleur is a self-hosted **watch server**. It collects information from pluggable sources (RSS/Atom feeds, JSON APIs, web pages, or any source written as a plugin), detects what is new or has changed between two rounds, turns it into **reports**, and delivers them, **signed and encrypted**, to receiving tools. Receiving tools are out of the project's scope; a small reference receiver will show how to write one.

> **Status: early development.** Only the project skeleton exists. Nothing is usable yet. The design and the roadmap are in [docs/en/design.md](docs/en/design.md).

## Principles

- **One server per team, one administrator.** Members pair their receiving tool with the server once, by pasting a pairing code.
- **The server knows what it collects, never what receivers do with it.**
- **Signed and encrypted reports**, delivered over HTTPS or by plain file transfer, with an optional notification (ntfy, webhook) that only carries counts.
- **Declarative, hardened installation** on NixOS (dedicated server or isolated container), with a fallback for other Linux distributions.
- **Bilingual**: messages, reports and documentation in English and French.

## Development

Requires [uv](https://docs.astral.sh/uv/) and Python 3.12 or later.

```bash
uv sync
uv run pytest
uv run ruff check src tests
uv run mypy
uv run lint-imports
uv run veilleur --lang fr version
```

Translations: see [docs/en/translating.md](docs/en/translating.md).

## Licence

Veilleur is free software under the [European Union Public Licence v. 1.2](LICENSE) (EUPL-1.2). The EUPL is published in all official languages of the European Union, all versions being equally valid.
