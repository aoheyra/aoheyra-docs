#!/usr/bin/env bash
# Validate Markdown link targets and workflow YAML syntax for aoheyra-docs.
# Run from any directory; the script resolves the repository root itself.
set -euo pipefail

cd "$(dirname "$0")/.."

python3 - <<'PY'
from pathlib import Path
import re
import sys

import yaml

bad = []

for path in sorted(Path('.').rglob('*.md')):
    if '.git' in path.parts:
        continue
    text = path.read_text(encoding='utf-8')
    for match in re.finditer(r'\[[^\]]*\]\(([^)]+)\)', text):
        target = match.group(1).split('#', 1)[0].strip()
        if not target or '://' in target or target.startswith('mailto:'):
            continue
        if not (path.parent / target).exists():
            bad.append(f'{path}: missing link target {target}')

for path in sorted(Path('.github/workflows').glob('*.y*ml')):
    try:
        yaml.safe_load(path.read_text(encoding='utf-8'))
    except yaml.YAMLError as exc:
        bad.append(f'{path}: invalid YAML: {exc}')

if bad:
    print('\n'.join(bad), file=sys.stderr)
    sys.exit(1)

print('markdown links and workflow syntax are valid')
PY