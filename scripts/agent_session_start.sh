#!/usr/bin/env bash
# agent_session_start.sh — optional Claude Code SessionStart hook: print the agent board status at session start.
#
# Operator-installed only (hooks are an operator surface; no agent wires this). Install, in the operator's
# ~/.claude/settings.json (or the project's .claude/settings.local.json):
#   "hooks": { "SessionStart": [ { "hooks": [ { "type": "command",
#       "command": "bash \"$CLAUDE_PROJECT_DIR/scripts/agent_session_start.sh\"" } ] } ] }
# What it does: runs `agent_claim.py status --no-gh` (read-only: claim files, local git refs; no GitHub, no writes)
# and prints docs/ops/AGENT_START_HERE.md's five commands. Always exits 0, bounded by a 20 s timeout.
# First (operator 2026-10-28) it prints the AGENTS.md Policy-Version this worktree holds against origin/main's
# (scripts/lib/policy_freshness.py, one short fetch): STALE is printed loudly with the fix. Advisory only; the claim,
# pre-commit, pre-push and CI gates are what refuse.
set -uo pipefail
ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
PY="python3"
[ -x "$ROOT/.venv/bin/python" ] && PY="$ROOT/.venv/bin/python"
echo "== AGENTS.md policy freshness (scripts/lib/policy_freshness.py) =="
prc=0
fresh="$(timeout 15 "$PY" "$ROOT/scripts/lib/policy_freshness.py" --repo "$ROOT" --gate session 2>&1)" || prc=$?
if [ "$prc" -eq 1 ]; then
  cat <<TXT
!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
$fresh
This session is reading an OLD AGENTS.md. Stop: work from fresh origin/main (scripts/new-worktree.sh), re-read §0.
Claims, commits and pushes from this copy are refused.
!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
TXT
elif [ "$prc" -eq 0 ]; then
  echo "$fresh"
else
  echo "WARNING (not a pass): ${fresh:-policy freshness check could not run (rc=$prc)}"
fi
echo "== Agent claim board (docs/ops/AGENT_START_HERE.md) =="
timeout 20 "$PY" "$ROOT/scripts/agent_claim.py" --no-gh status --repo "$ROOT" 2>&1 | head -80 || true
cat <<'TXT'
Next: export AGENT_CLAIM_VENDOR/AGENT_CLAIM_SESSION/AGENT_CLAIM_AGENT, then
  agent_claim.py next | take <task-id> | takeover <claim_id> --claim ; plan/done/note/blocker ; task done ; release --summary
TXT
exit 0
