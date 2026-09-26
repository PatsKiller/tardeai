#!/usr/bin/env bash
# fast_check.sh -- the inner-loop check. Target: under 60 s. CHANGED files only.
#
# 2026-09-25 (operator: "the current approach is slowing down the entire
# lifecycle; need faster feedback with appropriate governance"). Run it while
# iterating; run scripts/ai_local_acceptance.sh (fast profile, every gate) before
# asking for a push. It is read-only: no generated-file writes, no git add, no
# npm ci, no manifest candidate.
#
#   scripts/fast_check.sh                 # diff vs origin/main + uncommitted + untracked
#   scripts/fast_check.sh --base <ref>
#   FAST_CHECK_BUDGET=240 scripts/fast_check.sh  # impacted-test budget in hint-seconds (default 120)
#
# Steps
#   1. ruff check on changed .py files -- fails only if a file has MORE violations
#      than at the base (inherited debt in a file you touched is not your failure)
#   2. check_no_secrets --tree            (~2 s; tracked files incl. staged)
#   3. check_test_coverage --fail-on-new  (a new test file must be registered)
#   4. check_test_host_paths --fail-on-new
#   5. docs index drift (read-only --check-index)
#   6. impacted tests: run_cio_hardening_ci.py --profile pr on the diff, with a
#      tighter budget and no tail. Uses the cached import map (in the git dir); a stale
#      map is rebuilt (~10 s). Over-budget tests are listed as deferred.
set -uo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.." || exit 2

BASE="origin/main"
while [[ $# -gt 0 ]]; do
  case "$1" in
    --base) BASE="$2"; shift 2 ;;
    *) echo "unknown arg: $1" >&2; exit 2 ;;
  esac
done

PY="${TRADEAI_PY:-}"
if [[ -z "$PY" ]]; then
  if [[ -x .venv/bin/python ]]; then PY=.venv/bin/python; else PY=python3; fi
fi
RUFF="$(command -v ruff || true)"
[[ -x .venv/bin/ruff ]] && RUFF=.venv/bin/ruff
BUDGET="${FAST_CHECK_BUDGET:-120}"

t0=$SECONDS
failed=()
step() { printf '\n== %s (%ss)\n' "$1" "$((SECONDS - t0))"; }

mapfile -t CHANGED < <("$PY" - "$BASE" <<'PY'
import sys
from pathlib import Path
sys.path.insert(0, ".")
from scripts.lib import test_impact
paths = test_impact.changed_paths(sys.argv[1], root=Path("."), include_worktree=True)
if paths is None:
    print(f"BASE-UNUSABLE {sys.argv[1]}", file=sys.stderr)
    raise SystemExit(3)
print("\n".join(p for p in paths if p))
PY
)
echo "fast_check: base=$BASE changed=${#CHANGED[@]}"

step "ruff (changed .py, no new violations vs base)"
if [[ -z "$RUFF" ]]; then
  echo "  ruff not found"; failed+=("ruff_missing")
else
  merge_base="$(git merge-base "$BASE" HEAD)"
  for f in "${CHANGED[@]}"; do
    [[ "$f" == *.py && -f "$f" ]] || continue
    now=$("$RUFF" check --quiet --output-format concise "$f" 2>/dev/null | grep -c ":[0-9]*:[0-9]*: " || true)
    [[ "$now" -eq 0 ]] && continue
    before=0
    if git cat-file -e "$merge_base:$f" 2>/dev/null; then
      before=$(git show "$merge_base:$f" | "$RUFF" check --quiet --output-format concise --stdin-filename "$f" - 2>/dev/null | grep -c ":[0-9]*:[0-9]*: " || true)
    fi
    if [[ "$now" -gt "$before" ]]; then
      echo "  $f: $now violations (base $before)"
      "$RUFF" check --output-format concise "$f" | head -20
      failed+=("ruff:$f")
    fi
  done
fi

step "secrets (--tree)"
"$PY" scripts/check_no_secrets.py --tree | tail -2 || failed+=("check_no_secrets")

step "test coverage (new test files registered)"
"$PY" scripts/check_test_coverage.py --fail-on-new >/dev/null || { "$PY" scripts/check_test_coverage.py --fail-on-new | tail -15; failed+=("check_test_coverage"); }

step "test host paths"
"$PY" scripts/check_test_host_paths.py --fail-on-new || failed+=("check_test_host_paths")

step "docs index drift (read-only)"
"$PY" scripts/report_docs_inventory.py --check-index | grep -E '^\[(PASS|FAIL)\]' || failed+=("docs_index_drift")

step "impacted tests (pr selection, budget ${BUDGET}s, no tail)"
out="$("$PY" scripts/run_cio_hardening_ci.py --profile pr --base "$BASE" --include-worktree --budget "$BUDGET" --no-tail 2>&1)"
rc=$?
grep -E '^\[(select|plan|FAIL|timing)\]|^CIO HARDENING' <<<"$out"
if [[ $rc -ne 0 ]]; then
  grep -E '^(E |FAILED |[^ ]+\.py:[0-9]+: )' <<<"$out" | head -40
  failed+=("impacted_tests")
fi

printf '\nfast_check: %ss total\n' "$((SECONDS - t0))"
if [[ ${#failed[@]} -gt 0 ]]; then
  echo "fast_check: FAILED: ${failed[*]}"
  exit 1
fi
echo "fast_check: PASS (not a substitute for ai_local_acceptance.sh before push)"
