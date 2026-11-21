# aoheyra-docs

Documentation crate for the aoheyra mesh stack. This repository holds the
cross-repository documentation that does not belong to a single code repo.
The Rust crate contains no runtime code; `cargo doc` renders the README and
the CI check fails if a referenced file is missing.

## Contents

- `docs/ownership.md`: one owner per concept and dependency direction.
- `docs/protocol.md`: packet layout, capability negotiation and wire evolution.
- `docs/operations.md`: build, release, fuzzing and diagnostics.

Each document is owned by the issue that created it. See the repository issues
for the exact scope and acceptance test of every document.
