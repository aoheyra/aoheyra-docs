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
## Store, sync and receipt lifecycle

aoMesh owns store-and-forward **policy**. It never opens a database, keeps
application keys or interprets payload bytes. The aoheyra host supplies a
SQLite `MessageStore` implementation (APP-05) and owns every insert, purge and
restart file. The current aoheyra `master` branch does not yet contain that
SQLite implementation; it is a required host seam, not an engine feature.

### `MessageStore` contract, quotas and eviction

`store::MessageStore` is the seam implemented by aoMesh's `MemoryStore`
reference and by the host backend:

```rust
fn put(&mut self, now: u64, entry: StoredMessage) -> Result<Vec<MessageId>, StoreError>;
fn get(&self, now: u64, id: &MessageId) -> Option<&StoredMessage>;
fn by_destination(&self, now: u64, dst: &NodeId) -> Vec<MessageId>;
fn summary(&self, now: u64) -> Vec<MessageId>;
fn expire(&mut self, now: u64) -> Vec<MessageId>;
fn evict(&mut self, id: &MessageId) -> Option<StoredMessage>;
```

Results and summaries are lexicographic by `MessageId`. `put` first removes
expired entries, then evicts within each violated quota scope, and must be
atomic with its evictions in SQLite. Eviction order is fewest remaining spray
copies, larger priority number, oldest `first_seen`, then message id.
Duplicate insertion never refreshes metadata.

| Default quota | Value |
|---|---:|
| Entries | 1024 |
| Total encoded bytes | 2 MiB |
| Per origin | 256 KiB |
| Direct | 2 MiB |
| Broadcast | 512 KiB |
| Presence | 64 KiB |
| Telemetry | 0: never stored |

A stored envelope is at most `MAX_PAYLOAD + 512` bytes. Callers verify
authenticity before insertion; the store parses only the bounded header.
Local metadata (`copies_left`, `first_seen`, `received_at`, `priority`,
`received_from`, `age_ms`) is not wire data. Expiry compares relative age plus
local elapsed time against the sender's lifetime and the class ceiling.
Remote `created_ms` never decides expiry.

The shared backend suite is exported as `ao_mesh::store::conformance::check`.
aoMesh runs it against `MemoryStore` with `cargo test --test store`; the host
must run the same function against a fresh SQLite backend factory. The exact
copy-pasteable command is in [operations](operations.md).

### Summary, beacon digest and sync

The host submits live ids through `MeshInput::StoreSummary`.
`sync::StoreSummary` sorts and deduplicates them, exposes sorted eight-byte
prefixes and hashes the full ids plus count into a four-byte digest. A change
is debounced 200 ms before one `MeshOutput::SetBeacon`; a change back to the
published value cancels it, and a backwards clock cannot shorten the wait.
The digest is a change detector, not a proof of equality.

Sync frames travel on aoNetwork's Bulk channel and are engine-to-engine
control frames, not signed mesh packets. The items inside them are complete
encoded mesh packets. The receiving engine checks bounded decode, content
address and storable class; final signature verification and insertion remain
with the store owner.

| Capability | Flow |
|---|---|
| `CAP_SYNC_V1` (MSH-14) | Five-byte header: magic `0x53`, version `1`, tag `Digest`/`Summary`/`Item`/`Done`, two-byte big-endian length. Summary carries up to 1024 sorted 8-byte prefixes. Missing prefixes produce `MeshOutput::SyncNeed`; the host answers with `MeshInput::SyncItems`. `Done` from both sides precedes `ReleaseOpportunistic`. Per-contact budget 256 KiB, per-frame limit 15 KiB, deadline 20 s. |
| `CAP_SYNC_V2` (MSH-15) | Preferred when both peers set it. Range keys are a 16-byte prefix plus a bit count, with canonical trailing zero bits. Differing ranges split until they hold at most 32 ids, then full ids are exchanged through `Ids` and the existing v1 `Item`/`Done` transfer and budget apply. |

Telemetry is never offered to `SyncItem`. A peer without either capability
stays on the beacon-digest path. Equal digests end the exchange without
releasing the link, which may still carry ordinary traffic.

### Spray tickets, receipts and immunity

Direct packets use binary spray-and-wait (MSH-16, `CAP_SPRAY_V1`). A six-byte
envelope before the encoded packet carries magic `0x54`, version `1`, tag `1`,
one byte of remaining copies and a little-endian inner length. A
non-destination contact receives `floor(copies_left / 2)` tickets; the
destination receives one and ends the spray. The same count survives store and
sync as `StoreMetadata::copies_left` and `SyncFrame::SprayItem`; the engine
holds at most 4096 live tickets.

A successful authenticated delivery on a `CAP_RECEIPT_V1` link emits a signed
receipt envelope. Verification is self-contained: the attached public identity
is proved to own the original destination, the acknowledged id is re-derived,
and the acknowledgement is checked under the existing packet domain. An
accepted receipt produces `MeshOutput::Purge` for the host store and
`MeshOutput::Delivered` at the origin. It also inserts a bounded immunity
entry: 512 ids, 300 seconds, 16 frames per contact burst. Immune ids are not
relayed, re-stored or served from sync. This is distinct from aoIdents'
recipient-side `ReplayGuard` and from the forwarding seen-cache.

### Restart snapshots

The host owns the MSH-29 snapshot bytes. `MeshEngine::snapshot()` emits magic
`AMSH`, version `1`, four little-endian section counts and BTreeMap-ordered
sections for seen entries, seen eviction order, receipt immunity and spray
tickets. Stored packets, config, clock, RNG state and link capabilities are
deliberately excluded. `MAX_SNAPSHOT_LEN` is 4 MiB; bad magic, wrong version,
oversized or truncated input, trailing bytes, count mismatches, duplicate
entries and invalid receipt wires are typed `SnapshotError` values before any
state changes. Restore uses the same config and RNG seed, then the host
re-announces live links with `MeshInput::LinkUp`.

Sources: aoMesh `src/store.rs`, `src/sync.rs`, `src/spray.rs`, `src/receipt.rs`,
`src/snapshot.rs`, `docs/adr/message-store.md`, `docs/protocol.md` and ADR-0001.
## Mesh-wide ephemeral state and its bounds

All state in this section is local, bounded and ephemeral. aoMesh's
**`NodeDirectory`** is a mesh-wide view built from verified presence facts;
aoNetwork's **neighbour table** is a radio-local view of discovered peers that
evicts after 30 seconds. They are different tables with different purposes.
aoheyra's map-data service derives map items from both: directory facts supply
distant nodes and last known location, and the link view supplies currently
connected neighbours. Neither table is persisted by aoMesh.

The source of truth for every parameter is the MSH-02 table in
[aoMesh ADR-0001](https://github.com/aoheyra/aoMesh/blob/master/docs/adr/0001-routing-per-traffic-class.md)
and the `Default` implementation of each config struct; do not change a number
here without the measured justification required by MSH-02.

### Presence announcements (MSH-19)

A Presence announcement is an ordinary signed `PacketClass::Presence` packet
with no destination and TTL clamped to 3. It is emitted and accepted only on
links whose negotiated caps include `CAP_PRESENCE_V1` (`1 << 4`). The fixed
150-byte payload is:

| Offset | Size | Field |
|---:|---:|---|
| 0 | 1 | Magic `0x56` |
| 1 | 1 | Version `1` |
| 2 | 8 | `card_hash` announcement hash |
| 10 | 4 | Capability bits, big-endian |
| 14 | 8 | Per-origin monotonic `seq`, big-endian |
| 22 | 32 | Origin Ed25519 verification key |
| 54 | 32 | Origin X25519 agreement key |
| 86 | 64 | Agreement-key binding signature |

Every relay verifies the body, derives `origin` from the carried keys and
checks the packet signature under `aoheyra/mesh/v1/packet`. The host borrows its
identity and card hash on each `MeshInput::Tick`, declares resolvable hashes
through `MeshInput::KnownCards`, and consumes `MeshOutput::CardFetch`. The
engine retains no key.

| `PresenceConfig` default | Value | Reason |
|---|---:|---|
| `enabled` | `true` | Cap-gated on each link. |
| `max_entries` | 1024 | Bounds learned nodes. |
| `max_known_cards` | 1024 | Bounds one host input. |
| `quick_ms` | 1000 ms | Bounded convergence after a change. |
| `base_interval_ms` | 60_000 ms | First quiet refresh. |
| `steady_interval_ms` | 900_000 ms | 15-minute steady bound. |
| `lifetime_s` | 1800 s | Matches the ADR-0001 30-minute lifetime. |

A change carries its scheduled facts, so later ticks cannot postpone the first
announcement. Quiet refreshes double from one minute to the steady bound.
Fresh announcements use suppression with Presence TTL 3 and are sent only to
capable links.

### NodeDirectory (MSH-20)

An observation is typed: node id, card hash, caps, per-origin `seq`, estimated
hop distance, via-node, observation time and opaque bounded location bytes.
The directory does not fetch cards or interpret location. Entries expire from
local receipt time using a high-water-mark clock; peer-supplied observation
time is clamped for display ordering only and cannot change expiry.

| `DirectoryConfig` default | Value | Reason |
|---|---:|---|
| `capacity` | 256 | About 80 KiB with indexes. |
| `stale_after_ms` | `30 * 60 * 1_000` ms | One missed trickle refresh is tolerated. |
| `max_location_bytes` | 64 | Bounds hostile claims; schema belongs to MSH-22/APP-07. |
| `max_change_events` | 64 | Coalesced UI events per node. |

A lower `seq` is ignored. An equal or higher `seq` refreshes local freshness
and LRU position but emits an `Updated` event only when a visible field
changes. A full table evicts least-recently-seen. Changes reach the host as
`MeshOutput::DirectoryChanged`; the UI queries entries rather than receiving
location bytes in the event stream.

### Reverse-path route hints (MSH-21)

A hint says: the freshest observation for destination D arrived from verified
neighbour N, H hops away. It is local routing advice, never signed, never sent
to a peer and never used to authenticate a packet. Sources are verified MSH-19
announcements through the directory and host facts through
`MeshInput::ObserveNode`. Observations from links that are down or unverified
are ignored, as are zero-hop or over-ceiling hop counts.

| `RouteHintConfig` default | Value | Reason |
|---|---:|---|
| `mode` | `SubstituteCopy` | Measured latency win with unchanged transmissions. |
| `max_entries` | 1024 | Bounded per-destination state. |
| `lifetime_ms` | 300_000 ms | Shorter than one presence refresh. |
| `max_hops` | 8 | Matches Direct's TTL. |

Hints rank by `(hops ascending, seq descending, LinkId ascending)`; an exact
tie does not refresh expiry. `Tick` expires hints and `LinkDown` removes every
hint supplied by that link. With `SubstituteCopy`, a fresh hint replaces one
ordinary spray recipient, so transmission count and ticket accounting do not
grow. `AdditiveUnicast` was measured and rejected because it added one send.

### Telemetry (MSH-22)

Telemetry reuses class 4 and the existing packet signature domain. Its opaque
payload prefix is version `1`, a one-byte application `kind` and a big-endian
`u64` sequence. The coalescing key is BLAKE3 over
`aoheyra/mesh/v1/telemetry/coalesce || origin(16) || kind(1)`, so a newer
sequence replaces an older waiting frame in aoNetwork's send queue. aoMesh
does not interpret `kind`.

| `TelemetryConfig` default | Value | Reason |
|---|---:|---|
| `expiry_ms` | 30_000 ms | Tighter than ADR-0001's original 5-minute value. |
| `rate_limit_ms` | 10_000 ms | One accepted update per origin per 10 s. |
| `hop_limit` | 3 | Same class TTL as ADR-0001. |
| `max_entries` | 512 | Bounds freshness and rate state. |

The effective window is `min(sender lifetime, 30 s)`. Remote `created_ms` is
ignored; local monotonic `now` alone drives freshness, eviction and throttling.
Stale, expired, throttled and hop-limited updates are silent drops. Only
malformed frames or content-address mismatches earn a neighbour penalty.
Telemetry is never stored or synced.

### Redacted diagnostics view

The MSH-30 `MeshSnapshot` exposes only counters and gauges: duplicate
verdicts, suppressed relays, store id count, sync bytes, neighbour penalty
events and current scores, seen-cache records and pending suppression windows.
All content-derived fields are **redacted by omission**: no packet text,
`MessageId`, key, identity, contact identifier or coordinate appears in the
snapshot. Adding or changing a field bumps `MESH_SNAPSHOT_VERSION`; it does not
change any packet, sync or beacon bytes.

Sources: aoMesh `src/presence.rs`, `src/directory.rs`, `src/routehint.rs`,
`src/telemetry.rs`, `src/observability.rs`, `docs/protocol.md` and ADR-0001.

## Application payload schema and privacy (DOC-09)

This schema is owned by aoheyra. aoMesh treats these bytes as **opaque**: it
chooses a `PacketClass` for them, bounds them at 2048 bytes and relays them
without reading a single application field. aoIdents seals and signs them.
The implementation and round-trip tests are in APP-07
(`crates/aoheyra/src/payload.rs`); the sharing-session rules are the contract
of APP-12. Source of truth: [aoheyra ADR-0003](https://github.com/aoheyra/aoheyra/blob/master/docs/adr/0003-app-payload-schema.md)
and the payload module.

### Versioned payload table

Every payload starts with a one-byte version (`PAYLOAD_VERSION = 1`) and a
one-byte kind. Unknown versions and kinds are rejected with a typed
`PayloadError`; decoding consumes the input exactly, so trailing bytes are
rejected. All integers are big-endian.

The implementation names the caps `MAX_TEXT_BYTES = 1024`,
`MAX_TEXT_ENCODED_LEN = 4 + MAX_TEXT_BYTES`,
`MAX_PROFILE_ENCODED_LEN = 4 + 32 + 1 + 160 + 8 = 205`,
`RECEIPT_ENCODED_LEN = 19`, `OFF_ENCODED_LEN = 7`,
`PRECISE_ENCODED_LEN = 17`, `PRECISE_WITH_HEADING_ENCODED_LEN = 19` and
`MAX_ENCODED_LEN = 2048`. The approximate-location constants are
`APPROX_100M_GRID_E6 = 1000` and `APPROX_100M_ACCURACY_M = 150`.

| Kind | ID | Layout | Size | Mesh class |
|---|---:|---|---|---|
| Text | 1 | `ver | kind | text_len:u16 | UTF-8 text` | 4..1028 bytes (text 1..=1024) | Direct |
| Location | 2 | `ver | kind | precision_flags | timestamp_s:u32 | [lat_e6:i32, lon_e6:i32, accuracy_m:u16, heading_tenths:u16]` | 7 / 17 / 19 bytes | Telemetry |
| Profile | 3 | `ver | kind | flags | name_len:u8 | name | bio_len:u8 | bio | [avatar_hash:8]` | up to 205 bytes | Presence |
| Receipt | 4 | `ver | kind | status:u8 | message_id:16` | 19 bytes | Direct |

Text must be non-empty UTF-8 and at most 1024 bytes. A profile name is at most
32 bytes, a bio at most 160 bytes, and the optional 8-byte avatar hash is an
opaque application identifier, never an encryption key; its presence is
signalled by bit 0 of the profile flags. A receipt status is 1 (delivered) or
2 (read) and carries the 16-byte id of the message being acknowledged. This is
the application-level status shown in chat and is distinct from aoMesh's
internal signed receipt envelope (MSH-17), which never sees an application
payload. The maximum encoded size of any kind fits inside one mesh packet,
so no application payload needs fragmentation.

### Location encoding

Coordinates are signed 1e-6 degrees, the unit Android locations use, with
latitude in ±90,000,000 and longitude in ±180,000,000. `timestamp_s` is a
`u32` Unix timestamp in whole seconds. Accuracy is an unsigned 16-bit value in
metres and must be positive whenever coordinates are present. Heading, when
bit 7 of `precision_flags` is set, is an unsigned 16-bit value in tenths of a
degree, 0..=3600. Bit 7 is forbidden with precision `off`, and bits 2..6 must
be zero.

| Precision | Bits 0..1 | Encoded length | Coordinates on the wire |
|---|---:|---:|---|
| Precise | 0 | 17 bytes, or 19 with heading | Exactly the supplied 1e-6 degree values |
| About 100 m | 1 | 17 bytes, or 19 with heading | Rounded onto a 0.001 degree grid before leaving the device |
| Off | 2 | 7 bytes | None: no coordinates, accuracy or heading |

`About 100 m` rounds to the nearest 1000 units of 1e-6 degrees (0.001 degrees,
about 111 m of latitude at the equator) with halfway points upward, and forces
accuracy to at least 150 m. The constructor applies this rounding before any
bytes exist, so neither the in-memory value nor the encoded payload ever
holds the precise input. A decoder rejects an `About 100 m` payload whose
coordinates are off-grid or whose accuracy is finer than the grid supports;
it does not silently treat it as precise. `Off` discards coordinates, accuracy
and heading at construction, and all coordinate accessors return `None`.

### Privacy contract

- **No network egress without user action.** Nothing leaves the device unless
  the user explicitly shares or exports it. The schema defines bytes, not a
  trigger: no field, constructor or codec starts a radio or network operation,
  and no field permits network egress without user action.
- **Precise coordinates never leave the device** unless the sharing session
  is explicitly set to precise. The `About 100 m` quantisation and `Off`
  elision are enforced at construction, and tests inspect outgoing bytes to
  prove the precise values are absent.
- **Sessions, not broadcasts.** APP-12 shares with named recipients for a
  chosen duration at a chosen precision, sealed to those contacts and never
  public by default. Sessions expire on their own.
- **Stop sharing is immediate.** The user's stop sharing action publishes an
  end to an existing session at once, so recipients stop showing the position
  and stale updates do not continue to be relayed. This is a contract of
  APP-12, which is planned and not yet implemented; do not claim it is present
  in code.
- **Transit protection only.** A sealed location payload is confidential on
  the wire, but a malicious recipient can forward what it receives; there is
  no post-delivery control. aoIdents' threat model lists this as an accepted
  MVP limit.

### Traceability to tests

APP-07 round-trip tests, traceable by name in the payload module:

| Test | Property proved |
|---|---|
| `round_trip_text` | Text, including multibyte UTF-8 and the 1024-byte maximum, survives encode/decode |
| `round_trip_location_precise_with_heading` | Full 19-byte precise location round-trips |
| `round_trip_location_approx_100m` | Approximate coordinates are on-grid and accuracy is at least 150 m |
| `round_trip_location_off` | `Off` uses exactly 7 bytes and carries no coordinates |
| `round_trip_profile`, `round_trip_receipt` | Profile and receipt round-trip at their caps |
| `approx_100m_never_encodes_precise_coordinates` | Precise byte patterns are absent from the approximate payload |
| `off_never_encodes_coordinates` | `Off` bytes contain no coordinate patterns |
| `per_variant_caps_fit_inside_mesh_payload` | Every kind fits the aoMesh 2048-byte cap |
| `packet_class_mapping_uses_real_mesh_classes` | Text/Receipt to Direct, Location to Telemetry, Profile to Presence |

APP-12 adds the outgoing-payload inspection test for session precision and
the immediate-stop behaviour; it is not implemented yet and must be linked
here when it lands.
