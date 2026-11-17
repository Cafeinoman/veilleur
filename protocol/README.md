# veilleur-protocol

Standalone implementation of the Veilleur protocol 1.0, for the Veilleur server and for receiving tools:

- pairing codes (`VEIL1:…`);
- key derivation (HKDF-SHA256);
- request signing and verification (`Authorization: Veilleur …`);
- sealing and opening report packages (XChaCha20-Poly1305 envelope, Ed25519-signed manifest), with a reader that
  checks everything before reading any data;
- server signing key rotation statements.

Its only dependency is [`pycryptodomex`](https://pypi.org/project/pycryptodomex/). It does not depend on the Veilleur
server.

The normative specification is [`docs/en/protocol.md`](https://github.com/Cafeinoman/veilleur/blob/main/docs/en/protocol.md)
in the Veilleur repository; the test vectors are in `protocol/vectors/`.

Licence: EUPL-1.2.
