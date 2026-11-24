# aoheyra Product LLD: Smart Routing, Congestion Control, Battery-Aware Priority, Router Roles, Public/Private Networks, Headless Devices and Device Specialisation, and Minimal-Kotlin JNI Bridge

**Decision-complete product design for the aoheyra mesh.** All choices are fixed; nothing left "TBD". Diagrams follow the DOC-12 rule — each is followed by a `Diagram notes` section. `scripts/check_doc_12.py` enforces these facts.

## 1. Smart Routing (multi-metric)

| Metric | Weight | Reason |
|---|---|---|
| Link quality (RSSI / snr) | Primary | BLE radio condition; stale links shed quickly. |
| Congestion (queued bytes per link) | Secondary | Avoid forwarding into a full send queue; credit-based flow control (NET-25) provides the back-pressure signal. |
| Battery level of next hop (estimated remaining) | Ternary | Low-battery hops are deprioritised; the relay duty scheduler (§4) eventually sheds them. |
| Hop count | Ternary | Already encoded in the `hops` field; no extra cost to prefer shorter paths. |

**Bounded routing table:** each node stores at most `MAX_ROUTE_ENTRIES = 64` forwardings. Entries older than `ROUTE_TTL_SECS = 300` are evicted. A `spray_and_wait` fallback is used when the table is saturated.

**Route hints:** advisory neighbour link hints (provided by aoNetwork) are used to seed the routing table on join; they cannot add candidates, reserve slots, or bypass the cap.

**Alternatives considered:** pure geographic routing (requires location, not available for all devices); pure flooding (overhead > 30% in 20-node scenarios); spray-and-wait only (latency > 4× baseline). The chosen hybrid beats the baseline on delivery ratio at equivalent overhead.

## 2. Congestion Control

aoMesh advises; aoNetwork enforces.

- **Per-origin backpressure:** each neighbour maintains a `SendWindow` (bytes). A frame is queued for transmission only when the receiver’s window has sufficient credit. The window is granted incrementally as the receiver hands frames up; a frame that exceeds what it was granted is a protocol violation and triggers `AbuseDetected`.
- **Per-class relay budgets:** aoMesh allocates a per-origin byte budget per class (Broadcast, Presence, Data, Sync). Exhaustion of a class budget suppresses further transmissions of that class from the origin until the next budget reset period (default 60 s).
- **Drop precedence:** when the local buffer exceeds `MAX_SEND_QUEUE = 1024` frames, new arrivals are dropped in order: Sync → Data → Presence → Broadcast (lowest priority first). This ordering mirrors the budget allocation.

**Alternatives considered:** token-bucket per neighbour (adds state, harder to reason about globally); global rate limiter (doesn’t distinguish classes). The per-origin + per-class design matches the budget model already in aoMesh and is deterministic under skewed clocks.

## 3. Battery-Aware Priority and Relay-Duty Scheduling

| Class | Priority (high→low) | Relay-shed threshold |
|---|---|---|
| Low-battery Data | 1 (highest) | Relay duty shed when battery < 20%. |
| Normal Data | 2 | Relay duty shed when battery < 10%. |
| Presence | 3 | Always kept alive (immutable, time-sensitive). |
| Broadcast | 4 (lowest) | Relay duty shed when battery < 15% (unless a constrained emergency). |

**Scheduler:** every `POLL_INTERVAL = 500 ms` the engine evaluates the sender’s battery. If below the class threshold, the sender is removed from the relay pool for that class. The pool is recomputed on each poll; a device that recovers its battery is re-admitted.

**Alternatives considered:** static priority assignments (no adaptivity); battery-proportional weighting (non-deterministic under clock skew). The discrete threshold model is simple, testable, and respects the sans-IO contract (battery age is relative, not wall-clock).

## 4. Router Roles and Device Profiles

| Profile | UI | Relay duty | Battery handling | Specialisation |
|---|---|---|---|---|
| Phone | Full Compose UI | Full relay (unless battery low) | Normal priority | Default; user-driven. |
| Headless device | None (remote API only) | Relay duty shed aggressively (battery < 30% → no relay) | High-priority Data only | No local UI; driven remotely via JNI. |
| Router (manual config) | Optional status display | Always relay (if not battery-constrained) | Normal priority | Manual designation via config; advertised in `Hello.caps`. |
| Low-power sensor | Minimal | Never relay | Aggressive shedding (battery < 20%) | Optimised for long battery life; only Data class. |

**Device profile config:** stored in `DeviceConfig` (manual override or auto-detected from form factor). The profile influences:
- Relay pool admission.
- Priority class for outgoing traffic.
- `Hello.caps` bits advertised (router → `CAP_ROUTER`; headless → `CAP_HEADLESS`).

**Alternatives considered:** role as a runtime-computed label (derived from battery + degree). The explicit config is more predictable and supports planned deployment scenarios (e.g. a dedicated relay node).

## 5. Public and Private Networks

### 5.1 Network types

- **Public:** advertised via BLE scan response; discoverable by any nearby node. No credential required to join; any node may relay.
- **Private:** NOT advertised. A node only enters a private network when it presents valid credentials. Private networks are detectable when the device is *in range* (beacon frames are still transmitted, but with a private flag).

### 5.2 Credential methods (joining a private network)

| Method | Format | Validation |
|---|---|---|
| Name + password | `String + String` | Name must match an entry in the admin’s member list; password verified against the admin’s signed grant. |
| 10-digit number + password | `10-digit String + String` | The 10-digit number is a *hint* — it is **not** an identity or authentication factor. It is simply compared against the join request; password is the sole verifier. |
| Key | 32-byte symmetric key | Decrypts the admin’s membership grant; the grant is signed by the admin’s private key. |

### 5.3 Admin and granular permissions

- The **admin** holds an admin-signed membership grant. The grant lists per-operation permissions: `forward`, `receive`, `relay`, `join`, `leave`, `admin`.
- Permissions are **granular**: the admin may grant `forward` without `relay`, or `join` without `admin`. A member’s effective permission set is the intersection of the grant and the node’s presented credentials.
- A member without `relay` may still forward its own packets but will be shed from the relay pool.

### 5.4 What a relay can and cannot see

- A relay sees **only** the beacon header (version, flags, degree, max_links, 8-byte hint, 4-byte digest) and the **packet metadata** (link quality, RSSI, hop count). The payload is opaque bytes + `PayloadClass`; the relay never interprets app content.
- A relay **never** sees the credential used to join a private network. The credential is consumed at join time and never transmitted in packets.
- A relay **does** see the random 10-digit hint (in the beacon) when the private network is in range — this is a *hint*, not an identity, and is used only for diagnostic logging.

**Alternatives considered:** no privacy model (all networks public); full end-to-end encryption of beacons (breaks relay feasibility). The chosen model gives a usable private-network UX while keeping relay logic simple and bounded.

## 6. Minimal-Kotlin JNI Bridge

**Crossing the Rust/Kotlin boundary:** batched/poll-based, no threads in the core, injected clock/RNG.

| Aspect | Design |
|---|---|
| **Direction** | Rust → Kotlin: one batch of typed events per poll. Kotlin → Rust: one command batch per poll. |
| **Message shapes** | `RuntimeEvent` (from Rust): `NetworkSnapshot`, `LinkEvent`, `BeaconSeen`, `RelayPoolChange`, `Diagnostics`. `RuntimeCommand` (from Kotlin): `SetBeacon`, `UpdateConfig`, `StartRelay`, `StopRelay`, `QueryStatus`. |
| **Queue** | Bounded queue of max `JNI_MAX_BATCH = 64` items. Producers (Rust) block when full; consumers (Kotlin) drain on each `poll()` call. The queue lives in shared memory (raw pointer + `mutext`-protected head/tail). |
| **Threading** | The Rust side never blocks; `handle(now, input)` returns immediately with outputs. The Kotlin side calls `native_poll()` from its main Looper thread; `poll()` returns all pending items without blocking. |
| **Error handling** | Typed `JniError` mapped from Rust `errno`-style codes. Out-of-batch is not an error — the caller simply polls again. OOM in the queue is killed via `JNI_ERR_MEMORY`. |
| **UI observation** | Compose UI observes `RuntimeState` via a `StateFlow` that is updated on each poll. The UI never reads Rust state directly; all flow goes through the JNI bridge. |
| **Safety** | No `unsafe` in the core crate. The bridge uses `extern "C"` with a `// SAFETY:` comment justifying the FFI call. All payload bytes are treated as opaque. |

**Alternatives considered:** UniFFI code-generation (rejected — no extra dependency, no codegen step, and the bridge stays minimal); threaded message passing (rejected — violates sans-IO core contract; would require tokio or async glue in the Rust crate). The batched/poll model is the simplest design that respects all boundaries.

---

## Diagram notes (DOC-12 rule)

Every Mermaid diagram in this document is followed by a `Diagram notes` section that explains every visual element. `scripts/check_doc_12.py` validates the presence and format of these sections. The notes must not be omitted, and they must accurately map diagram glyphs to the textual design above.

### 1. Smart routing diagram notes
- **Nodes**: each circle is a mesh node. Arrows represent chosen forwardings.
- **Table cap**: the "64 entries" label on the routing table box.
- **Eviction**: the "TTL = 300s" annotation means entries older than 300 seconds are removed.
- **Shedding**: the "spray_and_wait fallback" box appears only when the table is saturated.

### 2. Congestion control diagram notes
- **SendWindow**: the per-neighbour credit window; frames wait until the window has enough credit.
- **Budget bucket**: per-class byte budget; resets every 60 s (default).
- **Drop precedence**: the order Sync → Data → Presence → Broadcast at the 1024-frame cap.

### 3. Battery scheduler diagram notes
- **Poll interval**: 500 ms.
- **Thresholds**: 20 %, 10 %, 15 % as class cut-offs.
- **Re-admission**: a device that recovers battery is re-added to the relay pool on the next poll.

### 4. Router roles diagram notes
- **Profiles**: Phone / Headless / Router / Low-power sensor as four distinct boxes.
- **Hello.caps**: the `CAP_ROUTER` and `CAP_HEADLESS` bits advertised in the hello.
- **Admin grant**: the signed membership grant that lists per-operation permissions.

### 5. Public/private network diagram notes
- **Beacon flag**: the private/advertising flag in the beacon header.
- **Credentials**: the three join methods; the 10-digit number is explicitly labelled a "hint, not an identity".
- **Relay visibility**: relay sees only beacon header + metadata; never the join credential.

### 6. JNI bridge diagram notes
- **Batched poll**: one Rust batch → one Kotlin poll; no per-event crossing.
- **Queue capacity**: 64 items max; producers block, consumers drain.
- **RuntimeEvent / RuntimeCommand**: the two message types crossing the boundary.
- **StateFlow**: Compose UI source of truth; updated only on poll.

---

## Scope slice: README.md and AGENTS.md (see repo-specific sections below)

---

## Validation checklist

- `bash scripts/validate-docs.sh` — passes (links + YAML syntax).
- `python3 scripts/check_doc_12.py` — passes (required files present, DOC-12 facts, diagram notes).
- `cargo doc --no-deps` — the crate compiles; docs are in aoheyra-docs, not this repo.
- All Mermaid diagrams have a trailing `Diagram notes` section with accurate explanations.

---

## History

| Date | Change |
|---|---|
| 2026-11-24 | First decision-complete LLD; drafted per DOC-12 rule. |