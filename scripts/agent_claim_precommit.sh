#!/usr/bin/env bash
# agent_claim_precommit.sh — pre-commit gate of staged files against the agent claim board. POLICY-GATED.
#
#   AGENTS.md below 20.0.0, or 20.0.0+ not ACTIVE  -> WARN and exit 0 (reports, never blocks).
#   AGENTS.md 20.0.0 or later AND ACTIVE            -> exit 1 (BLOCK) when a staged file is
#       * held by another session's live claim (prints holder, branch and since), or
#       * not covered by any live claim of this session (AGENT_CLAIM_SESSION) or of this branch.
#     Bypass only with TRADEAI_CLAIM_OVERRIDE=<reason>; every bypass is appended to claims_history.jsonl
#     (AgentClaimOverride@v1). An override that cannot be logged is refused.
#
# The policy state is read from the repo's AGENTS.md on every run (control block Policy-Version >= 20.0.0,
# Status ACTIVE, and that version's history row ACTIVE: agent_claim_board.claim_policy_state). The amendment
# that makes claiming mandatory is AGENTS.md 20.0.0 (built as "19.1.0", renumbered MAJOR).
# A claim whose PR has merged no longer holds its files (lifecycle stage merged/released).
# Design: docs/ops/AGENT_CLAIM_BOARD.md.
#
# Not wired by this PR: .githooks/ is an operator-only surface (AGENTS.md §23.13 exclusion; the guard's
# governed_globs; config/ci_risk_tiers.json policy_and_guard). Operator install, one line in .githooks/pre-commit,
# before its chain to scripts/githooks/pre-commit (no "|| true": the exit code is the gate):
#     bash "$ROOT/scripts/agent_claim_precommit.sh" || exit 1
#
# Exit: 0 commit continues · 1 blocked (agent_claim.py precommit returns 10). Any other rc means the gate itself
# could not run (import error, crash, usage): it then blocks only while the policy is enforcing, and otherwise warns.
# Env: AGENT_CLAIM_NO_GH=1 never calls GitHub (a holder's merge is then seen only from the lifecycle cache);
#      TRADEAI_AGENT_CLAIMS_DIR overrides the claims directory; TRADEAI_CLAIM_OVERRIDE=<reason> bypasses (logged).
set -uo pipefail
ROOT="$(git rev-parse --show-toplevel 2>/dev/null)" || exit 0
mapfile -t staged < <(git diff --cached --name-only --diff-filter=ACMRD 2>/dev/null)
[ "${#staged[@]}" -eq 0 ] && exit 0
branch="$(git symbolic-ref --short -q HEAD 2>/dev/null || true)"  # works on an unborn branch too
[ "$branch" = "HEAD" ] && branch=""
PY="python3"
[ -x "$ROOT/.venv/bin/python" ] && PY="$ROOT/.venv/bin/python"
"$PY" "$ROOT/scripts/agent_claim.py" precommit --exclude-branch "$branch" --agents-md "$ROOT/AGENTS.md" \
  --paths "${staged[@]}"
rc=$?
[ "$rc" -eq 0 ] && exit 0
[ "$rc" -eq 10 ] && exit 1  # the gate blocked (agent_claim.py PRECOMMIT_BLOCK)
# Stdlib-only policy read (same rule as claim_policy_state), so a broken gate library still fails closed.
if "$PY" -I - "$ROOT/AGENTS.md" 2>/dev/null <<'PY'; then
import re, sys
t = open(sys.argv[1], encoding="utf-8").read()
b = re.search(r"```\n(Policy-Version:.*?)```", t, re.S)
f = dict((k.strip(), v.strip()) for k, _, v in (l.partition(":") for l in (b.group(1) if b else "").splitlines()) if _)
v = f.get("Policy-Version", "")
m = re.match(r"^(\d+)\.(\d+)\.(\d+)$", v)
row = re.search(r"^\|\s*" + re.escape(v) + r"\s*\|[^|]*\|\s*([^|]*)\|", t, re.M) if v else None
ok = bool(m and tuple(map(int, m.groups())) >= (20, 0, 0) and f.get("Status", "").upper().startswith("ACTIVE")
          and row and row.group(1).strip().upper().startswith("ACTIVE"))
sys.exit(0 if ok else 1)
PY
  echo "agent-claim: gate could not run (rc=$rc) and AGENTS.md >= 20.0.0 is ACTIVE — commit blocked" >&2
  exit 1
fi
echo "agent-claim: gate could not run (rc=$rc); warn-only below AGENTS.md 20.0.0 ACTIVE, commit continues" >&2
exit 0
