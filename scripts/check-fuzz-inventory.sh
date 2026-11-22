#!/usr/bin/env bash
# Check that the DOC-07 target inventory matches the canonical fuzz targets.
# Run from any directory; the script resolves the repository root itself.
set -euo pipefail

cd "$(dirname "$0")/.."

python3 - <<'PY'
from pathlib import Path
import re
import sys

canonical = {
    "packet_decode",
    "engine_input",
    "sync_frames",
    "beacon_decode",
    "frame_decode",
    "reassembler_push",
    "seal_decode_open",
    "card_decode",
    "signed_decode",
    "group_decode",
    "prekey_decode",
    "handshake_read",
}

header = "| Crate in aoheyra-fuzz | Owning repository | Targets |"
found = []
in_table = False

for line in Path("docs/operations.md").read_text(encoding="utf-8").splitlines():
    if line.strip() == header:
        in_table = True
        continue
    if not in_table:
        continue
    if not line.lstrip().startswith("|"):
        break
    cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
    if len(cells) != 3 or not re.fullmatch(r"`ao-[a-z]+-fuzz`", cells[0]):
        continue
    found.extend(re.findall(r"`([^`]+)`", cells[2]))

problems = []
if len(found) != len(set(found)):
    duplicates = sorted({name for name in found if found.count(name) > 1})
    problems.append(f"duplicate target entries: {', '.join(duplicates)}")
missing = sorted(canonical - set(found))
extra = sorted(set(found) - canonical)
if missing:
    problems.append(f"missing targets: {', '.join(missing)}")
if extra:
    problems.append(f"unknown targets: {', '.join(extra)}")

if problems:
    print("\n".join(problems), file=sys.stderr)
    sys.exit(1)

print(f"fuzz inventory matches all {len(canonical)} canonical targets")
PY