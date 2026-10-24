#!/usr/bin/env bash
# Push policy v2 — OPERATOR-APPLIED package (AI_WORK_POLICY.md §29, .githooks/pre-push,
# scripts/lib/tradeai_push_budget.py, its test and CI gate).
#
#   bash apply-push-policy-v2.sh            # DRY RUN (default): verifies digests and base, checks the patch
#                                           # applies to origin/main in a scratch index. Writes nothing in the repo.
#   bash apply-push-policy-v2.sh --apply    # new worktree + branch from origin/main, apply, verify, commit.
#
# Never pushes, never opens a PR, never merges: those are the operator's acts (commands printed at the end).
set -euo pipefail

PKG="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="${TRADEAI_REPO:-$HOME/trade-ai-v12-rebuild/trade-ai-v12-rebuild}"
BRANCH="${TRADEAI_PP2_BRANCH:-ops/push-policy-v2-wp14-20261023}"
WT="${TRADEAI_PP2_WORKTREE:-$HOME/wt-push-policy-v2-wp14-apply-20261023}"
MODE="dry-run"
[[ "${1:-}" == "--apply" ]] && MODE="apply"
export TMPDIR="${TMPDIR:-$HOME/.cache/rtc}"
mkdir -p "$TMPDIR"

echo "== push policy v2 package ($MODE) =="
echo "package: $PKG"
echo "repo:    $REPO"

(cd "$PKG" && sha256sum -c --quiet SHA256SUMS) || { echo "REFUSED: package digests do not match SHA256SUMS" >&2; exit 2; }
echo "digests: OK ($(wc -l < "$PKG/SHA256SUMS") files)"

BASE="$(cat "$PKG/BASE_SHA")"
git -C "$REPO" fetch -q origin main
MAIN="$(git -C "$REPO" rev-parse origin/main)"
echo "base:    $BASE"
echo "main:    $MAIN"
OWNED=(AI_WORK_POLICY.md .githooks/pre-push scripts/lib/tradeai_push_budget.py)
if ! git -C "$REPO" diff --quiet "$BASE" "$MAIN" -- "${OWNED[@]}"; then
  echo "REFUSED: an operator-owned file changed on main since the package base; rebuild the package:" >&2
  git -C "$REPO" diff --stat "$BASE" "$MAIN" -- "${OWNED[@]}" >&2
  exit 3
fi
echo "operator-owned files unchanged since base: OK"

idx="$(mktemp "$TMPDIR/pp2-index.XXXXXX")"
GIT_INDEX_FILE="$idx" git -C "$REPO" read-tree "$MAIN"
GIT_INDEX_FILE="$idx" git -C "$REPO" apply --cached --check "$PKG/push-policy-v2.patch"
echo "patch applies to origin/main: OK"
GIT_INDEX_FILE="$idx" git -C "$REPO" apply --cached --stat "$PKG/push-policy-v2.patch"
echo "(scratch index left at $idx; nothing in $REPO was written)"

hp="$(git -C "$REPO" config --get core.hooksPath || true)"
echo "live core.hooksPath: ${hp:-unset}"
marker="$(grep -m1 -E '^Push-Policy-v2:' "${hp%/.githooks}/AI_WORK_POLICY.md" 2>/dev/null || true)"
echo "live policy marker:  ${marker:-absent (legacy: v1 exactly)}"

if [[ "$MODE" != "apply" ]]; then
  echo
  echo "DRY RUN OK. To apply: bash $PKG/apply-push-policy-v2.sh --apply"
  exit 0
fi

if [[ -e "$WT" ]]; then
  echo "REFUSED: $WT exists; set TRADEAI_PP2_WORKTREE to a new path" >&2
  exit 4
fi
if git -C "$REPO" show-ref --verify --quiet "refs/heads/$BRANCH"; then
  echo "REFUSED: branch $BRANCH exists; set TRADEAI_PP2_BRANCH" >&2
  exit 4
fi
git -C "$REPO" worktree add -q -b "$BRANCH" "$WT" "$MAIN"
git -C "$WT" apply --index "$PKG/push-policy-v2.patch"
bash "$PKG/verify-push-policy-v2.sh" "$WT" --stage proposed
git -C "$WT" commit -q -F "$PKG/COMMIT_MSG.txt"
echo
echo "APPLIED on $BRANCH at $(git -C "$WT" rev-parse --short HEAD) in $WT (not pushed)."
cat <<EOF

Operator next steps (your acts):
  1. Push and open the PR (the v1 hook still governs this push):
       cd $WT
       TRADEAI_REMOTE_PUSH_AUTHORIZED=1 git push -u origin $BRANCH
       gh pr create --base main --head $BRANCH --title "WP-14 policy(push): push policy v2 — AI_WORK_POLICY §29 (PROPOSED, shadow)" --body-file $PKG/PR_BODY.md
  2. Merge it when green (per-PR word: AI_WORK_POLICY.md and .githooks are excluded from standing approvals).
     Merged, it is inert: the hook runs v2 in SHADOW and v1 still decides.
     The train class remains TRAIN_AUTHORITY_UNPROVEN: verified reservation wiring is a separate review.
  3. Update the checkout core.hooksPath points at ($hp) to the merged main, as after any release.
     The hook reads the policy from there. Then read the shadow lines in the push ledger:
       tail -n 20 "\$(git -C $REPO rev-parse --git-common-dir)/tradeai-push-ledger.v2.jsonl"
  4. Once the open proposal PR exists, print exact PR/full-head-bound approval and ratification commands:
       bash $PKG/ratify-instructions.sh
     It refuses until the remote PR and local worktree have the same exact head. No placeholder is an approval.
     Enforcement also waits for AGENTS.md 20.0.0 ACTIVE.
EOF
