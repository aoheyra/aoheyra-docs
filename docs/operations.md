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

## Build, release and versioning (DOC-08)

This section is written so a fresh machine can follow it without local
context. aoheyra is Android-only and the native build needs the Android SDK
and NDK; where a command could not be run in the documentation environment,
that is stated rather than implied to have passed.

### Toolchain and prerequisites

| Requirement | Value | Source |
|---|---|---|
| Rust 1.89 | Minimum supported toolchain | `rust-version` in every workspace `Cargo.toml` |
| Edition | 2024 | Workspace manifests |
| Android SDK / NDK | Required for native libraries and device installs | AND-02 spike confirms minSdk (proposed 26) |
| `cargo-ndk` | Required for the documented native build command | APP-01 |
| JDK | 17+ | Android Gradle scaffold |
| Kotlin | Gradle Kotlin DSL, Jetpack Compose | `android/` |

The MSRV is 1.89 because the patched SQLCipher dependency needs it. Every
workspace manifest and CI job must record the same version.

### Native and Android build

From the repository root:

```bash
cargo ndk -t arm64-v8a -t armeabi-v7a -t x86_64 -o android/app/src/main/jniLibs build --release
```

`x86_64` is for emulator UI work only; radio behaviour needs physical phones.
Then, from `android/`:

```bash
./gradlew assembleDebug lintDebug test
```

UniFFI Kotlin bindings are not generated by `master` today: the committed
`android/app/build.gradle.kts` has no UniFFI tasks. The open APP-03 branch
`origin/app-03-uniffi` (PR #54) adds `generateUniFFIBindings` and
`buildUniFFILibrary`, makes `preBuild` depend on `generateUniFFIBindings`,
builds the host cdylib with `cargo build --locked --lib`, and generates Kotlin
with:

```bash
cargo run --locked --features bindgen --bin uniffi-bindgen -- \
  generate --library <host-library> --language kotlin \
  --config crates/aoheyra/uniffi.toml \
  --out-dir android/app/build/generated/source/uniffi/kotlin --no-format
```

Treat that as the binding-generation procedure once APP-03 lands; do not claim
it is present on `master`. **Never hand-edit generated bindings.** The FFI
surface exists only in aoheyra; aoMesh, aoNetwork and aoIdents stay pure Rust.

Rust checks, from the repository root:

```bash
cargo fmt --all -- --check
cargo clippy --workspace --all-targets --all-features -- -D warnings
cargo test --workspace
cargo deny check
cargo deny check licenses
cargo doc --no-deps --all-features
```

`cargo deny check` is the dependency and licence gate;
`cargo deny check licenses` prints the third-party licence report used for
APP-18. The audit configuration is `deny.toml`. The project is dual-licensed
Apache-2.0 or MIT, matching all
three sibling crates. Adding a dependency requires an acceptable licence,
active maintenance, no advisories, MSRV fit and a small footprint.

### Sibling resolution and patches

Committed manifests consume the three siblings by the `v0.1.0` git tag:

```toml
ao_idents = { git = "https://github.com/aoheyra/aoIdents", tag = "v0.1.0" }
ao_mesh   = { git = "https://github.com/aoheyra/aoMesh", tag = "v0.1.0" }
ao_network = { git = "https://github.com/aoheyra/aoNetwork", tag = "v0.1.0" }
```

To co-develop a sibling change, put a `[patch]` section in an **uncommitted**
`.cargo/config.toml` (the paths are documented in aoheyra's
`docs/local-development.md`). Never commit that file or a `[patch]` section.
Before opening a PR, land and tag the sibling change in its own repository,
bump the tag here and delete the override. A PR that depends on an untagged
sibling change is blocked until the tag exists. Note that some Cargo.toml
comments in the current repositories still describe git/master consumption;
the tag policy above is authoritative.

### Tag matrix

Current `v0.1.0` revisions, verified against GitHub tags:

| Repository | Tag | Commit |
|---|---|---|
| aoNetwork | `v0.1.0` | `84f84eadfdaf2134b839b4d5dceeeeacdbf914a0` |
| aoIdents | `v0.1.0` | `8fb173690ba4ade2b80f0459c40e7198bd0eb9ac` |
| aoMesh | `v0.1.0` | `0e9c36a38938412d993e0eea57df9b8a0d76c92f` |
| aoheyra | `v0.1.0` | not yet tagged; release pending (MSH-31 / APP-18) |

Do not invent a revision for aoheyra. Its crate version is already `0.1.0`,
but the repository has no `v0.1.0` tag at the time of writing.

### Release order and CHANGELOG

Tag in dependency order so each tag resolves against already-tagged siblings:

1. aoNetwork
2. aoIdents
3. aoMesh
4. aoheyra

Each repository's `CHANGELOG.md` must describe the user-visible change, the
wire or API compatibility note and the issue IDs in the release. A wire-format
change also requires an ADR, a version bump and a `MeshHello.caps` fallback
where negotiation applies. Tagged releases must resolve together with no
local patches: a fresh checkout of each tag, with no `.cargo/config.toml`
override, must build and pass its checks. The `v0.1.0` release tag for the
stack is only complete once aoheyra consumes all three siblings with no local
patches (MSH-31).
