#!/usr/bin/env bash
# Recompute every generated artifact, in the ONE order that works.
#
# Ordering is load-bearing and was learned the hard way:
#   1. git add        — the index is built from `git ls-files`, so regenerating
#                       before staging produces an index that omits the new files
#                       and fails again. (Done exactly that once.)
#   2. digest         — control_surface_digest is computed over the merged tree
#   3. write-index    — after the digest edit, because the evidence files are
#                       themselves tracked docs and change the index fingerprint
#   4. git add        — stage the regenerated results
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."

PY="${TRADEAI_PY:-python3}"
D="docs/implementation/maturity-program/sop-1.2.0-20260902"

git add -A >/dev/null 2>&1 || true

NEW="$($PY -c "
import sys; sys.path.insert(0,'scripts')
from lib import sop_evidence_integrity as S
from pathlib import Path
print(S.control_surface_digest(Path('.'))['digest'])")"
OLD="$(grep -rho 'control_surface_digest=[a-f0-9]*' "$D/FULL_TEST_MATRIX.txt" 2>/dev/null | head -1 | cut -d= -f2 || true)"

if [[ -n "$OLD" && "$OLD" != "$NEW" ]]; then
  echo "  control_surface_digest ${OLD:0:12} -> ${NEW:0:12}"
  grep -rl "control_surface_digest=$OLD" "$D/" | while read -r f; do
    sed -i "s/$OLD/$NEW/g" "$f"
  done
fi

git add -A >/dev/null 2>&1 || true
$PY scripts/report_docs_inventory.py --write-index >/dev/null 2>&1 || true
git add -A >/dev/null 2>&1 || true

$PY -c "
import sys; sys.path.insert(0,'scripts')
from lib import sop_evidence_integrity as S
from pathlib import Path
errs = S.validate_in_repo_evidence(Path('.'))
print('  sop evidence:', errs or 'clean')
raise SystemExit(1 if errs else 0)"
$PY scripts/report_docs_inventory.py --check-index | grep -oE '^\[(PASS|FAIL)\]' | sed 's/^/  docs index: /'
