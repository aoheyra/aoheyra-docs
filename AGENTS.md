# aoheyra-docs AGENTS.md

## Purpose

This repository holds the cross-repository product documentation that does not belong to a single code repo. It owns the decision-complete Low-Level Design (LLD), architecture, protocol, ownership, subsystem maps, call-stacks and operations reference for the aoheyra mesh stack.

## Owns

- Product LLD (`docs/lld.md`): smart routing, congestion control, battery-aware priority, router roles, public/private networks with authN/authZ, headless devices, device profiles, and the minimal-Kotlin JNI bridge.
- Architecture map (`docs/architecture.md`): subsystem names (Jan, Vent, McMohan, Ark, aoheyra, Hog), layered runtime view, message and discovery sequences.
- Protocol reference (`docs/protocol.md`): packet layout, capability negotiation, wire evolution, hop-mutable vs immutable fields.
- Ownership map (`docs/ownership.md`): one owner per concept and dependency direction.
- Jan networking spec (`docs/jan.md`): signed discovery record, bounds, privacy invariants.
- Call-stacks and request paths (`docs/call-stacks.md`): function-level call chains for every service, with diagram notes and current-versus-target status.
- Operations reference (`docs/operations.md`): runtime lifecycle, settings validation, diagnostics bundles and data lifecycle.

## Does not own

- Any production code, runtime, or FFI surface. The LLD and architecture docs describe designs that are implemented later via issues in aoMesh, aoNetwork, aoIdents and aoheyra.
- CI thresholds, workflow changes, or lints in other repos. Changes to those are reviewed and landed in their own repos.
- Tags or version bumps here. Tags are forbidden per MSH-31; sibling crates consumed as untagged git sources pinned by SHA.

## DOC-12 diagram rule

Every Mermaid diagram in any document owned by this repo must be followed by a `Diagram notes` section that explains every visual element. `scripts/check_doc_12.py` enforces the presence and format of these sections. The notes must not be omitted, and they must accurately map diagram glyphs to the textual design.

## Validation commands (run from /home/Gaurav/aoheyra-docs)

```bash
bash scripts/validate-docs.sh          # markdown links + workflow YAML syntax
python3 scripts/check_doc_12.py        # DOC-12 facts, required files, diagram notes
python3 scripts/check_doc_01.py        # DOC-01 facts (ownership, dep direction)
python3 scripts/check_doc_02.py        # DOC-02 facts
python3 scripts/check_doc_03.py        # DOC-03 facts
python3 scripts/check_doc_04.py        # DOC-04 facts
python3 scripts/check_doc_05.py        # DOC-05 facts
python3 scripts/check_doc_06.py        # DOC-06 facts
python3 scripts/check_doc_07.py        # DOC-07 facts
python3 scripts/check_doc_08.py        # DOC-08 facts
python3 scripts/check_doc_09.py        # DOC-09 facts
python3 scripts/check_doc_10.py        # DOC-10 facts
cargo doc --no-deps                    # crate compiles (no runtime code here)
```

## History

| Date | Change |
|---|---|
| 2026-11-24 | Scope slice added; LLD and diagram-notation rule documented. |