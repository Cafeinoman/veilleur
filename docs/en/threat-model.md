# Threat model

*[Version française](../fr/threat-model.md)*

What Veilleur protects, against whom, how, and what it does not protect. Protocol details are in
[protocol.md](protocol.md).

## 1. What is protected

| Asset | Where |
|---|---|
| **Report content** (items, renderings) | server database, packages in transit or in a folder, receiving tool |
| **Subscription parameters** (what a member watches) | in transit from the receiving tool; server database |
| **Pairing secrets** | server state directory, receiving tool, pairing code once |
| **Server signing key** | server state directory |
| **Members' identity and activity** | never collected: no account, no name (a pairing label is a marker such as "desk 3"), no IP address in the logs |
| **The server itself** | a host on the Internet that makes outbound requests on behalf of its users |

Principle (specification ES-01): *the server knows what it collects, never what receivers do with it.*

## 2. Adversaries

| Adversary | Capabilities |
|---|---|
| **Network** | reads, alters, replays and drops traffic between the receiving tool and the server, or packages carried by folder |
| **Unpaired client** | sends arbitrary requests to the public API |
| **Paired member** | holds one pairing secret; may try to reach other subscriptions, or to use the server to probe internal networks (SSRF) |
| **Hostile source** | a watched site or API returning crafted content: huge, malformed, redirecting to internal addresses |
| **Thief of a pairing code or of a receiving tool's storage** | holds one pairing secret |
| **Server compromise** | reads the database and the state directory |

## 3. Threats and countermeasures

| Threat | Countermeasure |
|---|---|
| Reading reports in transit or in a folder | XChaCha20-Poly1305 envelope, key derived per subscription; TLS on top for HTTPS |
| Forging or altering a package | AEAD with a key only the server and the pairing know; Ed25519 signature of the manifest, which holds the hash of every file |
| Replaying a package under another number, kind or subscription | the header (uid, number, kind) is the AEAD's associated data; the manifest repeats it and is signed |
| Withholding packages | numbers have no gaps; the receiving tool notices a missing one (`reports?after=N`) |
| Malicious archive (path traversal, zip bomb, too many files) | the reader checks names, count and declared sizes before decompressing, never decompresses beyond the declared size, writes nothing to disk ([protocol.md §10](protocol.md#10-reader)); fuzzed in the tests |
| Request by an unpaired client | HMAC on method, path and query, date and body hash; constant-time comparison; `401` |
| Request replay | 5-minute date tolerance; versioned writes (see §4 for what remains) |
| A member reaching another subscription | authentication key derived for the subscription named in the path; a pairing only sees its own subscriptions; `403` for a revoked pairing |
| SSRF through a member's subscription | collectors that follow a client-given address are refused unless the administrator allows them for that pairing; the HTTP client refuses loopback, private, link-local, CGNAT, multicast and reserved addresses after DNS resolution and at each redirection; the connection goes to the checked address, never to a name resolved again (DNS rebinding), and a name with any internal address is refused; caps on size (decompressed), time and redirections; outbound firewall of the container as a second barrier |
| Hostile source content | size, time and content-type caps in the HTTP client; a failing source does not stop the round; source errors are reported as stable codes, without internal detail |
| Theft of the server key | rotation: the outgoing key signs the incoming one, receiving tools follow without re-pairing and stop trusting the outgoing key |
| Leaks through logs | no body, authentication header, secret, subscription parameter or member IP in the logs; the reverse proxy keeps no access log |
| Leaks through notifications | notifications carry counts only, never content |
| Oversized requests | bodies over 1 MB refused by the application (`413`) |

## 4. Accepted risks

These are known and documented; they follow from the design choices of the specification.

- **No forward secrecy** (ES-12): a stolen pairing secret opens every package of that pairing, past and future, that
  the thief can obtain. Revoking the pairing stops future packages; rotating a pairing means pairing again.
- **The server reads subscription parameters**: it must, to collect. They are encrypted in transit only. Whoever
  controls the server knows what each pairing watches (but not who the member is).
- **Metadata in clear**: an envelope header shows the subscription `uid`, the package number and its kind; its size
  shows the order of magnitude of the content; `reports?after=N` lists numbers, sizes and hashes. The network adversary
  sees them only if it also breaks TLS; anyone holding a folder export sees them.
- **Replay window**: a request captured despite TLS can be replayed for 5 minutes. Such a replay changes nothing: a
  read; a `PUT` based on a version that is now outdated gets `409`; a `DELETE` or a creation (`PUT` based on version
  0) replayed after a deletion meets a tombstone, since a deleted `uid` is never reused and versions keep increasing
  across a deletion ([protocol.md §9.1](protocol.md#91-subscription-document)). What remains is what a delay can do:
  an adversary who holds back a request delivers it up to 5 minutes later.
- **Compromised outgoing key**: a receiving tool stops trusting the outgoing key once it has adopted the incoming one
  ([protocol.md §6.3](protocol.md#63-key-rotation)). Until then, a thief of the key could sign a rotation to their
  own key, but still could not make a package the receiving tool accepts without the pairing secret.
- **Server compromise**: the server holds the pairing secrets and the signing key, hence everything. Hardening (dedicated
  user, read-only system, no capability, system call filtering, container) reduces this risk without removing it.
- **Denial of service**: rate limiting (`429`) and quotas protect the server from one pairing, not from a determined
  network attack; this is left to the host.

## 5. Out of scope

The security of the receiving tool once it has opened a package (storage, display), the security of the host and of
its other services, and the confidentiality of what sources publish (which is public by nature).
