#!/usr/bin/env bash
# Read-only: print actual PR/head-bound operator commands after the proposal PR exists.
set -euo pipefail
PKG="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
(cd "$PKG" && sha256sum -c --quiet SHA256SUMS)
BRANCH="${TRADEAI_PP2_BRANCH:-ops/push-policy-v2-wp14-20261023}"
WT="${TRADEAI_PP2_WORKTREE:-$HOME/wt-push-policy-v2-wp14-apply-20261023}"
SLUG="${TRADEAI_REPO_SLUG:-PatsKiller/tardeai}"
HEAD_SHA="$(git -C "$WT" rev-parse HEAD)"
META="$(gh pr view "$BRANCH" --repo "$SLUG" --json number,headRefOid,state,url)"
python3 - "$PKG" "$HEAD_SHA" "$META" <<'PY'
import json, shlex, sys
pkg, head, raw = sys.argv[1:]
pr = json.loads(raw)
if pr['headRefOid'] != head or pr['state'] != 'OPEN':
    raise SystemExit('REFUSED: open remote PR must have the exact local proposal head')
n = int(pr['number'])
phrase = f'APPROVE_AI_WORK_POLICY_PUSH_V2 {n} {head}'
print('Operator approval is required; this helper only prints commands:')
print(f'gh pr comment {n} --body {shlex.quote(phrase)}')
for apply in ('', ' --apply'):
    print(f'bash {shlex.quote(pkg + "/ratify-push-policy-v2.sh")} {n} {head}{apply}')
print('Ratification creates a new local commit. Publish it as operator, then re-check its exact-head CI.')
print('The coordinator owns merge and release. No command above merges or pushes.')
PY
