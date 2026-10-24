#!/usr/bin/env bash
# agent_session_start.sh — optional Claude Code SessionStart hook: print the agent board status at session start.
#
# Operator-installed only (hooks are an operator surface; no agent wires this). Install, in the operator's
# ~/.claude/settings.json (or the project's .claude/settings.local.json):
#   "hooks": { "SessionStart": [ { "hooks": [ { "type": "command",
#       "command": "bash \"$CLAUDE_PROJECT_DIR/scripts/agent_session_start.sh\"" } ] } ] }
# What it does: runs `agent_claim.py status --no-gh` (read-only: claim files, local git refs; no GitHub, no writes)
# and prints docs/ops/AGENT_START_HERE.md's five commands. Always exits 0, bounded by a 20 s timeout.
set -uo pipefail
ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
PY="python3"
[ -x "$ROOT/.venv/bin/python" ] && PY="$ROOT/.venv/bin/python"
echo "== Agent claim board (docs/ops/AGENT_START_HERE.md) =="
timeout 20 "$PY" "$ROOT/scripts/agent_claim.py" --no-gh status --repo "$ROOT" 2>&1 | head -80 || true
cat <<'TXT'
Next: export AGENT_CLAIM_VENDOR/AGENT_CLAIM_SESSION/AGENT_CLAIM_AGENT, then
  agent_claim.py next | take <task-id> | takeover <claim_id> --claim ; plan/done/note/blocker ; task done ; release --summary
TXT
exit 0
