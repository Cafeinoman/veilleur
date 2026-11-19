# Release notes

## 0.1.0

First public version. It is an **alpha**: the protocol and the data formats may still change.

### Included

- **Collection**: `rss`, `json_api` and `page` collectors, plugins, shared collection, and an HTTP client with an SSRF guard.
- **Reports**: change detection, `delta`, `state` and `history` packages, `keywords`, `regex` and `dedup` filters, and `markdown` and `html` renderings in English and French.
- **Protocol 1.0**: signed and encrypted packages, signed requests, server key rotation, the `veilleur-protocol` library and test vectors checked by two implementations.
- **Delivery**: HTTPS or folder delivery, `ntfy` and `webhook` notifications that carry only counts, and the `veilleur-receive` reference receiver.
- **Administration**: the `veilleur` command line, pairing and revocation, and team subscriptions declared in TOML.
- **Deployment**: NixOS modules (host and isolated container), and systemd units with a Caddy configuration for other Linux distributions.

### Not verified

- Load with several hundred subscriptions.
- Issuing a real Let's Encrypt certificate.
- Building and running on `aarch64-linux`.

### Known limitations

- A member who is missing a purged package and has missed two or more key rotations must pair again.
- A running service does not follow a `key rotate` started by another process. Restart the service after a rotation.
- Unauthenticated requests are not rate limited.
- A broken team declaration (a missing plugin, for example) stops the round before any collection.
- The port conflict check only covers what NixOS can see during evaluation.

Pairing secrets offer no forward secrecy: see the [threat model](threat-model.md).
