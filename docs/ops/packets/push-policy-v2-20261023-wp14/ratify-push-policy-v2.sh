#!/usr/bin/env bash
# Ratifying edit for push policy v2 (AI_WORK_POLICY.md §29.4). OPERATOR-ONLY.
#   bash ratify-push-policy-v2.sh <pr_number> <head_sha>           # DRY RUN: checks the approval, shows the edit
#   bash ratify-push-policy-v2.sh <pr_number> <head_sha> --apply   # edits the PR branch's worktree and commits
# It changes exactly three lines inside §29: the heading, the `Push-Policy-v2:` marker and `Status:`. Never pushes.
# Enforcement still waits for AGENTS.md >= 20.0.0 ACTIVE (the hook checks both).
set -euo pipefail
PR="${1:?pr number}"; SHA="${2:?head sha}"; MODE="dry-run"; [[ "${3:-}" == "--apply" ]] && MODE="apply"
PKG="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WT="${TRADEAI_PP2_WORKTREE:-$HOME/wt-push-policy-v2-wp14-apply-20261023}"
REPO_SLUG="${TRADEAI_REPO_SLUG:-PatsKiller/tardeai}"
[[ "$PR" =~ ^[0-9]+$ && "$SHA" =~ ^[0-9a-f]{40}$ ]] || { echo "REFUSED: numeric PR and full 40-character SHA required" >&2; exit 2; }
(cd "$PKG" && sha256sum -c --quiet SHA256SUMS) || { echo "REFUSED: package digest mismatch" >&2; exit 2; }
PHRASE="APPROVE_AI_WORK_POLICY_PUSH_V2 ${PR} ${SHA}"
export TMPDIR="${TMPDIR:-$HOME/.cache/rtc}"

echo "== ratify push policy v2 ($MODE) PR #$PR head $SHA =="
head="$(git -C "$WT" rev-parse HEAD)"
[[ "$head" == "$SHA" ]] || { echo "REFUSED: $WT is at $head, not $SHA" >&2; exit 2; }
# Read-only GitHub GET: the phrase must be a comment by the repository owner on that PR.
comments="$(gh api "repos/$REPO_SLUG/issues/$PR/comments" --paginate --slurp)"
found="$(printf '%s' "$comments" | python3 -c '
import json, sys
owner, phrase = sys.argv[1:]
data = json.load(sys.stdin)
if not isinstance(data, list):
    raise SystemExit("REFUSED: comments must be an array")
rows = [row for page in data for row in (page if isinstance(page, list) else [page])]
for row in rows:
    if not isinstance(row, dict):
        continue
    user = row.get("user") or {}
    lines = [line.strip() for line in str(row.get("body") or "").splitlines()]
    if user.get("login") == owner and phrase in lines:
        print(str(row.get("html_url") or ""))
        break
' "${REPO_SLUG%%/*}" "$PHRASE")"
[[ -n "$found" ]] || { echo "REFUSED: no comment by ${REPO_SLUG%%/*} on #$PR containing: $PHRASE" >&2; exit 3; }
echo "approval: $found"

f="$WT/AI_WORK_POLICY.md"
start="$(grep -n '^# 29\. PUSH CLASSES' "$f" | cut -d: -f1)"
[[ -n "$start" ]] || { echo "REFUSED: §29 not found" >&2; exit 4; }
new="$(mktemp "$TMPDIR/pp2-ratify.XXXXXX")"
python3 - "$f" "$new" "$start" "$PR" <<'PY'
import sys, datetime
src, dst, start, pr = sys.argv[1], sys.argv[2], int(sys.argv[3]), sys.argv[4]
lines = open(src, encoding="utf-8").read().split("\n")
head, body = lines[:start - 1], lines[start - 1:]
today = datetime.date.today().isoformat()
done = {"marker": 0, "status": 0, "title": 0}
for i, l in enumerate(body):
    if l == "# 29. PUSH CLASSES — PUSH POLICY v2 (PROPOSED)":
        body[i] = "# 29. PUSH CLASSES — PUSH POLICY v2 (ACTIVE)"; done["title"] += 1
    elif l == "Push-Policy-v2: PROPOSED":
        body[i] = "Push-Policy-v2: ACTIVE"; done["marker"] += 1
    elif l == "Status: PROPOSED" and not done["status"]:
        body[i] = f"Status: ACTIVE (ratified {today}, PR #{pr})"
        done["status"] += 1
assert done == {"marker": 1, "status": 1, "title": 1}, done
open(dst, "w", encoding="utf-8").write("\n".join(head + body))
PY
diff -u "$f" "$new" || true
if [[ "$MODE" != "apply" ]]; then
  echo "DRY RUN OK (edit shown above; $f untouched). Re-run with --apply."
  exit 0
fi
cp "$new" "$f"
bash "$PKG/verify-push-policy-v2.sh" "$WT" --stage ratified
git -C "$WT" commit -q -am "policy(push): ratify push policy v2 — AI_WORK_POLICY §29 ACTIVE (${PHRASE})"
echo "RATIFIED on $(git -C "$WT" rev-parse --short HEAD). Push it (TRADEAI_REMOTE_PUSH_AUTHORIZED=1 git push) and merge."
echo "Enforcement starts when the hook's checkout has this commit AND AGENTS.md >= 20.0.0 is ACTIVE there."
