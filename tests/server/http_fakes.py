# SPDX-License-Identifier: EUPL-1.2
"""A recorded web for the HTTP client's tests: names resolve to fixed addresses, requests get recorded answers.

No socket is ever opened.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from veilleur.adapters.http.client import Limits, NetworkHttpClient, RawResponse

RECORDED = Path(__file__).parent / "recorded"
PUBLIC = "93.184.215.14"
"""A global address (any would do: nothing is ever connected)."""


@dataclass
class Sent:
    scheme: str
    address: str
    host: str
    port: int
    target: str
    headers: dict[str, str]


@dataclass
class FakeWeb:
    """`dns[host]` gives the addresses of a host; `pages[(host, target)]` the answer to a request."""

    dns: dict[str, list[str]] = field(default_factory=dict)
    pages: dict[tuple[str, str], RawResponse | list[RawResponse]] = field(default_factory=dict)
    sent: list[Sent] = field(default_factory=list)
    clock: float = 0.0
    slept: list[float] = field(default_factory=list)

    def resolve(self, host: str, port: int) -> Sequence[str]:
        if host not in self.dns:
            raise OSError("no such host")
        return self.dns[host]

    def request(
        self,
        *,
        scheme: str,
        address: str,
        host: str,
        port: int,
        target: str,
        headers: Mapping[str, str],
        timeout: float,
        max_bytes: int,
    ) -> RawResponse:
        self.sent.append(Sent(scheme, address, host, port, target, dict(headers)))
        answer = self.pages.get((host, target))
        if answer is None:
            return RawResponse(404, {"content-type": "text/plain"}, b"not found")
        if isinstance(answer, list):
            answer = answer.pop(0) if len(answer) > 1 else answer[0]
        return RawResponse(answer.status, answer.headers, answer.body[: max_bytes + 1])

    def monotonic(self) -> float:
        return self.clock

    def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.clock += seconds

    def page(self, url_host: str, target: str, body: bytes | str, content_type: str, **headers: str) -> None:
        if url_host not in self.dns:
            self.dns[url_host] = [PUBLIC]
        data = body.encode() if isinstance(body, str) else body
        self.pages[(url_host, target)] = RawResponse(200, {"content-type": content_type, **headers}, data)

    def recorded(self, url_host: str, target: str, name: str, content_type: str) -> None:
        self.page(url_host, target, (RECORDED / name).read_bytes(), content_type)

    def requests_to(self, target: str) -> list[Sent]:
        return [s for s in self.sent if s.target == target]


def client(web: FakeWeb, **limits: Any) -> NetworkHttpClient:
    return NetworkHttpClient(
        public_url="https://veille.example.org",
        limits=Limits(**limits),
        resolver=web.resolve,
        transport=web,
        monotonic=web.monotonic,
        sleep=web.sleep,
    )
