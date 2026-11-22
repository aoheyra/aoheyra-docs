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
