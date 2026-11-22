#!/usr/bin/env python3
"""Check documentation links, workflow syntax and DOC issue-specific facts.

Run from any directory with TMPDIR set to an approved temporary path. The
script uses the checked-out worktree as its root and never writes files.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path
from urllib.parse import unquote

try:
    import yaml
except ImportError:  # pragma: no cover - CI installs PyYAML with the runner image
    print("PyYAML is required to validate workflow syntax", file=sys.stderr)
    raise SystemExit(2)

ROOT = Path(__file__).resolve().parents[1]

DOC_CHECKS: dict[str, tuple[str, tuple[str, ...]]] = {
    "01": (
        "docs/ownership.md",
        (
            "Concept map",
            "Dependency direction",
            "Sibling consumption and patches",
            "aoNetwork <-- aoMesh --> aoIdents",
            "never depend on each other",
            "git tag",
            "[patch]",
        ),
    ),
    "02": (
        "docs/protocol.md",
        (
            "v1 packet layout",
            "immutable prefix",
            "ttl",
            "hops",
            "MessageId",
            "MAX_PAYLOAD",
            "2048",
            "MeshHello",
            "CAP_SYNC_V1",
            "CAP_PRESENCE_V1",
            "1 << 4",
            "ADR-0002",
            "protocol change",
        ),
    ),
    "03": (
        "docs/protocol.md",
        (
            "NativeSink",
            "NativeEvents",
            "set_advertising",
            "set_scanning",
            "connect",
            "write",
            "disconnect",
            "one serial GATT thread",
            "single-flight",
            "LinkHintPreference",
            "advisory",
            "AND-04",
            "AND-09",
            "docs/native-contract.md",
        ),
    ),
    "04": (
        "docs/protocol.md",
        (
            "NodeId",
            "IdentityCard",
            "RotatingTag",
            "ReplayGuard",
            "seen-cache",
            "trust-on-first-use",
            "safety number",
            "IDN-19",
            "forward secrecy",
            "relay-visible metadata",
        ),
    ),
    "05": (
        "docs/protocol.md",
        (
            "MessageStore",
            "conformance::check",
            "cargo test --test store",
            "CAP_SYNC_V1",
            "CAP_SYNC_V2",
            "SyncNeed",
            "SprayItem",
            "Purge",
            "immunity",
            "relative age",
            "MAX_SNAPSHOT_LEN",
        ),
    ),
    "06": (
        "docs/protocol.md",
        (
            "PresenceConfig",
            "DirectoryConfig",
            "RouteHintConfig",
            "TelemetryConfig",
            "60_000",
            "900_000",
            "30 * 60 * 1_000",
            "300_000",
            "30_000",
            "10_000",
            "512",
            "redacted",
            "MSH-02",
        ),
    ),
    "07": (
        "docs/operations.md",
        (
            "aoheyra-fuzz",
            "30 18 * * 6",
            "5400",
            "cargo +nightly fuzz run",
            "fuzz-findings-",
            "packet_decode",
            "engine_input",
            "sync_frames",
            "beacon_decode",
            "frame_decode",
            "reassembler_push",
            "card_decode",
            "group_decode",
            "handshake_read",
            "prekey_decode",
            "seal_decode_open",
            "signed_decode",
        ),
    ),
    "08": (
        "docs/operations.md",
        (
            "Rust 1.85",
            "cargo ndk",
            "arm64-v8a",
            "armeabi-v7a",
            "x86_64",
            "assembleDebug",
            "generateUniFFIBindings",
            "cargo deny check licenses",
            "CHANGELOG",
            "84f84eadfdaf2134b839b4d5dceeeeacdbf914a0",
            "8fb173690ba4ade2b80f0459c40e7198bd0eb9ac",
            "0e9c36a38938412d993e0eea57df9b8a0d76c92f",
        ),
    ),
    "09": (
        "docs/protocol.md",
        (
            "PAYLOAD_VERSION",
            "MAX_TEXT_BYTES",
            "MAX_ENCODED_LEN",
            "APPROX_100M_GRID_E6",
            "APPROX_100M_ACCURACY_M",
            "3600",
            "round_trip_text",
            "off_never_encodes_coordinates",
            "stop sharing",
            "opaque",
        ),
    ),
    "10": (
        "docs/operations.md",
        (
            "MeshSnapshot",
            "duplicate_packets",
            "no message text",
            "no keys",
            "retention",
            "secure wipe",
            "VACUUM",
            "auto-backup",
            "SQLCipher",
            "cargo test --test observability",
        ),
    ),
}


def markdown_links() -> list[str]:
    bad: list[str] = []
    for path in ROOT.rglob("*.md"):
        if ".git" in path.parts:
            continue
        text = path.read_text(encoding="utf-8")
        for match in re.finditer(r"\[[^\]]*\]\(([^)]+)\)", text):
            raw = match.group(1).strip()
            if raw.startswith("<") and raw.endswith(">"):
                raw = raw[1:-1]
            if not raw or raw.startswith("#"):
                continue
            target = raw.split("#", 1)[0].split("?", 1)[0]
            if not target or "://" in target or target.startswith(("mailto:", "data:")):
                continue
            resolved = path.parent / unquote(target)
            if not resolved.exists():
                bad.append(f"{path.relative_to(ROOT)}: missing link target {target}")
    return bad


def workflow_syntax() -> list[str]:
    bad: list[str] = []
    workflow_dir = ROOT / ".github" / "workflows"
    for path in sorted(workflow_dir.glob("*.y*ml")):
        try:
            yaml.safe_load(path.read_text(encoding="utf-8"))
        except yaml.YAMLError as error:
            bad.append(f"{path.relative_to(ROOT)}: invalid YAML: {error}")
    return bad


def selected_doc() -> tuple[str, str]:
    stem = Path(__file__).stem
    doc_id = stem.rsplit("_", 1)[-1]
    if doc_id not in DOC_CHECKS:
        raise SystemExit(f"unknown validation script: {stem}")
    path, _ = DOC_CHECKS[doc_id]
    return doc_id, path


def issue_specific_checks(doc_id: str) -> list[str]:
    path, required = DOC_CHECKS[doc_id]
    doc = ROOT / path
    bad: list[str] = []
    if not doc.is_file() or not doc.read_text(encoding="utf-8").strip():
        return [f"{path}: missing or empty"]
    text = doc.read_text(encoding="utf-8")
    for needle in required:
        if needle not in text:
            bad.append(f"{path}: missing required fact {needle!r}")
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    if path not in readme:
        bad.append(f"README.md: missing link to {path}")
    if doc_id == "07":
        bad.extend(fuzz_target_checks(text))
    return bad


def fuzz_target_checks(text: str) -> list[str]:
    fuzz_repo = Path(os.environ.get("FUZZ_REPO", ROOT / ".fuzz-inventory")).resolve()
    target_dirs = sorted((fuzz_repo / "fuzz").glob("*/fuzz_targets"))
    if not target_dirs:
        # Without an aoheyra-fuzz checkout, compare the documented table with
        # the canonical inventory so the docs remain self-checking.
        inventory = ROOT / "scripts" / "check-fuzz-inventory.sh"
        result = subprocess.run(
            ["bash", str(inventory)],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode:
            return [result.stderr.strip() or f"{inventory.name}: inventory check failed"]
        return []
    bad: list[str] = []
    grouped: dict[str, list[str]] = {}
    for directory in target_dirs:
        crate = directory.parent.name
        grouped[crate] = sorted(p.stem for p in directory.glob("*.rs"))
        for target in grouped[crate]:
            if f"`{target}`" not in text:
                bad.append(f"docs/operations.md: missing fuzz target {crate}/{target}")
    for crate, targets in grouped.items():
        if crate not in text:
            bad.append(f"docs/operations.md: missing fuzz crate {crate}")
        if len(targets) != len(set(targets)):
            bad.append(f"{crate}: duplicate target names in checkout")
    return bad


def main() -> int:
    doc_id, _ = selected_doc()
    bad = markdown_links() + workflow_syntax() + issue_specific_checks(doc_id)
    if bad:
        print("\n".join(sorted(set(bad))), file=sys.stderr)
        return 1
    print(f"documentation links, workflow syntax and DOC-{doc_id} facts are valid")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
