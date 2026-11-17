# Design and roadmap

*[Version française](../fr/design.md)*

This document describes what Veilleur will be. The skeleton (milestone G0), the protocol (G1: [specification](protocol.md), [threat model](threat-model.md), `veilleur-protocol` library) and the core with its storage, administration command line and HTTP service (G2) exist today (§9).

## 1. Purpose

Veilleur:
1. **collects** information from pluggable sources (RSS/Atom feeds, JSON APIs, web pages, and any source written as a plugin);
2. **detects** what is new, has changed or has disappeared from one round to the next;
3. turns it into **reports** (structured data plus a readable rendering);
4. **delivers** them, signed and encrypted, to receiving tools (out of scope), over HTTPS or by file transfer, with a notification that carries only counts;
5. installs **declaratively** on NixOS (dedicated server, isolated container, or alongside other services on an existing host), with hardened systemd units, a TLS reverse proxy without access logs, and a version pinned by its tag and hash (§7).

## 2. Model

| Term | Definition |
|---|---|
| **collector** | plugin that, given parameters, returns items |
| **subscription** | a collector, its parameters, optional filters, a report frequency and a language, identified by a random `uid` |
| **item** | `{key, fields, hash, fetched_at, url?}`; `key` is stable and provided by the collector |
| **report** | numbered package for one subscription: new, changed and gone items, plus readable renderings |
| **pairing** | shared secret between the server and one receiving tool, with a `key_id`; can be revoked |

A round: `collectors → normalisation (key, hash) → item store → diff (new / changed / gone) → filters → report per subscription → sealing → delivery → notification`.

Collections are **shared**: two subscriptions asking for the same feed cause a single request (collection key = collector + canonical parameters). A failing source does not stop the round: it is reported in the reports' source status and in the administration commands, and the notification mentions it after two days of failure. An item is **gone** only when absent from a complete, successful collection, never after a failed or partial one.

### 2.1 Extension points (Python plugins, entry points)

| Group | Interface (sketch) | Built in |
|---|---|---|
| `veilleur.collectors` | `schema` (parameters, validated on receipt); `collect(params, since, http) -> Iterable[Item]` | `rss` (RSS/Atom), `json_api` (URL + path in the response + key field), `page` (change of a page, extracted by CSS selector) |
| `veilleur.filters` | `keep(item, params) -> bool` or `transform(item) -> Item` | keywords / regular expression (on chosen fields, optionally case- and accent-insensitive), deduplication across the collections of one subscription |
| `veilleur.renderers` | `render(report, language) -> dict[file_name, bytes]` | `markdown`, `html` (simple template, no JavaScript) |
| `veilleur.notifiers` | `notify(target, counts)` | `ntfy`, `webhook` (HMAC-signed body) |

Filters apply after change detection and before the report; they never modify stored items.

A collector never uses the network directly: it receives the server's HTTP client (cache, quotas, `robots.txt`, SSRF guard, offline mode). On NixOS, plugins are added through a module option and built into the read-only environment; nothing is installed at run time.

### 2.2 Who creates subscriptions

- **The administrator**, declaratively (configuration file or NixOS module option): a team watch on fixed topics.
- **A receiving tool**, by `PUT /v1/subscriptions/{uid}` with sealed parameters, **limited to the collectors the administrator allows for its pairing**. Collectors that follow addresses given by the client (`rss`, `page`, `json_api`) are refused by default and allowed pairing by pairing.

Privacy principle: *the server knows what it collects, never what receivers do with it*. Parameters are validated against the collector's schema on receipt; a modified subscription carries a version number, and a change based on an outdated version is refused (`409`).

Subscription parameters are encrypted in transit and readable by the server in its database (it must read them to collect); the administration guide says so.

## 3. Reports

A package contains `manifest.json` (protocol version, subscription, number, kind, period, hash of every other file, status of the collections), `manifest.sig`, `items.jsonl` (JSON Lines, one item per line, sorted by key: `{key, change: new|changed|gone, hash, fields, fetched_at, url}`) and the requested renderings (`report.md`, `report.html`) in the subscription's language. Renderings are **optional** and **derived**: `items.jsonl` is authoritative.

Kinds: `delta` (since the previous package), `state` (everything currently valid, for a receiver back after packages were purged), `history` (catch-up from a date, prepared in the background). Each subscription keeps what it last reported: a report compares the filtered current items of its collection with that, so changes accumulate until the report is due. Frequency per subscription (daily by default, weekly, every round); an empty report is not produced; a new subscription first receives a `state`, then `delta`s. Packages are numbered without gaps and kept 90 days; a purged package answers `410`, and the receiver then asks for a `state`.

## 4. Security

| Topic | Design |
|---|---|
| Pairing | 32-byte random secret per pairing, random `key_id`, server Ed25519 public key; given once as a pairing code `VEIL1:<base64url JSON>`; its label is a marker ("desk 3"), never a person's name; a revoked pairing receives `403` |
| Keys | HKDF-SHA256 from the pairing secret, salted per subscription, one `info` label per use: a package cannot pass for another subscription's; requests that name no subscription use a pairing-wide authentication key |
| Envelope | `header (magic, version, uid, number, kind) ‖ 24-byte nonce ‖ XChaCha20-Poly1305(plain zip)`; associated data = the header (no replay, no substitution); the header is in clear so that a package in a folder says what it is |
| Signature | pure Ed25519 (RFC 8032) over the exact bytes of `manifest.json`, which holds the SHA-256 of every other file; checked inside the envelope, before reading any data |
| Requests | `Authorization: Veilleur <key_id>:<HMAC-SHA256(method, path and query, timestamp, SHA-256 of the body)>`, `X-Veilleur-Date`, 5-minute tolerance |
| Server key rotation | the outgoing key signs the incoming key; the statement travels in every package for 90 days |
| SSRF | the HTTP client refuses loopback, private, link-local, CGNAT, multicast and reserved addresses (IPv4 and IPv6) **after DNS resolution** and at every redirection, caps the number of redirections, refuses oversized or slow responses and unexpected content types; the container firewall is a second barrier |
| Reader | checks the package size, the number of files (32 at most), their names (no path, no file the kind does not provide for) and their sizes before reading any data; nothing is written in clear on the receiver's disk by the library |
| Logs | no request body, no authentication header, no secret, no subscription parameter, no member IP (the reverse proxy keeps no access log; the service only sees `127.0.0.1`) |
| Secrets | in the service's state directory (mode 700), never in the Nix store, the NixOS configuration, the logs or the repository |
| Limits | request bodies of 1 MB at most (`413`), enforced by the application even if the proxy lets them through |

No forward secrecy: a stolen pairing secret opens past packages of that pairing. This is documented in the threat model.

Security deliverables: the protocol specification (**normative in English**, informative French translation), **test vectors**, a threat model, `SECURITY.md`, fuzzing of the package reader.

## 5. Receiving side

The receiving tool is out of scope. Veilleur provides:
- `veilleur-protocol`, a standalone library (pairing code, request signing, opening and checking a package; single dependency `pycryptodomex`);
- a minimal **reference receiver** (`veilleur-receive pull --folder …`) that fetches, checks and writes reports in a folder. It is used for end-to-end tests and as an example.

## 6. HTTP interface `/v1`

`PUT|DELETE /subscriptions/{uid}`, `GET /subscriptions/{uid}/reports?after=N`, `GET …/reports/{n}`, `GET …/state`, `GET …/history`, `GET /collectors` (collectors this pairing may use, with their schemas). A WSGI application listening on `127.0.0.1` behind the reverse proxy; long jobs answer `202` with `Retry-After` and run in a worker thread. Every request is authenticated. Error bodies: `{"code", "message"}`, without internal detail; `code` is a stable English identifier, `message` is translated. Statuses: `400`, `401`, `403` (revoked pairing or collector not allowed), `404`, `409`, `410`, `413`, `429`, `500`. Every response carries `Cache-Control: no-store`.

The administration command line `veilleur` offers `info`, `config`, `pairing new|list|revoke`, `subscription list|show`, `collectors` (with `allow`, `deny` and `default` to set what a pairing may use), `round`, `sources`, `log`, `export` (delivery by folder), `notify --test`, `key rotate` (server key rotation), `serve` and `version`. The HTTP service (`veilleur serve`) and the periodic round (systemd timer) are two processes on the same SQLite database (WAL mode, numbered SQL migrations run at start-up after a backup).

## 7. Installation

### 7.1 NixOS

The repository's flake exposes `nixosModules.default` (service on the host, `services.veilleur`) and `nixosModules.container` (`services.veilleur-container`: `systemd-nspawn` container with private users and a private network, outbound access to the Internet only — neither the host, nor private networks, nor the Tailscale network (100.64/10) — port 25 closed, memory (`memoryMax`) and process caps). Caddy (Let's Encrypt TLS, domain name or IP address), ntfy and the round timer come with it. Units are fully hardened (dedicated user, no capability, read-only system, private namespaces, system call and address family filtering, `UMask=0077`).

The code and its Python environment (built from `uv.lock` by uv2nix, with nixpkgs' Python) live in `/nix/store`; nothing is downloaded at start-up; plugins are added through a module option.

**Pinned version**: the host configuration loads Veilleur from `github:Cafeinoman/veilleur/<tag>`, either as a flake input (locked in its `flake.lock`) or through `builtins.getFlake` with `narHash`; a manually dropped archive (`tarball+file://…?narHash=…`) remains possible for a host without access to GitHub. The host configuration must **evaluate on any machine**, without any file specific to the server.

### 7.2 Integration into an existing host configuration

For a personal server that already runs other services:
- both modules are **inert while `enable = false`** (`mkIf`): the host can import them unconditionally;
- **TLS front end of choice**: `proxy = "caddy"` (Veilleur takes 80/443, and 8443 for ntfy without its own name) or `proxy = "external"` (Veilleur only listens on an internal address; the guide gives the Caddy and nginx blocks to add to the host's front end). An **assertion** reports any port conflict declared in the configuration;
- **ntfy of choice**: built in, external (address and token of an existing ntfy server) or none;
- **secrets provided by the host** if wanted (file paths, compatible with sops-nix or agenix) for the ntfy token and the webhook key; otherwise generated in the state directory;
- **backup**: the module exposes the list of paths to back up (`backupPaths`) and a service making a consistent copy of the database, to plug into the host's backup (restic, borg);
- **public address** (`publicHost`), written into pairing codes: the guide recommends a name (including a free dynamic DNS name) rather than an IP; in container mode, port forwarding is IPv4 only, so **no AAAA record** (Let's Encrypt and IPv6 clients would fail) as long as IPv6 is not relayed, which the guide and an assertion point out;
- an example host module (`deploy/nixos/examples/host-module.nix`) shows this integration with a settings file.

### 7.3 Other Linux distributions

systemd units, a `Caddyfile` and an ntfy configuration excerpt are provided; code and environment belong to root.

## 8. Repository layout

```
src/veilleur/
  core/domain/          items, subscriptions, reports, pairings (no network, no storage)
  core/services/        collect, diff, report, pairing, round, purge
  core/ports/           Collector, Filter, Renderer, Notifier, Store, Sealer, HttpClient
  adapters/             sqlite, http client, collectors, notifiers, renderers
  apps/server/          command line, WSGI service, worker
  i18n.py, locale/      translations (gettext)
protocol/               veilleur-protocol package and test vectors
receiver/               reference receiver
deploy/nixos/           NixOS module, container, VPS example, NixOS VM test
deploy/systemd/         units, reverse proxy and ntfy examples for other distributions
docs/en/, docs/fr/      documentation, same files in both languages
```

The core depends on no storage, network or translation; this is checked by `lint-imports`.

## 9. Milestones

| Milestone | Content | Done when |
|---|---|---|
| **G0** | Skeleton, EUPL-1.2 licence and SPDX headers, CI, `ruff`, `mypy`, `lint-imports`, gettext with French catalogue and completeness tests, bilingual documentation | skeleton green, one message translated end to end |
| G1 | Protocol 1.0: specification, `veilleur-protocol`, AEAD envelope, key rotation, test vectors | vectors checked by two implementations (library + independent script) |
| G2 | Core: items, diff, subscriptions, reports, pairings, rounds; SQLite; administration command line; WSGI service | a full round on a fake collector, tests without network |
| G3 | HTTP client with SSRF guard; `rss`, `json_api`, `page` collectors; `ntfy`, `webhook` notifiers | tests on recorded responses, SSRF attempts refused |
| G4 | `markdown` and `html` renderings; reference receiver | end to end, server → receiver |
| G5 | Deployment: flake, NixOS module, container, NixOS VM test, systemd fallback, versioned release; administration guide | `nix flake check` and VM test green |
| G6 | Publication pass: secret scanning, `SECURITY.md`, release 0.1.0 | publication |

## 10. Decisions

- **Name**: Veilleur ("watcher" in French).
- **Licence**: EUPL-1.2.
- **Languages**: code, identifiers and comments in English; messages, API error messages, reports and documentation in English and French. Source strings are English; the French catalogue translates them (see [translating.md](translating.md)).
- **Hosting**: GitHub (`Cafeinoman/veilleur`). NixOS installs from `github:Cafeinoman/veilleur/<tag>` (§7.1).
- **Development**: one branch per feature (`claude/<topic>`), pushed and proposed as a pull request by Claude; the user merges into `main`. No direct push to `main` after the first commit. Checks required before every commit: `pytest`, `ruff`, `mypy` (strict), `lint-imports`. GitHub Actions are pinned by commit hash before the first release.
