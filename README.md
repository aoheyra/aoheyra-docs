# aoheyra-docs

Documentation crate for the aoheyra mesh stack. This repository holds the
cross-repository documentation that does not belong to a single code repo.
The Rust crate contains no runtime code; `cargo doc` renders the README and
the CI check fails if a referenced file is missing.

The product names are **Jan** for networking, **Vent** for identity and trust,
**Ark** for store-and-forward, **McMohan** for location and the offline map,
**aoheyra** for chat and messaging, and **Hog** for the BLE beacon. These are
communication labels, not new crates or wire formats. See
[architecture](docs/architecture.md) for boundaries and diagrams.

## Contents

- [Architecture and subsystem names](docs/architecture.md): product names, system context, layered runtime view and message/discovery sequences.
- [Jan](docs/jan.md): networking engine, signed discovery record, bounds and privacy invariants.
- [Call stacks and request paths](docs/call-stacks.md): function-level call chains for every service, with diagram notes and current-versus-target status.
- [Ownership](docs/ownership.md): one owner per concept and dependency direction.
- [Protocol](docs/protocol.md): packet layout, capability negotiation and wire evolution.
- [LLD](docs/lld.md): smart routing, congestion control, battery-aware priority, router roles, public/private networks with authN/authZ, headless devices, device profiles, and the minimal-Kotlin JNI bridge.
- [Operations](docs/operations.md): build, release, fuzzing and diagnostics.

Each document is owned by the issue that created it. See the repository issues
for the exact scope and acceptance test of every document.
