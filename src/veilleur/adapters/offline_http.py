# SPDX-License-Identifier: EUPL-1.2
"""HTTP client of the offline mode (cahier EF-06): every request fails with `network_unavailable`.

The networked client, with its SSRF guard, comes with milestone G3.
"""

from __future__ import annotations

from collections.abc import Sequence

from veilleur.core.domain import errors
from veilleur.core.domain.errors import CollectorError
from veilleur.core.ports.http import HttpResponse


class OfflineHttpClient:
    def get(self, url: str, *, accept: Sequence[str] = ()) -> HttpResponse:
        raise CollectorError(errors.NETWORK_UNAVAILABLE)
