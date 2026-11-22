# Ownership map and dependency direction

This document is the cross-repository authority for "one owner per concept". It
starts from section 2 of the aoheyra Ownership Map and Issue Backlog (3 Nov
2026) and is reconciled with the current `AGENTS.md` and `README.md` files in
[aoNetwork](https://github.com/aoheyra/aoNetwork),
[aoIdents](https://github.com/aoheyra/aoIdents),
[aoMesh](https://github.com/aoheyra/aoMesh) and
[aoheyra](https://github.com/aoheyra/aoheyra). When an issue assigns a concept
to a repo, that repo owns it; no other repo implements it.

## Concept map

| Concept | Single owner | What the other crates may do | Boundary that must not be crossed |
|---|---|---|---|
| Node identity: keys, `NodeId`, `IdentityCard` | aoIdents (`ao_idents`) | aoMesh treats `NodeId` as an opaque 16-byte value; aoheyra persists identity behind a keystore seam; aoNetwork never sees it. | aoMesh keeps no keys and does not derive node ids; aoNetwork has no identity types. |
| Rotating link tag and beacon hint (`RotatingTag`) | aoIdents generates | aoMesh passes the bytes down; aoNetwork carries them in `Hello`/beacon and uses the tag only for duplicate-link tie-break. | aoNetwork may not interpret, validate or derive a tag; it must not link it to `NodeId`. |
| Link `Hello` (version, caps, tag, opaque blob) | aoNetwork, unauthenticated | aoMesh puts a signed, fixed-width `MeshHello` in the opaque `app_hello` blob. | aoNetwork carries `app_hello` as opaque bytes; it does not parse mesh signatures or capabilities. |
| Neighbour authentication and hop encryption | aoIdents handshake state machine (optional, M6) | aoMesh drives the handshake over Control frames; the aoheyra host owns cards and `HopSessions`. | No crypto state, keys or handshakes inside aoMesh's engine or aoNetwork. |
| End-to-end encryption, signatures and recipient replay guard | aoIdents | aoMesh calls the seams and treats payload bytes as opaque; aoheyra supplies keys and persistence. | Do not weaken signature checks or merge the replay guard with forwarding dedupe. |
| Packet header, TTL, hop count, `MessageId` | aoMesh | aoheyra sees only delivered payloads; aoNetwork carries encoded packets on the Message channel. | No other crate defines a packet class, header field, TTL or content address. |
| Forwarding dedupe (seen-cache) | aoMesh | aoIdents' `ReplayGuard` is a different check: per-sender acceptance at the final recipient. | Never merge the two caches or reuse their state. |
| Rate limiting | aoNetwork per link (bytes and frames, protocol-blind); aoMesh per origin and per class (relay budgets) | Inputs differ: radio link vs claimed origin and packet class. | No shared limiter code; a neighbour cannot be blamed for an origin-only budget denial. |
| Coalescing and expiry mechanism | aoNetwork provides `coalesce_key` and `expires_at` | aoMesh chooses the keys and lifetimes (telemetry latest-wins, presence trickle, message lifetimes). | aoNetwork does not know what a message or a location update is. |
| Degree cap, slots and link classes | aoNetwork enforces | aoMesh advises through `set_link_hint(peer, LinkHintPreference)`; aoheyra supplies the numbers. | Hints are advisory only: they cannot add a candidate, reserve a slot or bypass `max_links`. |
| Liveness | aoNetwork ping/pong per link | aoMesh presence is mesh-wide gossip with a different purpose and lifetime. | Presence never becomes a radio keepalive, and a keepalive never becomes a directory entry. |
| Radio neighbour table | aoNetwork `NeighborTable`/peer table | aoMesh keeps a separate neighbour entry for verified mesh peers; aoheyra never persists radio peers. | `PeerKey` is a radio address, not an identity. |
| Mesh-wide node directory | aoMesh `NodeDirectory`, ephemeral | aoheyra derives map items from it and from aoNetwork's link view. | No card fetching, payload interpretation or persistence inside the directory. |
| Contact book, trust on first use and safety numbers | aoIdents logic | aoheyra implements the `ContactStore` seam and persists contacts; Kotlin only renders them through UniFFI. | aoIdents performs no I/O; aoheyra makes no independent trust decision. |
| Store-and-forward policy and sync | aoMesh (`MessageStore` trait, in-memory reference, summary/digest, sync frames) | aoheyra supplies the SQLite implementation and XORs nothing into wire bytes; aoNetwork carries sync frames on Bulk. | aoMesh owns no store file and never interprets payloads; aoheyra does not reimplement routing policy. |
| App payload schema (`Text`, `Location`, `Profile`, `Receipt`) | aoheyra | aoMesh sees opaque bytes plus a `PayloadClass`; aoIdents seals and encrypts them. | No app field becomes a mesh header or a sibling-crate type. |
| Persistence | aoheyra only (Rust SQLite is the single source of truth) | Kotlin reads through UniFFI; there is no Room database and no authoritative Kotlin cache. | Sibling crates never open files or persist state. |
| Time and randomness | Each crate takes `now` and an RNG as parameters | The app supplies platform clocks and OS randomness at the edge. | No shared utility crate and no global clock/RNG inside core logic. |
| Android radio | Kotlin `:ble` module in `aoheyra/android` | It implements aoNetwork's `NativeSink`/`NativeEvents` contract and decodes no protocol bytes. | Kotlin never retries, times out, enforces the degree cap or builds GATT protocol bytes itself. |
| FFI | aoheyra only (UniFFI) | Sibling crates stay pure Rust. | No FFI, Android types or JNI in aoMesh, aoNetwork or aoIdents. |
| Location: capture, permission and precision | aoheyra plus Android | aoMesh provides a latest-wins class; aoIdents signs and encrypts. | Precise coordinates never leave the device unless a precise sharing session is active. |
| Map and tiles | Android, offline-first | aoheyra's map-data service supplies derived items; aoMesh supplies a node directory. | The map never requires internet for core function. |
| Diagnostics and data lifecycle | aoheyra (`APP-15`/`APP-16`) | aoNetwork and aoMesh expose plain-data snapshots; aoIdents redacts secrets in `Debug`. | No message text, keys or coordinates in a diagnostics bundle. |

## Dependency direction

```text
aoNetwork <-- aoMesh --> aoIdents
     ^           ^          ^
     |           |          |
     +---------- aoheyra ---+
```

- `aoMesh` depends on `aoNetwork` and `aoIdents`.
- `aoheyra` depends on all three and is the only crate with UniFFI.
- `aoNetwork` and `aoIdents` never depend on each other, directly or through a
  shared utility crate.
- The arrows are compile-time dependencies in `Cargo.toml`, not a statement
  about who calls whom at runtime: the aoheyra runtime owns one object from
  each sibling and wires them together.

## Sibling consumption and patches

Sibling crates are consumed **by git tag**: the policy is `tag = "v0.1.0"`
for aoheyra and the pending MSH-31 change in aoMesh. The current aoMesh
`master` `Cargo.toml` still pins the `ao_network` and `ao_idents` git branches,
so the published tags are not yet consumed everywhere; that gap is tracked by
MSH-31 and is documented in [build, release and versioning](operations.md)
(DOC-08). A local `[patch]` override in an uncommitted `.cargo/config.toml` is
allowed only while co-developing a sibling change. It must never appear in a
commit, and a PR that needs an untagged sibling change is blocked until that
change lands and is tagged in its own repository. Release order is aoNetwork,
aoIdents, aoMesh, then aoheyra.

## Where to verify each boundary

| Repository | Authority file | Concept |
|---|---|---|
| aoNetwork | `AGENTS.md`, `README.md`, `docs/native-contract.md` | Frames, link state, degree cap, native radio contract |
| aoIdents | `AGENTS.md`, `docs/adr/0001-crypto-suite-and-encodings.md`, `docs/threat-model.md` | Keys, domains, trust and threat limits |
| aoMesh | `AGENTS.md`, `docs/adr/0001-routing-per-traffic-class.md`, `docs/protocol.md` | Classes, defaults, packet and sync formats |
| aoheyra | `AGENTS.md`, `docs/adr/` | App schema, persistence, FFI, Android |
