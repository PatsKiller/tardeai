#!/usr/bin/env bash
# agent_claim_precommit.sh — WARN-ONLY pre-commit check of staged files against the agent claim board.
#
# Reports staged files that overlap a live claim of ANOTHER session (claims of this branch or of
# AGENT_CLAIM_SESSION are this session's own) or an open draft PR on another branch. It never blocks: it
# always exits 0, until AGENTS.md 19.1.0 makes the check mandatory. Design: docs/ops/AGENT_CLAIM_BOARD.md.
#
# Not wired by this PR: .githooks/ is an operator-only surface (AGENTS.md §23.13 exclusion; the guard's
# governed_globs; config/ci_risk_tiers.json policy_and_guard). Operator install, one line near the end of
# .githooks/pre-commit, before its chain to scripts/githooks/pre-commit:
#     bash "$ROOT/scripts/agent_claim_precommit.sh" || true
#
# Env: AGENT_CLAIM_NO_GH=1 skips the draft-PR lookup (offline); AGENT_CLAIM_GH_TIMEOUT (default 8 s);
#      TRADEAI_AGENT_CLAIMS_DIR overrides the claims directory.
set -uo pipefail
ROOT="$(git rev-parse --show-toplevel 2>/dev/null)" || exit 0
mapfile -t staged < <(git diff --cached --name-only --diff-filter=ACMRD 2>/dev/null)
[ "${#staged[@]}" -eq 0 ] && exit 0
branch="$(git rev-parse --abbrev-ref HEAD 2>/dev/null || true)"
[ "$branch" = "HEAD" ] && branch=""
args=(check --warn-only --quiet --gh-timeout "${AGENT_CLAIM_GH_TIMEOUT:-8}" --exclude-branch "$branch")
[ "${AGENT_CLAIM_NO_GH:-0}" = "1" ] && args+=(--no-gh)
PY="python3"
[ -x "$ROOT/.venv/bin/python" ] && PY="$ROOT/.venv/bin/python"
"$PY" "$ROOT/scripts/agent_claim.py" "${args[@]}" --paths "${staged[@]}" || \
  echo "agent-claim: check could not run (warn-only, commit continues)" >&2
exit 0
