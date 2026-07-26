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
readonly LAB_SOCK="${AGENTIC_LAB_SOCK:-/home/johnclaw/tradeai-lab/sock}"
readonly LAB_DB=trade_ai_agentic_lab
readonly EVIDENCE_DIR="${AGENTIC_EVIDENCE_DIR:-/home/johnclaw/tradeai-lab/evidence}"
readonly LAB_SECRETS_DIR="${AGENTIC_SECRETS_DIR:-/home/johnclaw/tradeai-lab/secrets/agentic-runtime}"

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
readonly CLEANUP_MANIFEST="$(mktemp /tmp/agentic-cleanup-manifest.XXXXXX)"
chmod 600 "$CLEANUP_MANIFEST"

# Exact-run cleanup. Runs the EXACT fresh rollback file and removes ONLY the exact fresh
# writer/reader pgpass files (never an unrelated file, never a glob). Idempotent and armed
# via the EXIT trap so it fires on every path: evolve failure after partial provisioning,
# manifest-validation rejection, missing driver, pytest/gate failure, success, and
# shell exit/interrupt. Sanitized pytest/DB evidence is preserved.
CLEANUP_DONE=0
CLEANUP_ROLLBACK=""
CLEANUP_WRITER=""
CLEANUP_READER=""
run_cleanup() {
  [[ "$CLEANUP_DONE" == 1 ]] && return 0
  CLEANUP_DONE=1
  if [[ -n "$CLEANUP_ROLLBACK" && -f "$CLEANUP_ROLLBACK" ]]; then
    /usr/bin/psql -h "$LAB_SOCK" -p 5433 -U johnclaw -d postgres -q -v ON_ERROR_STOP=1 -f "$CLEANUP_ROLLBACK" >/dev/null 2>&1 \
      && echo "rollback_or_teardown|PASS" \
      || echo "rollback_or_teardown|MANUAL"
  else
    echo "rollback_or_teardown|MANUAL_NO_ROLLBACK_FILE"
  fi
  [[ -n "$CLEANUP_WRITER" && -f "$CLEANUP_WRITER" ]] && rm -f -- "$CLEANUP_WRITER"
  [[ -n "$CLEANUP_READER" && -f "$CLEANUP_READER" ]] && rm -f -- "$CLEANUP_READER"
  return 0  # never let a false final test abort a set -e caller before its own fail/exit
}
cleanup_all() { run_cleanup; rm -rf "$STAGE"; rm -f "$CLEANUP_MANIFEST"; }
trap cleanup_all EXIT
trap 'exit 130' INT TERM

"$GIT" -C "$HOST_REPO" archive "$RESOLVED" scripts tests migrations config | tar -x -C "$STAGE"

readonly PY="$HOST_REPO/.venv/bin/python"
[[ -x "$PY" ]] || fail "project venv python unavailable"

echo "source_commit|$RESOLVED"
echo "database_target|$LAB_DB"
echo "database_port|5433"
echo "production_port_5432_contact|NONE"

# 4) evolve a fresh disposable LAB on 5433. The evolve writes a private cleanup manifest
#    containing ONLY the exact rollback / writer / reader pathnames (never a password).
evolve_rc=0
AGENTIC_CLEANUP_MANIFEST="$CLEANUP_MANIFEST" LAB_ACK="$LAB_ACK_VALUE" REPO="$HOST_REPO" AGENTIC_SOURCE_REF="$RESOLVED" \
  bash "$STAGE/scripts/agent_runtime/lab_evolve_from_ref.sh" >/dev/null || evolve_rc=$?

# 4a) Register + validate the exact fresh cleanup paths BEFORE anything else, so cleanup
#     is armed even when evolve failed after partial provisioning. The validator prints
#     ROLLBACK=/WRITER=/READER= for each path that is a canonical, non-symlink, regular
#     file directly inside its expected directory with the exact fresh-run name (shared
#     stamp derived from the rollback file). It exits 0 only when all three are valid AND
#     the writer is mode 0600. Symlink/out-of-directory paths are never emitted, so they
#     are never used or removed. Paths are captured privately and never echoed.
set +e
creds="$("$PY" - "$CLEANUP_MANIFEST" "$EVIDENCE_DIR" "$LAB_SECRETS_DIR" <<'PYEOF'
import os, stat, sys
manifest, ev_dir, sec_dir = sys.argv[1], sys.argv[2], sys.argv[3]

def canon_regular(path):
    if not path or "\n" in path or os.path.islink(path):
        return None
    try:
        real = os.path.realpath(path)
    except Exception:
        return None
    if os.path.islink(real) or not os.path.isfile(real):
        return None
    return real

try:
    fields = open(manifest, encoding="utf-8").read().splitlines()
except Exception:
    sys.exit(3)
if len(fields) != 3:
    sys.exit(3)
rb, wr, rd = fields
ev = os.path.realpath(ev_dir)
sec = os.path.realpath(sec_dir)
ok = True

rbc = canon_regular(rb)
stamp = None
if rbc and os.path.dirname(rbc) == ev:
    base = os.path.basename(rbc)
    if base.startswith("agentic-runtime-rollback-") and base.endswith(".sql"):
        stamp = base[len("agentic-runtime-rollback-"):-len(".sql")]
        print("ROLLBACK=" + rbc)
if not stamp:
    ok = False

wrc = canon_regular(wr)
if stamp and wrc and os.path.dirname(wrc) == sec and os.path.basename(wrc) == f"agentic-runtime-lab-rw-{stamp}.pgpass":
    print("WRITER=" + wrc)
    if oct(stat.S_IMODE(os.stat(wrc).st_mode)) != "0o600":
        ok = False
else:
    ok = False

rdc = canon_regular(rd)
if stamp and rdc and os.path.dirname(rdc) == sec and os.path.basename(rdc) == f"trade-ai-shadow-ro-{stamp}.pgpass":
    print("READER=" + rdc)
else:
    ok = False

sys.exit(0 if ok else 3)
PYEOF
)"
validate_rc=$?
set -e
while IFS='=' read -r _k _v; do
  case "$_k" in
    ROLLBACK) CLEANUP_ROLLBACK="$_v" ;;
    WRITER) CLEANUP_WRITER="$_v" ;;
    READER) CLEANUP_READER="$_v" ;;
  esac
done <<< "$creds"
unset creds

[[ "$evolve_rc" -eq 0 ]] || { run_cleanup; fail "LAB evolve did not reach PASS_DB_PROOF"; }
[[ "$validate_rc" -eq 0 ]] || { run_cleanup; fail "LAB credential manifest failed validation"; }

# 5) one reusable clean-libpq launcher for BOTH the auth preflight and pytest. It strips
#    every inherited libpq (PG*) variable — PGPASSWORD/PGSERVICE/PGSERVICEFILE/PGHOST/
#    PGPORT/PGDATABASE/PGUSER/PGOPTIONS/PGSSL*/... — so an inherited PGPASSWORD can never
#    override the reviewed credential, then sets ONLY the reviewed connection inputs plus
#    the validated private PGPASSFILE.
clean_libpq_run() {
  (
    for _v in $(compgen -v PG 2>/dev/null); do unset "$_v"; done
    export PGPASSFILE="$CLEANUP_WRITER"
    export AGENTIC_REAL_LAB=1 AGENTIC_LAB_HOST=127.0.0.1 AGENTIC_LAB_DB="$LAB_DB" PYTHONPATH="$STAGE"
    exec "$@"
  )
}

# the driver must be present in host-proof mode — a missing driver is a hard failure
"$PY" -c 'import psycopg2' 2>/dev/null || { run_cleanup; fail "psycopg2 is required for the real host proof (missing driver is not a skip)"; }

# 6) fail-closed writer authentication preflight in the SAME sanitized environment as the
#    tests. Asserts the connected identity/database/port over TCP and refuses to run the
#    suite if authentication is wrong. Emits ONLY writer_auth_preflight|PASS; never a
#    password, pgpass path, DSN, or connection metadata.
if clean_libpq_run "$PY" - "$LAB_DB" <<'PYEOF'
import os, sys
LIBPQ = ("PGPASSWORD", "PGSERVICE", "PGSERVICEFILE", "PGHOST", "PGPORT", "PGDATABASE",
         "PGUSER", "PGOPTIONS", "PGSSLMODE", "PGSSLCERT", "PGSSLKEY", "PGSSLROOTCERT",
         "PGREQUIRESSL", "PGSSLCRL", "PGCHANNELBINDING", "PGGSSENCMODE",
         "PGTARGETSESSIONATTRS", "PGCONNECT_TIMEOUT")
report = os.environ.get("AGENTIC_PREFLIGHT_ENV_REPORT")
if report:  # test-only: sanitized presence report (variable NAMES only, never values)
    with open(report, "w", encoding="utf-8") as fh:
        for name in (*LIBPQ, "PGPASSFILE"):
            fh.write(f"{name}={'present' if name in os.environ else 'absent'}\n")
if any(name in os.environ for name in LIBPQ):
    sys.exit(5)  # fail closed: inherited libpq environment was not sanitized
if "PGPASSFILE" not in os.environ:
    sys.exit(6)
db = sys.argv[1]
try:
    import psycopg2
    conn = psycopg2.connect(host="127.0.0.1", port=5433, dbname=db,
                            user="agentic_runtime_lab_rw", options="-c search_path=agentic_runtime")
    cur = conn.cursor()
    cur.execute("SELECT current_user, current_database(), inet_server_port()")
    user, database, port = cur.fetchone()
    cur.close()
    conn.close()
except Exception:
    sys.exit(3)  # never print the exception (could carry connection metadata)
if user != "agentic_runtime_lab_rw" or database != db or port != 5433:
    sys.exit(4)
sys.exit(0)
PYEOF
then
  echo "writer_auth_preflight|PASS"
else
  run_cleanup
  fail "writer authentication preflight failed"
fi

# 7) run the REAL psycopg2 adapter suite in the SAME sanitized environment; preserve output
readonly STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
readonly PYTEST_LOG="$EVIDENCE_DIR/agentic-runtime-hostproof-pytest-$STAMP.txt"
readonly JUNIT="$STAGE/real-junit.xml"
mkdir -p "$EVIDENCE_DIR"
set +e
clean_libpq_run "$PY" -m pytest -rA -v -p no:cacheprovider \
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
  run_cleanup
  echo "activation_authority|DENIED"
  echo "production_database_write|NONE"
  echo "final_status|PASS_AGENT_RUNTIME_PERSISTENCE_PROOF"
else
  run_cleanup
  echo "final_status|FAIL_AGENT_RUNTIME_PERSISTENCE_PROOF" >&2
  exit 3
fi
