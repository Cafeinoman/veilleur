# Veilleur protocol 1.0

*[Version française](../fr/protocol.md) (informative translation; this English text is normative)*

This document specifies how a Veilleur server and a receiving tool pair, authenticate requests, and exchange sealed
report packages. It is enough to write a receiving tool without reading the server's code. The reference
implementation is the `veilleur-protocol` Python package (`protocol/` in the repository); the test vectors in
`protocol/vectors/` are part of this specification.

The key words MUST, MUST NOT, SHOULD and MAY are to be read as in RFC 2119.

## 1. Overview

- The administrator creates a **pairing**: a 32-byte random secret and a `key_id`. The receiving tool gets them once,
  with the server's public signing key, in a **pairing code** (§3).
- Every key is derived from the pairing secret, one per use and per scope (§4).
- A **package** is a zip archive whose `manifest.json` is signed by the server (§6) and lists the hash of every other
  file (§7), sealed in an authenticated **envelope** (§5).
- Every HTTP request of the receiving tool is authenticated by an HMAC (§8). The server never connects to the
  receiving tool.
- A **reader** checks everything, in a fixed order, before interpreting any data (§10).

## 2. Encodings

| Name | Definition |
|---|---|
| base64url | RFC 4648 §5 alphabet, **without padding**. A decoder MUST refuse padding, any other character, and non-canonical encodings (unused trailing bits set). |
| hex | lowercase hexadecimal |
| `key_id` | pairing identifier: 8 random bytes, as 16 hex digits |
| `uid` | subscription identifier: 16 random bytes, as 32 hex digits; chosen by whoever creates the subscription (the server or the receiving tool) |
| timestamp | UTC, to the second, exactly `YYYY-MM-DDTHH:MM:SSZ` (for example `2026-11-17T06:00:00Z`) |
| JSON | RFC 8259, UTF-8, no byte order mark. A reader MUST refuse an object with a duplicate member name and the non-JSON values `NaN`, `Infinity` and `-Infinity`; it MAY refuse a number it cannot represent. Each refusal takes the code of what is being read (`bad_pairing_code`, `bad_rotation`, `bad_manifest`, `bad_items`, `bad_subscription`). |

Writers produce compact JSON (no insignificant white space) with sorted member names. Readers MUST NOT depend on
either: signatures and hashes are computed over exact bytes, never over a re-serialisation.

## 3. Pairing code

```
VEIL1:<base64url(JSON object)>
```

| Member | Type | Value |
|---|---|---|
| `v` | integer | `1` |
| `server` | string | origin of the server, `https://host[:port]` (no user information, path, query or fragment, not even an empty `?` or `#`; a single trailing `/` is tolerated), or `folder:` when packages are delivered by folder only |
| `key_id` | string | `key_id` of the pairing |
| `secret` | string | base64url of the 32-byte pairing secret |
| `sign_key` | string | base64url of the server's 32-byte Ed25519 public key |
| `ntfy` | object, optional | `{"url": https URL, "topic": non-empty string, "token": absent, or a non-empty string (not `null`)}` |

In `https://host[:port]`, `host` is a DNS name (labels of letters, digits and inner hyphens, 1 to 63 characters,
separated by dots, at most 253 characters, the last label not all digits), an IPv4 address in dotted decimal without
leading zeros, or an IPv6 address in brackets; `port` is a decimal number from 1 to 65535 without leading zero. The
`ntfy.url` member has the same form, optionally followed by a path and query: `/` or `?`, then letters, digits and
``-._~!$&'()*+,;=:@/?%`` (no fragment).

A reader MUST ignore white space around the code, refuse a code longer than 4096 characters, and refuse a code that
does not satisfy this table (`bad_pairing_code`). Unknown members MUST be ignored. The pairing code is shown once; it
holds the secret and MUST be handled as one.

## 4. Key derivation

```
key = HKDF-SHA256(IKM = pairing secret, salt, info, L = 32)        (RFC 5869)
```

| Use | `info` (ASCII) | Scope, salt |
|---|---|---|
| sealing packages (server → receiving tool) | `veilleur-report` | subscription: salt = the 16 bytes of its `uid` |
| sealing subscription documents (receiving tool → server) | `veilleur-subscription` | subscription: salt = the 16 bytes of its `uid` |
| authenticating requests | `veilleur-auth` | the subscription named in the request path (salt = its 16 bytes), otherwise the pairing (empty salt) |

A key thus serves one use and one scope: a package of one subscription can never be opened, or passed off, as
another's.

## 5. Envelope

```
header   = magic "VEIL" (4 bytes) || version 0x01 (1 byte) || uid (16 bytes) || seq (8 bytes, unsigned, big-endian)
           || kind (1 byte)                                                                        -- 30 bytes
envelope = header || nonce (24 bytes) || XChaCha20-Poly1305(key, nonce, plaintext, associated data = header)
```

`ciphertext || tag (16 bytes)` follows the nonce. XChaCha20-Poly1305 is the construction of
draft-irtf-cfrg-xchacha (HChaCha20 subkey, then the ChaCha20-Poly1305 AEAD of RFC 8439). The nonce is random for
every envelope.

| `kind` byte | Kind | Key | Plaintext |
|---|---|---|---|
| `0x01` | `delta` | report | package archive (§7) |
| `0x02` | `state` | report | package archive |
| `0x03` | `history` | report | package archive |
| `0x10` | `subscription` | subscription | subscription document (§7.6) |

`seq` is lower than 2^63. The header travels in clear: a package found in a folder says which subscription, number
and kind it is. Because it is the associated data, changing any of its bytes makes decryption fail, so a package can
be neither replayed under another number or kind nor substituted for another subscription's.

## 6. Signatures

### 6.1 Server signing key

The server holds an Ed25519 key pair (RFC 8032, pure Ed25519, no pre-hashing). Public keys are 32 bytes, signatures
64 bytes. The receiving tool trusts the key of its pairing code, then those it adopts through rotation statements
(§6.3).

### 6.2 Manifest signature

`manifest.sig` holds the 64-byte signature of the exact bytes of `manifest.json`. Since the manifest holds the
SHA-256 of every other file, it authenticates the whole package.

### 6.3 Key rotation

When the server replaces its key, the outgoing key signs a statement naming the incoming one:

`rotation.json` (exact bytes signed):

| Member | Value |
|---|---|
| `protocol` | `"1.0"` |
| `old_key` | base64url of the outgoing public key |
| `new_key` | base64url of the incoming public key |
| `issued_at` | timestamp |

`rotation.sig` holds the signature of `rotation.json` by `old_key`. The server puts both files in every package for
90 days after the rotation. A reader that trusts `old_key` and finds the manifest signed by `new_key` adopts
`new_key` (§10, step 7). Once it has adopted `new_key`, the receiving tool MUST stop trusting `old_key`: a rotation
is how the server recovers from the theft of its key, so the stolen key must not keep signing. A receiving tool that
missed the whole 90-day window must be paired again.

## 7. Packages

### 7.1 Archive

The plaintext of a package envelope is a zip archive (APPNOTE), compression method 0 (stored) or 8 (deflate),
without encryption, without directories, on a single disk, without Zip64 and without data descriptors (general purpose
flags limited to bits 1, 2 and 11); every local header carries the same flags, method, CRC, sizes and name as the
central directory. It contains only these files, each at most once, at the root:

| File | Required | Content |
|---|---|---|
| `manifest.json` | yes | §7.2, at most 1 MiB |
| `manifest.sig` | yes | §6.2, 64 bytes |
| `items.jsonl` | yes | §7.4 |
| `rotation.json`, `rotation.sig` | together or not at all | §6.3; `rotation.json` at most 4096 bytes |
| `report.<ext>` | no | readable rendering, `<ext>` matching `[a-z0-9]{1,16}` (for example `report.md`, `report.html`) |

Writers SHOULD set every modification date to 1980-01-01 00:00:00, so that archives reveal nothing of the server's
clock beyond the manifest.

### 7.2 Manifest

| Member | Type | Value |
|---|---|---|
| `protocol` | string | `"1.0"`; a reader accepts `1.<minor>` and refuses any other major version |
| `uid` | string | subscription, equal to the envelope's |
| `seq` | integer | equal to the envelope's |
| `kind` | string | `delta`, `state` or `history`, equal to the envelope's |
| `created_at` | timestamp | when the package was made |
| `period` | object | `{"from": timestamp or null, "to": timestamp}`, both members present: what the package covers |
| `files` | object | file name → hex SHA-256, for **every** file of the archive except `manifest.json` and `manifest.sig` |
| `sources` | array of objects | status of the collections behind the subscription (§7.5) |

Unknown members MUST be ignored (minor versions may add some).

### 7.3 Numbering

Packages of one subscription are numbered from 1, without gaps, in the order the server produces them. The first
package of a new subscription is a `state`; the following ones are `delta`s.

A `state` or `history` prepared on request (§9) carries the number of the last package it accounts for: the
receiving tool then continues with the packages after that number. Such a package and the `delta` of the same number
are told apart by their kind, which the envelope authenticates.

### 7.4 `items.jsonl`

JSON Lines: one JSON object per line, each line ended by a line feed (`0x0A`), no empty line; an empty file means no
item. Lines are sorted by `key`, in strictly increasing order of Unicode code points (so keys are unique).

| Member | Type | Value |
|---|---|---|
| `key` | non-empty string | stable key given by the collector |
| `change` | string | `new`, `changed` or `gone` |
| `hash` | string | hex SHA-256 computed by the server from the item's fields; receivers compare it, they need not recompute it |
| `fields` | object | the item's data (for `gone`, the last known fields) |
| `fetched_at` | timestamp | when the server collected it |
| `url` | string or null | address of the item at its source, if any |

`items.jsonl` is authoritative; renderings are derived from it and only for reading.

### 7.5 Source status

Each element of `sources` describes one collection: `id` (string), `ok` (boolean), `last_success` (timestamp or
null), `error` (stable error code or null), plus members a reader MUST ignore if unknown. It never holds internal
detail (stack traces, addresses of the server).

### 7.6 Subscription document

The body of `PUT /v1/subscriptions/{uid}` is an envelope of kind `subscription`, sealed with the subscription key.
Its `seq` is the version the change is based on: `0` to create the subscription, otherwise the version returned by
the previous `PUT`. The plaintext is a JSON object whose members (collector, parameters, filters, frequency,
language, renderings) are defined with the HTTP API. The whole envelope is the request body, so it is at most
1 000 000 bytes (§9), and the plaintext at most 999 930 bytes.

## 8. Request authentication

Every request carries:

```
X-Veilleur-Date: <timestamp>
Authorization: Veilleur <key_id>:<base64url(HMAC-SHA256(A, string to sign))>
```

```
string to sign = method "\n" path-and-query "\n" X-Veilleur-Date "\n" hex(SHA-256(body))
```

- `method` in upper case; `path-and-query` exactly as sent on the request line (percent-encoding unchanged), starting
  with `/`; the body is empty for `GET` and `DELETE` (its hash is then that of the empty string).
- `A` is the `veilleur-auth` key (§4) of the request's scope: when the path starts with `/v1/subscriptions/<uid>`
  followed by `/`, `?` or its end, the scope is that subscription (a malformed `uid` there is refused); otherwise the
  pairing.
- The server finds the secret from `key_id`, refuses a date more than **5 minutes** away from its clock in either
  direction (`stale_date`), then compares the MAC in constant time.

The date bounds replay to a 5-minute window. Within it, most replays have no effect (a read; a `PUT` based on a
version that is now outdated gets `409`), but some do: see the [threat model](threat-model.md), §4.

## 9. HTTP interface `/v1`

All requests are authenticated (§8). Every response carries `Cache-Control: no-store`. Error responses have a JSON
body `{"code", "message"}`: `code` is a stable English identifier, `message` a translated text without internal
detail.

| Request | Response |
|---|---|
| `GET /v1/collectors` | collectors this pairing may use, with the JSON schema of their parameters |
| `PUT /v1/subscriptions/{uid}` | sealed subscription document (§7.6); `200 {"version"}`; `409` if based on an outdated version |
| `DELETE /v1/subscriptions/{uid}` | `204` |
| `GET /v1/subscriptions/{uid}/reports?after=N` | `200 {"packages": [{"seq", "size", "sha256"}], "oldest", "last"}`, in clear, without content |
| `GET /v1/subscriptions/{uid}/reports/{n}` | `200` package (`application/octet-stream`); `410` if purged (packages are kept 90 days) |
| `GET /v1/subscriptions/{uid}/state` | `200` `state` package, or `202` with `Retry-After` while it is prepared |
| `GET /v1/subscriptions/{uid}/history?since=YYYY-MM-DD` | `200` `history` package, or `202` with `Retry-After` |

Statuses: `400`, `401` (authentication), `403` (revoked pairing, or collector not allowed for this pairing), `404`,
`409`, `410`, `413` (body over 1 000 000 bytes), `429`, `500`. After a `410`, the receiving tool asks for a `state`.

## 10. Reader

### 10.1 Limits

| Limit | Default |
|---|---|
| size of the envelope | 64 MiB |
| number of files in the archive | 32 |
| declared size of one file | 64 MiB (`manifest.json` 1 MiB, `rotation.json` 4096 bytes, signatures 64 bytes) |
| sum of the declared sizes | 128 MiB |
| size of a subscription envelope | 1 000 000 bytes (the request body limit, §9) |

A reader MAY lower these limits. It MUST keep decrypted data in memory, or in storage only it can read; the reference
implementation writes nothing to disk.

### 10.2 Order of the checks

A reader opening a package for subscription `uid`, possibly expecting a number and a set of kinds, MUST perform
these checks in this order and stop at the first failure, with the given code:

1. envelope larger than the limit: `too_large`;
2. shorter than 70 bytes, magic other than `VEIL`: `bad_envelope`; version other than 1: `unsupported_version`;
   `seq` ≥ 2^63 or unknown kind byte: `bad_envelope`;
3. `uid` other than expected: `uid_mismatch`; kind not expected: `kind_mismatch`; number other than expected (when one
   is expected): `seq_mismatch`;
4. decryption with the key of the envelope's kind fails: `decryption_failed`;
5. archive:
   - no end of central directory record (the last one whose comment ends the archive), several disks, or a central
     directory that does not end exactly where that record begins (offset plus size): `bad_archive`;
   - the record announces more entries than the limit: `too_many_files`, before parsing the directory;
   - then the central directory, entry by entry:
     - a truncated or malformed entry: `bad_archive`;
     - a name not allowed by §7.1 (or not ASCII): `unexpected_file`;
     - a name seen twice, other general purpose flags than §7.1 allows (encryption, data descriptor…), a compression
       method other than 0 or 8, a Zip64 marker (`0xFFFFFFFF` as size or offset): `bad_archive`;
     - a declared size over its limit: `file_too_large`;
   - entries that do not fill the central directory exactly: `bad_archive`;
   - then the sum of declared sizes over its limit: `too_large`;
   - then a required file absent, or only one of `rotation.json` / `rotation.sig`: `missing_file`;
6. read `manifest.json`, `manifest.sig`, and `rotation.json` / `rotation.sig` if present: the entry's whole compressed
   data (its compressed size, from the local header on) must decompress to exactly the declared size and CRC, never
   yielding more than the declared size; a local header whose flags, method, CRC, sizes or name differ from the
   central directory, data out of the
   archive, corrupt data, data going on beyond the declared size, a size or a CRC differing from the declared ones are
   `bad_archive`;
7. signature:
   - if a rotation statement is present, it must be well-formed and signed by its `old_key`: `bad_rotation`;
   - the manifest is accepted if signed by a trusted key;
   - otherwise, if a rotation statement is present, its `old_key` is trusted and the manifest is signed by its
     `new_key`, the manifest is accepted and `new_key` adopted;
   - otherwise: `bad_signature`;
8. manifest:
   - not a JSON object: `bad_manifest`;
   - `protocol` not `1.<minor>`: `unsupported_version`;
   - `uid`, `seq` (an integer, not a boolean) or `kind` differing from the envelope; `created_at` or `period`
     malformed; `sources` not an array of objects; `files` not an object of hex SHA-256 digests: `bad_manifest`;
   - a file listed but absent: `missing_file`; a file present but not listed: `unexpected_file`;
9. every listed file: read as in step 6, then its SHA-256 differs from the manifest: `hash_mismatch`;
10. `items.jsonl` does not follow §7.4: `bad_items`.

Only then may the receiving tool use the package. When reading a folder (no expected number), the receiving tool
checks that numbers follow each other.

A server opening a subscription document applies steps 1 to 4 (limit 1 000 000 bytes, kind `subscription`), then refuses a
plaintext that is not a JSON object (`bad_subscription`).

## 11. Error codes

Stable identifiers, never translated:

| Code | Meaning |
|---|---|
| `bad_encoding` | malformed base64url, identifier or timestamp |
| `bad_pairing_code` | malformed pairing code |
| `too_large` | envelope or archive content over the limits |
| `bad_envelope` | not a Veilleur envelope |
| `unsupported_version` | envelope or protocol version not supported |
| `uid_mismatch`, `seq_mismatch`, `kind_mismatch` | envelope for another subscription, number or kind |
| `decryption_failed` | authentication of the envelope failed (wrong key, altered data) |
| `bad_archive` | archive unreadable, duplicate name, encrypted entry, unsupported compression, size or CRC differing from the declared one |
| `too_many_files`, `unexpected_file`, `missing_file`, `file_too_large` | archive content not allowed |
| `bad_signature` | manifest not signed by a trusted key |
| `bad_rotation` | malformed or falsely signed rotation statement |
| `bad_manifest` | malformed manifest, or not matching the envelope |
| `hash_mismatch` | a file does not match its hash in the manifest |
| `bad_items` | malformed `items.jsonl` |
| `bad_subscription` | malformed subscription document |
| `bad_authorization` | missing or malformed `Authorization`, or MAC mismatch |
| `bad_date` | missing or malformed `X-Veilleur-Date` |
| `stale_date` | request date more than 5 minutes from the server's clock |

## 12. Test vectors

`protocol/vectors/` holds JSON files (binary values in hex):

| File | Content |
|---|---|
| `keys.json` | secret, `uid` (or null), `info` → derived key |
| `pairing.json` | pairing codes and their decoded members |
| `requests.json` | requests, string to sign, scope, `Authorization` header |
| `subscriptions.json` | sealed subscription documents |
| `packages.json` | valid packages (delta, state, history, key rotation): envelope, plain archive, and what a reader must find |
| `refusals.json` | packages, requests and pairing codes a reader must refuse, with the expected code |

They are produced by the reference implementation (`tools/protocol_vectors.py`) and checked by an independent one
written from this document, with libsodium instead of pycryptodomex (`tools/check_vectors.py`); the CI runs both.

## 13. Versions

The pairing code prefix (`VEIL1:`), the envelope version byte and the manifest's `protocol` member carry the version.
A minor version (`1.x`) only adds optional members, which older readers ignore. A major version changes the prefix,
the version byte and the major number; readers refuse what they do not know.
