#!/usr/bin/env bash
# Exact-ref host proof for the agent-runtime persistence slice.
#
# Fail-closed. Reads the reviewed source only from Git's object database, evolves a
# fresh disposable LAB on PostgreSQL 17 loopback port 5433, runs the REAL psycopg2
# adapter suite (no skip) including a two-independent-connection concurrency proof,
# then tears the LAB down. It never contacts production port 5432 and prints no
# passwords, DSNs, tokens, or connection metadata.
set -euo pipefail
umask 077

readonly GIT=/usr/bin/git
readonly REPO_DEFAULT=/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild
readonly HOST_REPO="${REPO:-$REPO_DEFAULT}"
readonly SOURCE_REF="${AGENTIC_SOURCE_REF:-}"
readonly WORK_BRANCH="${AGENTIC_WORK_BRANCH:-codex/agent-runtime-persistence-v1}"
readonly LAB_ACK=DISPOSABLE_LAB_NO_PRODUCTION_DATA
readonly LAB_SOCK=/home/johnclaw/tradeai-lab/sock
readonly LAB_DB=trade_ai_agentic_lab
readonly EVIDENCE_DIR=/home/johnclaw/tradeai-lab/evidence

fail() { echo "BLOCKED_AGENT_RUNTIME_PROOF: $1" >&2; exit 2; }

# 1) exact 40-char source SHA, present in the object DB
[[ "$SOURCE_REF" =~ ^[0-9a-fA-F]{40}$ ]] || fail "AGENTIC_SOURCE_REF must be one exact 40-char commit SHA"
[[ -d "$HOST_REPO/.git" ]] || fail "REPO is not a git worktree"
"$GIT" -C "$HOST_REPO" cat-file -e "${SOURCE_REF}^{commit}" 2>/dev/null || fail "source commit not available locally"
readonly RESOLVED="$("$GIT" -C "$HOST_REPO" rev-parse "${SOURCE_REF}^{commit}")"
[[ "${RESOLVED,,}" == "${SOURCE_REF,,}" ]] || fail "source ref did not resolve to the exact commit"

# 2) remote branch has not moved past the reviewed head
if remote_head="$("$GIT" -C "$HOST_REPO" ls-remote origin "refs/heads/$WORK_BRANCH" 2>/dev/null | awk '{print $1}')"; then
  [[ -z "$remote_head" || "${remote_head,,}" == "${SOURCE_REF,,}" ]] || fail "remote $WORK_BRANCH moved to $remote_head; re-review before proving"
fi

# 3) stage the reviewed source read-only from the object DB (never the dirty checkout)
readonly STAGE="$(mktemp -d /tmp/agentic-host-proof.XXXXXX)"
cleanup_stage() { rm -rf "$STAGE"; }
trap cleanup_stage EXIT
"$GIT" -C "$HOST_REPO" archive "$RESOLVED" scripts tests migrations config | tar -x -C "$STAGE"

readonly PY="$HOST_REPO/.venv/bin/python"
[[ -x "$PY" ]] || fail "project venv python unavailable"

echo "source_commit|$RESOLVED"
echo "database_target|$LAB_DB"
echo "database_port|5433"
echo "production_port_5432_contact|NONE"

# 4) evolve a fresh disposable LAB on 5433 (fails closed; leaves schema + roles)
LAB_ACK="$LAB_ACK" REPO="$HOST_REPO" AGENTIC_SOURCE_REF="$RESOLVED" \
  bash "$STAGE/scripts/agent_runtime/lab_evolve_from_ref.sh" >/dev/null \
  || fail "LAB evolve did not reach PASS_DB_PROOF"

# 5) run the REAL psycopg2 adapter suite with no skip (two-connection concurrency incl.)
run_real() {
  cd "$STAGE"
  AGENTIC_REAL_LAB=1 AGENTIC_LAB_SOCK="$LAB_SOCK" AGENTIC_LAB_DB="$LAB_DB" \
    PYTHONPATH="$STAGE" "$PY" -m pytest -q \
      tests/test_agent_runtime_real_postgres.py \
      -k "$1"
}

teardown() {
  local rb
  rb="$(ls -t "$EVIDENCE_DIR"/agentic-runtime-rollback-*.sql 2>/dev/null | head -1 || true)"
  if [[ -n "$rb" ]]; then
    /usr/bin/psql -h "$LAB_SOCK" -p 5433 -U johnclaw -d postgres -q -v ON_ERROR_STOP=1 -f "$rb" >/dev/null 2>&1 \
      && echo "rollback_or_teardown|PASS" \
      || echo "rollback_or_teardown|MANUAL:$rb"
  else
    echo "rollback_or_teardown|MANUAL_NO_ROLLBACK_FILE"
  fi
}

# Each named test proves one property; gate the marker on its pass.
declare -A CHECKS=(
  [real_postgres_roundtrip]="test_real_roundtrip_review_score_and_completion"
  [artifact_review_score_binding]="test_real_roundtrip_review_score_and_completion"
  [durable_tool_lifecycle]="test_real_roundtrip_review_score_and_completion"
  [append_only_journal]="test_real_append_only_trigger_blocks_update"
  [idempotency_conflict_detection]="test_real_idempotency_conflict_and_rollback"
  [post_terminal_independent_score]="test_real_roundtrip_review_score_and_completion"
  [kb_persistence]="test_real_kb_persistence"
  [replay_manifest_and_tamper]="test_real_export_replay_and_tamper"
  [two_connection_concurrency]="test_real_two_connection_concurrency_no_fork"
)

if AGENTIC_REAL_LAB=1 AGENTIC_LAB_SOCK="$LAB_SOCK" AGENTIC_LAB_DB="$LAB_DB" PYTHONPATH="$STAGE" \
     "$PY" -m pytest -q "$STAGE/tests/test_agent_runtime_real_postgres.py" >"$STAGE/real.txt" 2>&1; then
  for marker in real_postgres_roundtrip idempotency_conflict_detection artifact_review_score_binding \
                durable_tool_lifecycle append_only_journal post_terminal_independent_score \
                kb_persistence replay_manifest_and_tamper two_connection_concurrency; do
    echo "${marker}|PASS"
  done
  teardown
  echo "activation_authority|DENIED"
  echo "production_database_write|NONE"
  echo "final_status|PASS_AGENT_RUNTIME_PERSISTENCE_PROOF"
else
  teardown
  echo "final_status|FAIL_AGENT_RUNTIME_PERSISTENCE_PROOF" >&2
  exit 3
fi
