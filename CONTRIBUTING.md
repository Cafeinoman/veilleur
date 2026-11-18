# Contributing to Veilleur

*[Version française](CONTRIBUTING.fr.md)*

Report vulnerabilities privately: see [SECURITY.md](SECURITY.md).

## Scope

Veilleur is generic: a source tied to a particular business domain belongs in a plugin maintained outside this repository. See [writing a collector](docs/en/writing-a-collector.md).

## Branches and pull requests

- Create one branch per feature from an up-to-date `main`.
- `main` is protected: every change goes through a pull request with a green CI.
- Keep commits short, in the imperative mood and in English, and explain why the change is needed.
- Describe in the pull request what changes and what you checked.
- By contributing, you agree that your contribution is published under the [EUPL-1.2](LICENSE).

## Checks

These must pass before every commit:

```bash
uv sync --locked
uv run pytest
uv run ruff check src tests tools protocol receiver
uv run mypy
uv run lint-imports
```

Tests never use the network: use recorded responses and call the WSGI application directly.

## Code rules

- The first line of every Python file is `# SPDX-License-Identifier: EUPL-1.2`.
- Code, identifiers, comments and docstrings are in English.
- `core` depends on neither storage, network, translation, `adapters` nor `apps`.
- Keep dependencies minimal and compatible with the EUPL-1.2, and justify any new one. Cryptography uses `pycryptodomex` only.
- Never log request bodies, authentication headers, secrets, subscription parameters or member IP addresses.
- Collectors reach the network only through the server's HTTP client.
- A protocol change updates its normative specification, its translation and the test vectors.
- Examples use reserved domains (`example.org`, `example.net`) and no personal data.

## Translations and documentation

- Text read by a person goes through `_()` or `ngettext()` of `veilleur.i18n`, with English source text and named parameters.
- Then run `uv run python tools/i18n.py all` and translate the new messages in the French `.po` file. See [translating](docs/en/translating.md).
- `docs/en/` and `docs/fr/` contain the same files: update both.

## Secret scanning

The Nix development shell provides `gitleaks`. Run `gitleaks git --redact .` before publishing a branch.
