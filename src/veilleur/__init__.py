# SPDX-License-Identifier: EUPL-1.2
"""Veilleur: a self-hosted watch server with pluggable collectors and signed, encrypted reports."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("veilleur")
except PackageNotFoundError:  # running from a source tree without installation
    __version__ = "0.0.0"
