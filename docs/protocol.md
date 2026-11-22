# Protocol reference

This file is the cross-repository reference for bytes exchanged between
aoheyra processes. It restates the implemented formats owned by the sibling
crates; it does not define new ones. The source of truth for each format is the
owning repository and its ADR. Application payload schemas are documented
separately in DOC-09 and remain opaque to the mesh.

## aoMesh packet and capability reference (v1)

Implemented by aoMesh's `packet` and `hello` modules. The byte-level decision
record is [aoMesh ADR-0002](https://github.com/aoheyra/aoMesh/blob/master/docs/adr/0002-packet-wire-format.md);
the signed introduction decision is [ADR-0004](https://github.com/aoheyra/aoMesh/blob/master/docs/adr/0004-mesh-hello.md).
Class names, TTLs and relay budgets come from
[ADR-0001](https://github.com/aoheyra/aoMesh/blob/master/docs/adr/0001-routing-per-traffic-class.md).

### v1 packet layout

All integers are canonical unsigned LEB128: shortest form only, at most ten
bytes and at most 64 bits. `msg_id`, `origin` and `dst` are 16-byte opaque
values; `NodeId` bytes are never interpreted by aoMesh. `MAX_PAYLOAD` is
**2048** bytes and is checked while the header is parsed, before payload bytes
are read or copied.

```text
offset  size      field
0       1         ver = 1
1       1         class
2       1         flags
3       16        msg_id
19      16        origin
35      0 or 16   dst (present iff flags bit 0 is set)
..      1..10     created_ms
..      1..10     lifetime_s
..      1..10     payload_len
..      1         ttl       (hop-mutable)
..      1         hops      (hop-mutable)
..      64        signature (Ed25519)
..      payload_len payload (opaque)
```

| Field | Values and rules |
|---|---|
| `ver` | `1` only. Another value is rejected as `UnsupportedVersion`. |
| `class` | `1` Direct, `2` Broadcast, `3` Presence, `4` Telemetry. `0` and `5..255` are rejected. |
| `flags` | Bit 0 means `dst` is present. Every other bit must be zero. |
| `msg_id` | 16-byte content address derived as below. |
| `origin` | Claimed origin; the recipient checks it against the seal and signature. |
| `dst` | Present only for a directed packet. |
| `created_ms`, `lifetime_s` | Sender-declared creation time and lifetime. Expiry uses local relative age, never a remote wall-clock comparison. |
| `payload_len` | Declared payload length, at most `MAX_PAYLOAD` (2048). |
| `ttl`, `hops` | Hop limit and hop count. Both are mutable by relays and are outside the signed prefix. |
| `signature` | 64-byte Ed25519 origin signature over the immutable prefix. |
| `payload` | Opaque application bytes. No sibling crate parses the application schema. |

The bytes from `ver` up to, but excluding, `ttl` are the **immutable prefix**.
The signature follows the hop fields and covers exactly that one contiguous
range under the registered domain `aoheyra/mesh/v1/packet`. A relay that
decrements `ttl` and increments `hops` therefore does not break verification;
a change to any byte in the prefix does. The payload is bound to the signature
through `msg_id`, not by signing it twice.

`Header::decode` is header-only and allocation-free. Parsing rejects unknown
versions, classes and flag bits, non-canonical varints, oversize declared
payloads, payload-length mismatches and trailing bytes instead of normalising
them, so one message has exactly one byte string and one identity.

### Per-class defaults

From ADR-0001. TTL is a hop limit; copies are bounded in-network copies;
lifetime is how long a copy may be stored; the relay budget is KiB/hour a relay
spends carrying that class for others.

| Class | Wire ID | Mechanism | TTL | Copies | Lifetime | Relay budget | Priority |
|---|---:|---|---:|---:|---|---:|---:|
| Direct | 1 | spray-and-wait with reverse-path hints | 8 | 255 | 24 h | 1 MiB/h | 1 |
| Broadcast and channels | 2 | counter-based suppression | 6 | 1 per node | 6 h | 256 KiB/h | 2 |
| Presence | 3 | trickle-timed gossip | 3 | 1 per node | 30 min | 64 KiB/h | 3 |
| Telemetry | 4 | announce, latest-wins, no storage | 3 | 1 per node | 30 s | 32 KiB/h | 4 |

Budget and suppression details are engine policy, not wire fields. Telemetry
is never inserted into the store or served by sync.

### Origin signature and `MessageId` (MSH-04)

The origin signs the immutable prefix with aoIdents' context-separated signing
API. The domain string `aoheyra/mesh/v1/packet` is registered in aoIdents
ADR-0001 so a signature made for another use cannot verify as a packet.
Relay verification is class dependent: Broadcast and Presence are always
verified, Direct is verified while the relay CPU budget allows, and Telemetry
is not verified by relays. The recipient always verifies a Direct packet
addressed to it before emitting local delivery.

`MessageId` is a 16-byte content address computed in two domain-separated
steps under `aoheyra/mesh/v1/msg-id`:

```text
payload_hash = BLAKE3(domain || 0x01 || payload)
msg_id       = BLAKE3(domain || 0x02 || prefix_with_msg_id_zeroed || payload_hash)[..16]
```

The `msg_id` field is hashed as zeroes because it lives inside the prefix it
derives from. Every other prefix byte participates, while `ttl` and `hops` do
not, so a relay's hop decrement preserves the identity used by the forwarding
dedupe cache.

### MeshHello and capability negotiation (MSH-07)

A signed `MeshHello` is carried inside aoNetwork's opaque 256-byte `app_hello`
field on link-up. aoNetwork does not parse it. The v1 hello is fixed width and
exactly **161** bytes:

| Offset | Size | Field | Notes |
|---:|---:|---|---|
| 0 | 16 | `node_id` | Claimed; verification derives the real value from the keys. |
| 16 | 8 | `card_hash` | Identity-card announcement hash, opaque to the mesh. |
| 24 | 1 | `proto` | Mesh format version the sender speaks. |
| 25 | 4 | `caps` | Feature bits, big-endian. |
| 29 | 4 | `store_digest` | Store summary digest, opaque to the mesh. |
| 33 | 32 | `signing_pk` | Ed25519 verification key. |
| 65 | 32 | `agreement_pk` | X25519 agreement key; with `signing_pk` it derives `node_id`. |
| 97 | 64 | `signature` | Ed25519 over bytes `0..97` under `aoheyra/mesh/v1/hello`. |

Verification requires exact length, a valid signature under `signing_pk`, and
`node_id == compute_node_id(signing_pk, agreement_pk)`. Negotiation is
`min(proto)` with a floor of 1 and a bitwise intersection of `caps`. A hello
that fails any step is dropped: the neighbour entry still counts traffic but
records no identity, and no forwarding, delivery or budgeting happens on its
behalf.

| Bit | Constant | Feature and owner issue | Fallback for peers without the bit |
|---:|---|---|---|
| 0 | `CAP_SYNC_V1` | Bounded anti-entropy sync, MSH-14 | Beacon digest only (MSH-13). |
| 1 | `CAP_SYNC_V2` | Range-based reconciliation, MSH-15 | MSH-14 summary exchange if bit 0 is set. |
| 2 | `CAP_SPRAY_V1` | Binary spray copy tickets, MSH-16 | Raw packet without the spray envelope. |
| 3 | `CAP_RECEIPT_V1` | Signed delivery receipts and immunity, MSH-17 | Receipt bytes are not sent. |
| 4 (`1 << 4`) | `CAP_PRESENCE_V1` | Signed presence announcements, MSH-19 | Pre-MSH-19 Presence relay path. |

Bits are advertised in `MeshHello.caps` and negotiated by intersection; an
unknown future bit is simply not shared by an older peer.

### Wire evolution

Changing the packet layout, the hello layout, signature coverage, the class
set, a flag meaning, a capability bit or the negotiation rule is a protocol change.
It requires an ADR, a version bump, a compatibility note, and fallback
through `MeshHello.proto` and `MeshHello.caps` so a node never parses a version
it does not know. Additive payloads that remain opaque bytes inside an existing
class and are cap-gated do not move these offsets, as with Presence in MSH-19;
they are still recorded in the protocol document in the same change.

Sources: `src/packet.rs`, `src/hello.rs` and `docs/adr/0002-packet-wire-format.md`
in [aoMesh](https://github.com/aoheyra/aoMesh).
## Link layer and Android BLE contract

aoNetwork owns everything below an opaque payload: radio peers, frames,
fragmentation, per-link queueing, the link state machine, topology policy and
the native radio contract. Its normative source is
[`docs/native-contract.md`](https://github.com/aoheyra/aoNetwork/blob/master/docs/native-contract.md)
and its defaults are validated by `NetworkConfig`, not copied here. The Kotlin
`:ble` module in `aoheyra/android` is a thin radio shim: it moves raw bytes and
raw status codes. Framing, timeouts, retries, beacons, the degree cap,
duplicate-link resolution and status mapping all live in Rust.

### What aoNetwork owns

| Area | Contract |
|---|---|
| Channels | `Control` has strict priority; `Message`, `Telemetry` and `Bulk` use deficit round-robin with approximate weights 4:2:1. Queue caps and receive windows are per link. |
| Frames | Hand-rolled, big-endian version/type bytes with canonical LEB128 lengths. `Hello`, `Data`, `Ping`, `Pong`, `Bye` and `Credit` are decoded with typed errors and bounded before allocation. See the NET-04 ADR. |
| Fragmentation | A one-byte chunk header (START, END, three-bit sequence); payload per chunk is `MTU - 3 - 1`. One frame is in flight per link. See the NET-05 ADR. |
| Beacons | A 16-byte scan-response manufacturer payload carrying version, flags, degree, `max_links`, an 8-byte hint and a 4-byte digest. Kotlin passes the bytes through unparsed. See the NET-06 ADR. |
| Link state | `Connecting → Negotiating → Handshaking → Ready → Closing → Closed`. Both sides send `Hello` when the MTU settles; version overlap, oversize hello and timeout have typed close reasons. |
| Per-link queueing | Bounded byte caps per channel, coalescing and expiry through `SendOpts { coalesce_key, expires_at }`, and credit-based flow control when both hellos offer it. |
| Topology | Stable, explore and opportunistic slots; a `max_links` ceiling; inbound links meet the same slots and floor; peer scoring, weak-link shedding and a temporary blacklist for abuse. |
| Link hints | `set_link_hint(peer, LinkHintPreference)` orders candidates for dialing and can skip the initiation delay. Hints are **advisory**: they cannot add a candidate, reserve a slot or bypass `max_links`. aoNetwork alone enforces the degree cap. |
| Liveness and metrics | Keepalive ping/pong, per-link RSSI, RTT, bytes, drops and queued bytes, plus cumulative counters exposed by `Network::snapshot`. |

The rotating link tag is generated by aoIdents, passed down by aoMesh and
carried by aoNetwork only for duplicate-link tie-breaking. The signed
`MeshHello` is opaque `app_hello` bytes at this layer.

### Rust to Kotlin: `NativeSink`

Kotlin implements this trait. Every method posts work to the BLE thread and
returns immediately; no BLE call, lock wait or sleep occurs inside a sink
call. Kotlin never calls back into `NativeEvents` from inside a sink call.

| Callback | Kotlin responsibility | Module issue |
|---|---|---|
| `set_advertising(beacon, mode)` / `set_advertising(None, _)` | Start, replace or stop legacy connectable advertising; carry the service UUID in advertising data and the raw beacon in scan-response manufacturer data; report `onStartFailure`; restart after radio toggles. Latest call wins. | AND-05, using the serial executor from AND-04 |
| `set_scanning(mode)` / `set_scanning(None)` | Start, change or stop active scanning with the service-UUID filter; guard against Android scan-start throttling. Rust already limits mode changes, so Kotlin adds no throttling. | AND-06, using AND-04 |
| `connect(link, peer)` | GATT client setup to the `BluetoothDevice` last seen for that radio peer; no `autoConnect`, no retry of its own. Unknown peer becomes `on_closed(link, PeerUnknown)`. | AND-08, using AND-04 |
| `write(link, bytes)` | Send exactly one ATT value: RX write without response as central, TX notification as peripheral. One write is in flight per link; a failed write closes the link through `on_closed`. | AND-07 (peripheral) or AND-08 (central), queued by AND-04 |
| `disconnect(link)` | Tear the GATT object down and report `on_closed(link, Requested)`. Valid in any state, including while connecting. | AND-04 with AND-07 or AND-08 teardown |

`LinkId` values are allocated by Rust. Kotlin never invents one and never
reuses one after `on_closed`. Calls for an already closed link are ignored.
`PeerKey` is a radio address, not an identity; Kotlin does not deduplicate by
it. Per link, Kotlin serialises GATT operations one at a time behind a single
GATT thread with a per-link single-flight operation queue, and Rust grants one
write credit at a time.

### Kotlin to Rust: `NativeEvents`

Rust implements this trait. Kotlin calls it from its GATT thread in stack
order. Callbacks return immediately; Rust queues them in bounded storage.

| Event | Meaning | Module issue |
|---|---|---|
| `on_radio_state` | Adapter state or BLE permission changed; on off or denied, all links are closed first. | AND-03, delivered through AND-09 |
| `on_discovery_failed` | Raw advertiser or scanner start failure code. | AND-05 or AND-06 |
| `on_scan_result` | One filtered scan result with the raw manufacturer payload. | AND-06 |
| `on_connected` | Outbound GATT setup finished; includes negotiated MTU. | AND-08 |
| `on_accepted` | Inbound GATT setup finished; Rust returns the `LinkId` to use. | AND-07 |
| `on_mtu_changed` | MTU changed after a link came up. | AND-04 with AND-07 or AND-08 |
| `on_bytes` | One ATT value received, unmodified. | AND-07 or AND-08 |
| `on_write_ready` | The local stack accepted the previous write; return the link's single write credit. | AND-07 or AND-08 |
| `on_closed` | The link is gone, its GATT object is closed, and this is its last event. | AND-04 with AND-07 or AND-08 |

Per link, `on_connected` or `on_accepted` comes first, `on_bytes` calls keep
their stack order, and `on_closed` comes exactly once and last. The simplest
implementation is one serial GATT thread for all callbacks, forwarding to Rust
in callback order. Across links no ordering is promised.

### Roles and connection state

- The peripheral opens one GATT server with the RX and TX characteristics
  before advertising. RX is write-without-response; TX is notify with a CCCD.
  The central connects, discovers the service, requests a larger MTU, enables
  TX notifications, then reports `on_connected`.
- Kotlin accepts every inbound central; Rust disconnects any it does not want.
  A malformed RX write or CCCD write is reported as `PeerMisbehaved`.
- Teardown waits for the disconnect callback, closes the GATT object and then
  reports `on_closed`. The mapping from raw `NativeStatus` to Rust
  `ConnectError` or `DisconnectReason` is in the aoNetwork contract and is not
  reimplemented in Kotlin.
- The foreground service (AND-10) owns start and stop; the runtime owns the
  one object that reaches aoNetwork on behalf of the BLE module.

Source: aoNetwork's `docs/native-contract.md`, `README.md` and the NET-03 to
NET-14 issue scopes in the ownership backlog.
## Identity and trust model

aoIdents owns identity, signatures, sealed messages, contact trust and replay
rejection. Its normative sources are
[ADR-0001](https://github.com/aoheyra/aoIdents/blob/master/docs/adr/0001-crypto-suite-and-encodings.md)
and the [threat model](https://github.com/aoheyra/aoIdents/blob/master/docs/threat-model.md)
(IDN-19). No secret material, sample private key or placeholder key value is
recorded here.

### Cryptographic suite and identities

Suite ID `0x01` fixes Ed25519 signatures, X25519 agreement,
XChaCha20-Poly1305 AEAD, BLAKE3 hashes, HKDF-SHA-256, Argon2id for backups and
Noise XX `25519_ChaChaPoly_SHA256` for the optional hop handshake. Every signed
or hashed structure uses one registered domain string; the signature preimage
is `u8 domain_len || domain || msg`, so a signature from another use cannot be
reused.

| Concept | Owner and contract |
|---|---|
| Seed | 32 bytes from injected CSPRNG, or fixed input for tests. Signing and agreement keys are derived with distinct HKDF info strings. |
| `NodeId` | `BLAKE3("aoheyra/idn/v1/node-id" || 0x01 || signing_pk || agreement_pk)[..16]`. aoMesh treats these 16 bytes as opaque. |
| Agreement binding | The agreement public key is signed under `aoheyra/idn/v1/bind-agreement`; a substituted key is detectable. |
| `IdentityCard` | Self-signed card carrying the public facts used by contacts and the 8-byte announcement hash. QR strings are `aoheyra:id:<base32>`. |
| Safety number | BLAKE3 under `aoheyra/idn/v1/safety-number`, compared out of band. It is a comparison aid, not a security boundary. |

Secret types zeroize on drop, print `<redacted>` in `Debug`, use explicit
`Clone` and constant-time comparison where needed, and take time and randomness
as parameters. aoheyra holds keys behind the `KeyStore` seam and Android
Keystore; aoMesh and aoNetwork never keep them.

### Rotating tags and sealed content

`RotatingTag` produces a 16-byte link tag and an 8-byte beacon hint per epoch.
aoIdents generates them, aoMesh passes the bytes down and aoNetwork carries
them in `Hello` and beacons for duplicate-link tie-breaking only. aoNetwork
does not interpret, validate or link a tag to a `NodeId`. Successive epochs
are unlinkable in the baseline mode; a pairwise contact-recognisable mode is a
setting behind a flag, not the default.

Messages are sealed with aoIdents' AEAD and signed under registered domains:

- `SealedMessage` (IDN-09) is the 1:1, offline-friendly form. It authenticates
  the sender inside the seal, binds the envelope to the mesh content address as
  associated data, and is addressed to the recipient's public identity.
- Multi-recipient sealed messages (IDN-10) wrap a content key per recipient.
  They use the `aoheyra/idn/v1/wrap` derivation and do not change the mesh
  packet header.
- Public blobs (IDN-11) carry signed presence and channel facts.

Relays cannot read content. They do see the mesh header, so origin and
destination are cleartext metadata by design; see the limits below.

### Replay protection, contacts and trust

Replay checks are layered and must not be merged:

| Check | Owner | Purpose |
|---|---|---|
| `ReplayGuard` | aoIdents, at the recipient | Accepts each `(origin, msg_id)` once within a bounded window. The authenticated local-delivery path uses 1024 ids per sender, 24-hour timestamp tolerance and 64 senders. |
| seen-cache | aoMesh, at every relay | Forwarding dedupe by content address. It is not an acceptance check and never sees keys. |
| Receipt immunity | aoMesh, policy only | Bounded list of already acknowledged ids that are not relayed, re-stored or served by sync. |

Trust is trust-on-first-use plus out-of-band comparison. There is no server,
certificate authority or global directory. A contact stores the first key seen
for a `NodeId`; safety numbers let the user compare it out of band. A changed
key for a known node raises a typed key-change warning rather than being
accepted silently. Rotation statements and revocation notices are signed under
their own domains (IDN-16); a thief who controls an unlocked device can delay
their propagation until contacts receive and act on them.

### Optional neighbour authentication

The hop handshake (IDN-13, M6) is a sans-IO Noise XX state machine driven by
aoMesh over Control frames. The host pins the peer's card by its 8-byte
announcement hash and owns the resulting per-link `HopSessions` outside the
engine. A failed pin or handshake installs no session and never silently falls
back to cleartext. On an encrypted link a radio observer still sees timing and
frame sizes.

### What is deliberately not protected

IDN-19 states the MVP limits explicitly:

- **relay-visible metadata:** origin and destination are visible to every
  relay and radio observer so relays can rate-limit spam (MSH-02). Traffic
  sizes, timing and the contact graph are likewise exposed. Rotating tags hide
  long-term link identity, not packet headers.
- **Deferred forward secrecy:** sealed v1 binds to the recipient's static
  agreement key. Compromise of that key decrypts stored ciphertext ever sealed
  to it. IDN-15 prekeys improve this for messages sealed under deleted prekeys;
  a full ratchet is out of scope.
- Availability is best effort: a relay can drop or delay traffic. Post-delivery
  control of location is impossible; a malicious recipient can forward what it
  receives.
- First-contact impersonation survives until the user compares safety numbers;
  Sybil identities are cheap, though per-origin budgets bound each one.

Layer responsibilities are disjoint: aoNetwork protects the link with
per-link rate limits, strikes and liveness, aoMesh protects routing with headers, budgets
and dedupe, aoIdents protects content and identity, and aoheyra owns
persistence, keystore and OS integration.

Source: aoIdents `docs/threat-model.md`, `docs/adr/0001-crypto-suite-and-encodings.md`,
and aoMesh `docs/protocol.md` sections on authenticated local delivery,
mesh hello and replay integration.
