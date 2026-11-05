#!/usr/bin/env bash
# precommit_pii_eol.sh — the local half of the integrity rails, run from .githooks/pre-commit.
#
# Two failures that used to surface only on hosted CI, minutes after the push:
#   * personal or identifying data on a staged ADDED line (scripts/check_no_pii.py --staged);
#   * line-ending churn in the staged diff (scripts/check_line_endings.py).
# Both are cheap to see before the commit exists, and both are expensive to discover later:
# on 2026-11-01 a CRLF->LF rewrite cost ~40 minutes of CI, and a red `secret-scan` reached main.
#
# Read-only: it inspects the index and never writes, restages or rewrites anything.
# Kept under 3 s on a typical commit; the caller measures it.
set -uo pipefail

ROOT="$(git rev-parse --show-toplevel 2>/dev/null)" || {
  echo "precommit: not inside a git work tree" >&2
  exit 1
}
cd "$ROOT" || exit 1

PY="${TRADEAI_PY:-}"
if [[ -z "$PY" ]]; then
  if [[ -x "$ROOT/.venv/bin/python" ]]; then PY="$ROOT/.venv/bin/python"; else PY=python3; fi
fi

status=0

if ! "$PY" "$ROOT/scripts/check_no_pii.py" --staged --repo "$ROOT"; then
  cat >&2 <<'EOF'
commit refused: personal or identifying data on a staged added line.
  fix: remove the value, or use a synthetic one (example.com for mail, /home/runner/... for paths).
       A reviewed historical finding may be silenced in config/pii_baseline.json -- never by path.
EOF
  status=1
fi

if ! "$PY" "$ROOT/scripts/check_line_endings.py"; then
  cat >&2 <<'EOF'
commit refused: line-ending churn (CRLF vs LF) in the staged diff.
  fix: git checkout -- <file>, then re-apply the edit so the file keeps its existing endings.
       .gitattributes decides the committed form; a whole-file rewrite is never the fix.
EOF
  status=1
fi

exit "$status"
