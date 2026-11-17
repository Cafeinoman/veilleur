# SPDX-License-Identifier: EUPL-1.2
"""The server's HTTP clients (cahier EF-06, ES-08): the networked client with its SSRF guard, and the offline mode."""

from .client import Limits, NetworkHttpClient
from .offline import OfflineHttpClient

__all__ = ["Limits", "NetworkHttpClient", "OfflineHttpClient"]
