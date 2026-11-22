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

## Fuzz coverage and weekly schedule

All fuzz targets and seeds live in the dedicated
[aoheyra-fuzz](https://github.com/aoheyra/aoheyra-fuzz) repository. The code
repositories contain no `fuzz/` directory and no fuzz workflow; adding a parser
to a code repository requires a matching target in aoheyra-fuzz in the same
change. aoheyra itself is docs-only and is covered by repository link and
workflow-syntax validation, not by libFuzzer targets.

### Target inventory

The inventory below is checked against `fuzz/<crate>/fuzz_targets/*.rs` in
aoheyra-fuzz by `scripts/check_doc_07.py`.

| Crate in aoheyra-fuzz | Owning repository | Targets |
|---|---|---|
| `ao-mesh-fuzz` | [aoMesh](https://github.com/aoheyra/aoMesh) | `packet_decode`, `engine_input`, `sync_frames` |
| `ao-network-fuzz` | [aoNetwork](https://github.com/aoheyra/aoNetwork) | `beacon_decode`, `frame_decode`, `reassembler_push` |
| `ao-idents-fuzz` | [aoIdents](https://github.com/aoheyra/aoIdents) | `card_decode`, `group_decode`, `handshake_read`, `prekey_decode`, `seal_decode_open`, `signed_decode` |

Each fuzz crate pins the sibling revision it fuzzes in its `Cargo.toml` and
commits `Cargo.lock`. When a code repository changes its wire format or engine
input surface, update the pinned revision and the target in the same PR.

### Schedule and budget

`.github/workflows/weekly-fuzz.yml` runs on cron
**`30 18 * * 6`**, Saturday 18:30 UTC / Sunday 00:00 IST, and on manual
dispatch. It starts one job per fuzz crate. Each job receives **5400** seconds
of libFuzzer time and splits them evenly across every target found in its
`fuzz_targets` directory, with at least ten minutes per target. The workflow
sets `-rss_limit_mb=2048`, `-timeout=10` and `-max_len=16384`.

On failure, a job uploads `artifacts/` and `corpus/` for that crate as
`fuzz-findings-<crate>` on the failed run. It also opens one labelled triage
issue per crate and run, records the last target started and assigns randomly
from the hardcoded org-member list in the workflow. Re-running the workflow
does not create a duplicate issue for the same run and crate.

### Local setup and reproduction

```bash
rustup toolchain install nightly --component llvm-tools-preview rust-src
cargo install cargo-fuzz --locked
git clone https://github.com/aoheyra/aoheyra-fuzz.git
cd aoheyra-fuzz/fuzz/ao-mesh-fuzz
cargo +nightly fuzz run packet_decode -- -runs=10000
cargo +nightly fuzz run packet_decode -- -max_total_time=60 -rss_limit_mb=2048 -timeout=10 -max_len=16384
```

Use the directory of the crate under test for the other targets. A corpus
directory is created under `corpus/<target>/`; committed seeds live under
`seeds/<target>/` when a known-good input exists.

### Adding or retiring a target

1. Add or remove the target source under the correct
   `fuzz/<crate>/fuzz_targets/` directory.
2. Add or remove the matching `[[bin]]` entry in that crate's `Cargo.toml`.
3. Add or remove seeds under `fuzz/<crate>/seeds/<target>/` when a known-good
   input exists.
4. Update the inventory table above in this document in the same PR.
5. Run `cargo +nightly fuzz run <target> -- -runs=10000` locally before opening
   the PR.

The docs PR validation checks the table against the target files so a target
cannot be added or retired without this document changing in the same change.
Set `FUZZ_REPO` to a local checkout of aoheyra-fuzz when running the script
locally. Without a checkout, `scripts/check-fuzz-inventory.sh` compares the
table above with the canonical target list:

```bash
bash scripts/check-fuzz-inventory.sh
```

### Weekly docs validation

The `aoheyra-docs` job in aoheyra-fuzz's `weekly-fuzz.yml` checks out
`aoheyra/aoheyra-docs` at `main`, so the weekly run validates this repository's
links and workflow syntax as well as the fuzz inventory.
