#!/usr/bin/env bash
# Recompute the generated artifacts, then validate them. Stages NOTHING.
#
# 2026-09-25 redesign (operator: "plan and build the evidence-file change"):
#   * The four SOP evidence files no longer embed control_surface_digest, so there
#     is no per-PR digest to rewrite. The digest is computed at HEAD by
#     validate_sop_evidence_integrity.py and recorded in the runtime attestation.
#   * docs/INDEX.md no longer commits the tree fingerprint or the counts tables,
#     so it changes only for the docs a PR actually adds or edits.
#   * This script no longer runs `git add -A` (it used to, three times, which
#     staged whatever else was in the worktree and contradicted new-worktree.sh's
#     "never add-all" rule). The index is built from `git ls-files`, so a NEW doc
#     must be staged first -- by name. If any untracked doc is found under docs/,
#     the script lists the exact `git add` command and stops without writing.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."

PY="${TRADEAI_PY:-python3}"

untracked="$(git ls-files --others --exclude-standard -- docs)"
if [[ -n "$untracked" ]]; then
  echo "  untracked docs found -- the index is built from tracked files, so stage them first:" >&2
  echo "    git add -- $(echo "$untracked" | tr '\n' ' ')" >&2
  exit 2
fi

$PY scripts/report_docs_inventory.py --write-index >/dev/null

$PY -c "
import sys; sys.path.insert(0,'scripts')
from lib import sop_evidence_integrity as S
from pathlib import Path
errs = S.validate_in_repo_evidence(Path('.'))
print('  sop evidence:', errs or 'clean')
raise SystemExit(1 if errs else 0)"
$PY scripts/report_docs_inventory.py --check-index | grep -oE '^\[(PASS|FAIL)\]' | sed 's/^/  docs index: /'
echo "  changed generated files (stage them explicitly if you want them in the commit):"
git status --porcelain -- docs/INDEX.md docs/implementation/maturity-program/sop-1.2.0-20260902 | sed 's/^/    /'
