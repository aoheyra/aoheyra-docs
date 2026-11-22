# Operations

This file records reproducible cross-repository procedures. Procedures whose
implementation is still a planned issue are marked as such.

## Running the aoMesh shared `MessageStore` conformance suite

The suite is exported by aoMesh as `ao_mesh::store::conformance::check`. It
must be run twice: once against the in-memory reference in aoMesh, and once in
the aoheyra host test crate against a fresh SQLite backend for every supplied
`StoreLimits`.

### Reference backend

```bash
git clone https://github.com/aoheyra/aoMesh.git
cd aoMesh
cargo test --test store
```

That command runs backend conformance, deterministic replication/priority/age
and ID ordering, relative expiry with a remote timestamp of `u64::MAX`,
malformed envelopes, no-mutation rejection and the 100-insertion stress case.
It does not test SQLite.

### Host backend (APP-05)

aoheyra `master` does not yet contain the SQLite `MessageStore` or its test
file, so this command is the acceptance procedure for that issue, not a claim
that it can run today. Add `crates/aoheyra/tests/mesh_store_conformance.rs`
to the aoheyra repository with a factory that creates a fresh encrypted test
database per call:

```rust
#[test]
fn mesh_store_conformance() {
    ao_mesh::store::conformance::check(|limits| {
        aoheyra::storage::SqliteMessageStore::new_for_test(limits)
    });
}
```

Then run from the aoheyra workspace:

```bash
cd aoheyra
cargo test --test mesh_store_conformance
cargo test --workspace
```

The `StoreLimits` values supplied by the suite are bounded; the factory must
not reuse rows between cases. Insertion and its evictions must be one SQLite
transaction. Do not weaken the suite or add backend-specific skips: the
in-memory reference and SQLite must expose the same ordering, expiry and quota
behaviour.
