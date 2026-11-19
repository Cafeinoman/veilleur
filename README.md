# Veilleur

*[Version française](README.fr.md)*

Veilleur is a self-hosted **watch server**. It collects information from pluggable sources (RSS/Atom feeds, JSON APIs, web pages, or any source written as a plugin), detects what is new or has changed between two rounds, turns it into **reports**, and delivers them, **signed and encrypted**, to receiving tools. Receiving tools are out of the project's scope; a small reference receiver (`receiver/`) shows how to write one.

> **Status: alpha (0.1.0).** The protocol and the data formats may still change. See the [release notes](docs/en/release-notes.md) for what is included and the known limitations, and the [administration guide](docs/en/admin-guide.md) to install it.

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
uv run ruff check src tests tools protocol receiver
uv run mypy
uv run lint-imports
uv run veilleur --lang fr version
```

Translations: see [docs/en/translating.md](docs/en/translating.md). Contributions: see [CONTRIBUTING.md](CONTRIBUTING.md). Vulnerabilities: see [SECURITY.md](SECURITY.md).

## Licence

Veilleur is free software under the [European Union Public Licence v. 1.2](LICENSE) (EUPL-1.2). The EUPL is published in all official languages of the European Union, all versions being equally valid.
