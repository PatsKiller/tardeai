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
# Constant value only — never assigned to a shell variable named LAB_ACK, so the
# child can receive `LAB_ACK=...` as a command-prefix env without a readonly clash.
readonly LAB_ACK_VALUE=DISPOSABLE_LAB_NO_PRODUCTION_DATA
readonly LAB_SOCK=/home/johnclaw/tradeai-lab/sock
readonly LAB_DB=trade_ai_agentic_lab
readonly EVIDENCE_DIR="${AGENTIC_EVIDENCE_DIR:-/home/johnclaw/tradeai-lab/evidence}"

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
LAB_ACK="$LAB_ACK_VALUE" REPO="$HOST_REPO" AGENTIC_SOURCE_REF="$RESOLVED" \
  bash "$STAGE/scripts/agent_runtime/lab_evolve_from_ref.sh" >/dev/null \
  || fail "LAB evolve did not reach PASS_DB_PROOF"

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

# 5) the driver must be present in host-proof mode — a missing driver is a hard failure
"$PY" -c 'import psycopg2' 2>/dev/null || { teardown; fail "psycopg2 is required for the real host proof (missing driver is not a skip)"; }

# 6) run the REAL psycopg2 adapter suite; capture and PRESERVE the actual pytest output
readonly STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
readonly PYTEST_LOG="$EVIDENCE_DIR/agentic-runtime-hostproof-pytest-$STAMP.txt"
readonly JUNIT="$STAGE/real-junit.xml"
mkdir -p "$EVIDENCE_DIR"
set +e
AGENTIC_REAL_LAB=1 AGENTIC_LAB_SOCK="$LAB_SOCK" AGENTIC_LAB_DB="$LAB_DB" PYTHONPATH="$STAGE" \
  "$PY" -m pytest -rA -v -p no:cacheprovider \
    --junitxml="$JUNIT" \
    "$STAGE/tests/test_agent_runtime_real_postgres.py" 2>&1 | tee "$PYTEST_LOG"
readonly PYTEST_RC=${PIPESTATUS[0]}
set -e
chmod 600 "$PYTEST_LOG" 2>/dev/null || true
echo "pytest_evidence|$PYTEST_LOG"
echo "pytest_exit|$PYTEST_RC"

# 7) gate each property marker on its OWN test having demonstrably PASSED.
#    Any skipped, xfailed, errored, failed, or uncollected required test fails the proof.
set +e
"$PY" - "$JUNIT" "$PYTEST_RC" <<'PYEOF'
import sys, xml.etree.ElementTree as ET
junit, rc = sys.argv[1], int(sys.argv[2])
# property marker -> the exact test that must pass to earn it
REQUIRED = {
    "real_postgres_roundtrip": "test_real_roundtrip_review_score_and_completion",
    "artifact_review_score_binding": "test_real_roundtrip_review_score_and_completion",
    "post_terminal_independent_score": "test_real_roundtrip_review_score_and_completion",
    "append_only_journal": "test_real_append_only_trigger_blocks_update",
    "idempotency_conflict_detection": "test_real_idempotency_conflict_and_rollback",
    "replay_manifest_and_tamper": "test_real_export_replay_and_tamper",
    "durable_tool_lifecycle": "test_real_tool_call_lifecycle_durably_reconstructed",
    "kb_persistence": "test_real_kb_persistence",
    "two_connection_concurrency": "test_real_two_connection_concurrency_no_fork",
}
try:
    root = ET.parse(junit).getroot()
except Exception as exc:
    print(f"BLOCKED_AGENT_RUNTIME_PROOF: cannot read junit evidence: {exc}", file=sys.stderr)
    sys.exit(4)
outcome = {}
for case in root.iter("testcase"):
    name = case.get("name", "")
    kids = {child.tag for child in case}
    if kids & {"failure", "error"}:
        outcome[name] = "failed"
    elif "skipped" in kids:
        outcome[name] = "skipped"   # covers skip AND xfail
    else:
        outcome[name] = "passed"
problems = []
if rc != 0:
    problems.append(f"pytest exit {rc}")
for test in set(REQUIRED.values()):
    state = outcome.get(test)
    if state is None:
        problems.append(f"{test}: UNCOLLECTED")
    elif state != "passed":
        problems.append(f"{test}: {state.upper()}")
# emit each property marker only when its test demonstrably passed
for marker, test in sorted(REQUIRED.items()):
    if outcome.get(test) == "passed":
        print(f"{marker}|PASS")
    else:
        print(f"{marker}|FAIL", file=sys.stderr)
if problems:
    print("BLOCKED_AGENT_RUNTIME_PROOF: " + "; ".join(problems), file=sys.stderr)
    sys.exit(5)
PYEOF
gate_rc=$?
set -e

if [[ "$gate_rc" -eq 0 ]]; then
  teardown
  echo "activation_authority|DENIED"
  echo "production_database_write|NONE"
  echo "final_status|PASS_AGENT_RUNTIME_PERSISTENCE_PROOF"
else
  teardown
  echo "final_status|FAIL_AGENT_RUNTIME_PERSISTENCE_PROOF" >&2
  exit 3
fi
