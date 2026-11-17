# SPDX-License-Identifier: EUPL-1.2
"""Configuration file (TOML): where the state lives, the public address, team subscriptions (cahier EF-10).

    state_dir = "/var/lib/veilleur"
    public_url = "https://veille.example.org"     # or "folder:" for delivery by folder only
    language = "en"                               # default language of API messages
    listen = "127.0.0.1"
    port = 8470

    [[subscriptions]]                             # team subscriptions
    name = "team_feed"
    collector = "rss"
    params = { url = "https://example.org/feed.xml" }
    pairings = ["desk 3"]                         # labels or key_ids
    frequency = "daily"
    language = "fr"

No secret belongs here (ES-10): secrets live in the state directory.
"""

from __future__ import annotations

import os
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from veilleur.core.domain import errors
from veilleur.core.domain.errors import VeilleurError
from veilleur.core.domain.model import LANGUAGES

DEFAULT_CONFIG = Path("/etc/veilleur/config.toml")
DEFAULT_STATE_DIR = Path("/var/lib/veilleur")
DEFAULT_PORT = 8470
_KEYS = {"state_dir", "public_url", "language", "listen", "port", "subscriptions"}
_SUBSCRIPTION_KEYS = {"name", "collector", "params", "pairings", "filters", "frequency", "language", "renderings"}


@dataclass(frozen=True)
class TeamDeclaration:
    """A team subscription as declared: the document of a subscription, and the pairings it is for."""

    name: str
    document: dict[str, Any]
    pairings: tuple[str, ...]


@dataclass(frozen=True)
class Config:
    state_dir: Path = DEFAULT_STATE_DIR
    public_url: str = "folder:"
    language: str = "en"
    listen: str = "127.0.0.1"
    port: int = DEFAULT_PORT
    subscriptions: tuple[TeamDeclaration, ...] = ()
    source: Path | None = field(default=None, compare=False)

    @property
    def database(self) -> Path:
        return self.state_dir / "veilleur.db"


def _bad(member: str) -> VeilleurError:
    return VeilleurError(errors.INVALID_CONFIG, member=member)


def _team(raw: Any, index: int) -> TeamDeclaration:
    where = f"subscriptions[{index}]"
    if not isinstance(raw, dict) or set(raw) - _SUBSCRIPTION_KEYS:
        raise _bad(where)
    name, pairings = raw.get("name"), raw.get("pairings")
    if not isinstance(name, str) or not name:
        raise _bad(f"{where}.name")
    if not isinstance(pairings, list) or not pairings or not all(isinstance(p, str) and p for p in pairings):
        raise _bad(f"{where}.pairings")
    document = {k: v for k, v in raw.items() if k not in ("name", "pairings")}
    return TeamDeclaration(name, document, tuple(pairings))


def parse(data: Mapping[str, Any], *, source: Path | None = None) -> Config:
    unknown = set(data) - _KEYS
    if unknown:
        raise _bad(sorted(unknown)[0])
    defaults = Config()
    state_dir = data.get("state_dir", str(defaults.state_dir))
    public_url = data.get("public_url", defaults.public_url)
    language = data.get("language", defaults.language)
    listen = data.get("listen", defaults.listen)
    port = data.get("port", defaults.port)
    raw_subscriptions = data.get("subscriptions", [])
    if not isinstance(state_dir, str) or not state_dir.startswith("/"):
        raise _bad("state_dir")
    if not isinstance(public_url, str) or not (public_url == "folder:" or public_url.startswith("https://")):
        raise _bad("public_url")
    if language not in LANGUAGES:
        raise _bad("language")
    if not isinstance(listen, str) or not listen:
        raise _bad("listen")
    if type(port) is not int or not 0 < port < 65536:
        raise _bad("port")
    if not isinstance(raw_subscriptions, list):
        raise _bad("subscriptions")
    subscriptions = tuple(_team(raw, i) for i, raw in enumerate(raw_subscriptions))
    names = [s.name for s in subscriptions]
    if len(set(names)) != len(names):
        raise _bad("subscriptions.name")
    return Config(Path(state_dir), public_url.rstrip("/"), language, listen, port, subscriptions, source)


def load(
    path: Path | None = None, *, state_dir: Path | None = None, environ: Mapping[str, str] | None = None
) -> Config:
    """The configuration: `path`, otherwise `VEILLEUR_CONFIG`, otherwise `/etc/veilleur/config.toml` if it exists.

    `state_dir` (or `VEILLEUR_STATE_DIR`) overrides the file's.
    """
    env = os.environ if environ is None else environ
    if path is None and env.get("VEILLEUR_CONFIG"):
        path = Path(env["VEILLEUR_CONFIG"])
    if path is None and DEFAULT_CONFIG.exists():
        path = DEFAULT_CONFIG
    data: dict[str, Any] = {}
    if path is not None:
        try:
            with path.open("rb") as f:
                data = tomllib.load(f)
        except OSError as exc:
            raise VeilleurError(errors.INVALID_CONFIG, member=str(path)) from exc
        except tomllib.TOMLDecodeError as exc:
            raise VeilleurError(errors.INVALID_CONFIG, member=str(path)) from exc
    if state_dir is None and env.get("VEILLEUR_STATE_DIR"):
        state_dir = Path(env["VEILLEUR_STATE_DIR"])
    if state_dir is not None:
        data = {**data, "state_dir": str(state_dir.absolute())}
    return parse(data, source=path)
