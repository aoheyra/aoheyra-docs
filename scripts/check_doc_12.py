#!/usr/bin/env python3
"""Validate DOC-12 architecture, subsystem naming and call-stack documentation.

Run from any directory. The script resolves the repository root itself and never
writes files. CI installs PyYAML with the runner image.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path
from urllib.parse import unquote

try:
    import yaml
except ImportError:  # pragma: no cover - CI installs PyYAML with the runner image
    print("PyYAML is required to validate workflow syntax", file=sys.stderr)
    raise SystemExit(2)

ROOT = Path(__file__).resolve().parents[1]

REQUIRED_FILES = (
    "docs/architecture.md",
    "docs/jan.md",
    "docs/call-stacks.md",
    "docs/ownership.md",
    "docs/protocol.md",
)

NAMES = ("Jan", "Vent", "McMohan", "Ark", "aoheyra", "Hog")

CALL_STACK_FACTS = (
    "Status legend",
    "Current, dormant",
    "MainActivity.onCreate",
    "MeshServiceLauncher.start",
    "BleModule",
    "AoHeyra::new",
    "Runtime::start",
    "NetworkAdapter::poll_event",
    "MeshEngine::handle",
    "MessagingService::compose",
    "ContactsService::add_from_qr",
    "LifecycleService::panic_wipe",
    "SettingsService::update",
    "LocationService::start_session",
    "MapService::topology",
    "ChannelService::join",
    "DiagnosticsBundle::new",
    "NodeDirectory::search",
    "Network::set_beacon",
    "open_delivery",
    "Runtime::process_events",
    "Diagram notes",
)


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


def read(relative: str) -> str:
    path = ROOT / relative
    if not path.is_file() or not path.read_text(encoding="utf-8").strip():
        return ""
    return path.read_text(encoding="utf-8")


def diagram_footer_checks() -> list[str]:
    bad: list[str] = []
    for relative in ("docs/architecture.md", "docs/jan.md", "docs/call-stacks.md"):
        text = read(relative)
        lines = text.splitlines()
        diagrams = 0
        notes = 0
        inside = False
        for index, line in enumerate(lines):
            if line.strip() == "```mermaid":
                diagrams += 1
                inside = True
                continue
            if inside and line.strip() == "```":
                inside = False
                window = "\n".join(lines[index + 1 : index + 5])
                if "**Diagram notes:**" in window:
                    notes += 1
                else:
                    bad.append(f"{relative}: diagram ending near line {index + 1} has no footer notes")
        if diagrams != notes:
            bad.append(f"{relative}: {diagrams} diagrams but {notes} diagram footers")
    return bad


def issue_specific_checks() -> list[str]:
    bad: list[str] = []
    readme = read("README.md")
    for relative in REQUIRED_FILES:
        if not read(relative):
            bad.append(f"{relative}: missing or empty")
        if relative not in readme:
            bad.append(f"README.md: missing link to {relative}")

    architecture = read("docs/architecture.md")
    for name in NAMES:
        if name not in architecture:
            bad.append(f"docs/architecture.md: missing subsystem name {name}")
        if name not in readme:
            bad.append(f"README.md: missing subsystem name {name}")

    protocol = read("docs/protocol.md")
    for needle in ("Product names used across repositories", "Hog", "jan:v1:", "SqliteMessageStore"):
        if needle not in protocol:
            bad.append(f"docs/protocol.md: missing required fact {needle!r}")

    ownership = read("docs/ownership.md")
    if "Subsystem names" not in ownership:
        bad.append("docs/ownership.md: missing subsystem name map")

    jan = read("docs/jan.md")
    for needle in ("Hog", "Vent", "Ark", "McMohan", "aoheyra", "jan:v1:"):
        if needle not in jan:
            bad.append(f"docs/jan.md: missing required fact {needle!r}")

    call_stacks = read("docs/call-stacks.md")
    for needle in CALL_STACK_FACTS:
        if needle not in call_stacks:
            bad.append(f"docs/call-stacks.md: missing required fact {needle!r}")

    workflow = (ROOT / ".github/workflows/docs.yml").read_text(encoding="utf-8")
    if "validate DOC-12 architecture and call stacks" not in workflow:
        bad.append(".github/workflows/docs.yml: missing DOC-12 validation step")
    if "python3 scripts/check_doc_12.py" not in workflow:
        bad.append(".github/workflows/docs.yml: does not run check_doc_12.py")

    return bad


def main() -> int:
    bad = markdown_links() + workflow_syntax() + diagram_footer_checks() + issue_specific_checks()
    if bad:
        print("\n".join(sorted(set(bad))), file=sys.stderr)
        return 1
    print("documentation links, workflow syntax and DOC-12 facts are valid")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
