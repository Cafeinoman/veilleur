# SPDX-License-Identifier: EUPL-1.2
# Project commands (ADR-0029). `just test` is what the CI runs in `nix develop`.

# Every check, in the order of the CI; stops at the first failure.
test:
    uv run --locked pytest
    uv run --locked ruff check src tests tools protocol receiver
    uv run --locked mypy
    uv run --locked lint-imports
    uv run --locked python tools/check_vectors.py
    uv run --locked python tools/protocol_vectors.py --check

# Format the code, then apply the safe lint fixes.
fmt:
    uv run --locked ruff format src tests tools protocol receiver
    uv run --locked ruff check --fix src tests tools protocol receiver

# NixOS modules and virtual machine tests (KVM needed).
vm:
    nix flake check -L

# Fail when the CI has grown too slow (needs `gh` authenticated on this repository).
ci-load:
    python3 tools/ci_load.py
