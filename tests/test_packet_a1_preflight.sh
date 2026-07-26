#!/usr/bin/env bash
# =============================================================================
# Focused tests for packet_a1_lab_persistence.sh --preflight (NO-CONNECTION mode)
# =============================================================================
# Pure shell. Builds throwaway git repos so HEAD/clean-tree state is controlled,
# and prepends a PATH of "forbidden-call" shims (psql, pg_isready, python3, nc)
# plus an in-repo apply.sh shim that touch a sentinel and exit 42 if ever invoked.
# A passing --preflight MUST leave zero sentinels — proving no DB/network/migration
# contact. Uses ONLY fake DSN strings and fake creds (labuser/labsecret); NO real
# DSN is ever supplied.
# =============================================================================
set -uo pipefail

SELF_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SRC_PACKET="$SELF_DIR/../scripts/operator_packets/packet_a1_lab_persistence.sh"
[[ -f "$SRC_PACKET" ]] || { echo "cannot find packet under test: $SRC_PACKET" >&2; exit 1; }

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

PASS=0; FAIL=0
ok()   { PASS=$((PASS+1)); printf '  PASS  %s\n' "$1"; }
bad()  { FAIL=$((FAIL+1)); printf '  FAIL  %s\n     -> %s\n' "$1" "$2"; }

# --- forbidden-call shims (psql/pg_isready/python3/nc): fail-on-invoke ---------
SHIMS="$WORK/shims"; mkdir -p "$SHIMS"
SENT="$WORK/sentinels"; mkdir -p "$SENT"
for tool in psql pg_isready python3 nc; do
  cat > "$SHIMS/$tool" <<SH
#!/usr/bin/env bash
echo "FORBIDDEN CALL: $tool \$*" >&2
: > "$SENT/$tool.called"
exit 42
SH
  chmod +x "$SHIMS/$tool"
done
# git must stay real; PATH keeps the system dirs after the shim dir.
SHPATH="$SHIMS:$PATH"

# --- build a throwaway repo containing the packet + an apply.sh shim ----------
# echoes the repo's HEAD sha on stdout.
make_repo() {
  local repo="$1"
  mkdir -p "$repo/scripts/operator_packets" "$repo/migrations/agentic_runtime"
  cp "$SRC_PACKET" "$repo/scripts/operator_packets/packet_a1_lab_persistence.sh"
  chmod +x "$repo/scripts/operator_packets/packet_a1_lab_persistence.sh"
  cat > "$repo/migrations/agentic_runtime/apply.sh" <<SH
#!/usr/bin/env bash
echo "FORBIDDEN CALL: apply.sh \$*" >&2
: > "$SENT/apply.sh.called"
exit 42
SH
  chmod +x "$repo/migrations/agentic_runtime/apply.sh"
  git -C "$repo" init -q
  git -C "$repo" add -A
  git -C "$repo" -c user.email=t@t -c user.name=t commit -q -m init
  git -C "$repo" rev-parse HEAD
}

REPO="$WORK/repo"
HEAD_SHA="$(make_repo "$REPO")"
SCRIPT="$REPO/scripts/operator_packets/packet_a1_lab_persistence.sh"
EVLOG="$WORK/evidence.log"   # keep any execute-path evidence out of the real backups dir

# Runner: RC and OUT are set. Sentinels wiped before each run.
# usage: runx LAB_DSN LAB_ALLOW -- <args...>
runx() {
  local dsn="$1" allow="$2"; shift 2
  [[ "$1" == "--" ]] && shift
  rm -f "$SENT"/*.called 2>/dev/null || true
  OUT="$(cd "$REPO" && PATH="$SHPATH" A1_EVIDENCE_LOG="$EVLOG" \
        env -u LAB_DSN -u LAB_DSN_ALLOWLIST \
        ${dsn:+LAB_DSN="$dsn"} ${allow:+LAB_DSN_ALLOWLIST="$allow"} \
        bash "$SCRIPT" "$@" 2>&1)"
  RC=$?
}
sentinel_any() { ls "$SENT"/*.called >/dev/null 2>&1; }

VALID_URL="postgresql://labuser:labsecret@labhost:6543/agentic_lab"
VALID_KV="host=labhost port=6543 dbname=agentic_lab user=labuser password=labsecret sslmode=disable"
ALLOW="labhost:6543/agentic_lab"

echo "== packet A1 --preflight focused tests =="
echo "HEAD under test: $HEAD_SHA"

# ---- gate 1: SHA shape ----
runx "$VALID_URL" "$ALLOW" -- "${HEAD_SHA^^}" --preflight
[[ $RC -eq 2 ]] && ok "uppercase SHA rejected" || bad "uppercase SHA rejected" "rc=$RC"

runx "$VALID_URL" "$ALLOW" -- "${HEAD_SHA:0:39}" --preflight
[[ $RC -eq 2 ]] && ok "short SHA rejected" || bad "short SHA rejected" "rc=$RC"

runx "$VALID_URL" "$ALLOW" -- "${HEAD_SHA}a" --preflight
[[ $RC -eq 2 ]] && ok "long SHA rejected" || bad "long SHA rejected" "rc=$RC"

runx "$VALID_URL" "$ALLOW" -- "gggggggggggggggggggggggggggggggggggggggg" --preflight
[[ $RC -eq 2 ]] && ok "non-hex SHA rejected" || bad "non-hex SHA rejected" "rc=$RC"

# ---- gate 2: HEAD mismatch ----
runx "$VALID_URL" "$ALLOW" -- "0000000000000000000000000000000000000000" --preflight
[[ $RC -eq 2 && "$OUT" == *"!= expected release SHA"* ]] \
  && ok "wrong HEAD rejected" || bad "wrong HEAD rejected" "rc=$RC out=$OUT"

# ---- gate 3: dirty tree ----
: > "$REPO/DIRTY_UNTRACKED"
runx "$VALID_URL" "$ALLOW" -- "$HEAD_SHA" --preflight
rm -f "$REPO/DIRTY_UNTRACKED"
[[ $RC -eq 2 && "$OUT" == *"dirty"* ]] \
  && ok "dirty/untracked tree rejected" || bad "dirty/untracked tree rejected" "rc=$RC out=$OUT"

# ---- gate 4/5: required env ----
runx "" "$ALLOW" -- "$HEAD_SHA" --preflight
[[ $RC -eq 4 && "$OUT" == *"LAB_DSN is not set"* ]] \
  && ok "missing LAB_DSN rejected" || bad "missing LAB_DSN rejected" "rc=$RC out=$OUT"

runx "$VALID_URL" "" -- "$HEAD_SHA" --preflight
[[ $RC -eq 4 && "$OUT" == *"LAB_DSN_ALLOWLIST is not set"* ]] \
  && ok "missing allowlist rejected" || bad "missing allowlist rejected" "rc=$RC out=$OUT"

# ---- gate 7: target rejections ----
runx "postgresql://labuser:labsecret@labhost:6543/trade_ai" "labhost:6543/trade_ai" -- "$HEAD_SHA" --preflight
[[ $RC -eq 4 && "$OUT" == *"trade_ai"* ]] \
  && ok "trade_ai database rejected" || bad "trade_ai database rejected" "rc=$RC out=$OUT"

runx "postgresql://labuser:labsecret@prodhost:6543/agentic_lab" "prodhost:6543/agentic_lab" -- "$HEAD_SHA" --preflight
[[ $RC -eq 4 && "$OUT" == *"prod"* ]] \
  && ok "prod host rejected" || bad "prod host rejected" "rc=$RC out=$OUT"

runx "postgresql://labuser:labsecret@labhost:6543/production_lab" "labhost:6543/production_lab" -- "$HEAD_SHA" --preflight
[[ $RC -eq 4 ]] && ok "production db substring rejected" || bad "production db substring rejected" "rc=$RC out=$OUT"

runx "postgresql://labuser:labsecret@labhost:5432/agentic_lab" "labhost:5432/agentic_lab" -- "$HEAD_SHA" --preflight
[[ $RC -eq 4 && "$OUT" == *"5432"* ]] \
  && ok "port 5432 rejected" || bad "port 5432 rejected" "rc=$RC out=$OUT"

runx "postgresql://labuser:labsecret@labhost/agentic_lab" "labhost:6543/agentic_lab" -- "$HEAD_SHA" --preflight
[[ $RC -eq 4 && "$OUT" == *"port is unset"* ]] \
  && ok "unset port rejected" || bad "unset port rejected" "rc=$RC out=$OUT"

runx "$VALID_URL" "otherhost:9999/otherdb" -- "$HEAD_SHA" --preflight
[[ $RC -eq 4 && "$OUT" == *"not on LAB_DSN_ALLOWLIST"* ]] \
  && ok "non-allowlisted target rejected" || bad "non-allowlisted target rejected" "rc=$RC out=$OUT"

runx "this-is-not-a-dsn" "$ALLOW" -- "$HEAD_SHA" --preflight
[[ $RC -eq 4 && "$OUT" == *"malformed"* ]] \
  && ok "malformed target rejected" || bad "malformed target rejected" "rc=$RC out=$OUT"

runx "postgresql://labuser:labsecret@h1,h2:6543/agentic_lab" "$ALLOW" -- "$HEAD_SHA" --preflight
[[ $RC -eq 4 && "$OUT" == *"multiple hosts"* ]] \
  && ok "multiple-host target rejected" || bad "multiple-host target rejected" "rc=$RC out=$OUT"

runx "host=/var/run/postgresql port=6543 dbname=agentic_lab" "$ALLOW" -- "$HEAD_SHA" --preflight
[[ $RC -eq 4 && "$OUT" == *"socket"* ]] \
  && ok "socket/path host rejected" || bad "socket/path host rejected" "rc=$RC out=$OUT"

runx 'host=labhost port=6543 dbname=agentic_lab service=lab' "$ALLOW" -- "$HEAD_SHA" --preflight
[[ $RC -eq 4 && "$OUT" == *"redirect"* ]] \
  && ok "service-file indirection rejected" || bad "service-file indirection rejected" "rc=$RC out=$OUT"

runx "postgresql://labuser:labsecret@labhost:6543/agentic_lab?host=evil" "$ALLOW" -- "$HEAD_SHA" --preflight
[[ $RC -eq 4 && "$OUT" == *"redirect"* ]] \
  && ok "redirecting query param rejected" || bad "redirecting query param rejected" "rc=$RC out=$OUT"

runx 'postgresql://labuser:labsecret@labhost:6543/$LABDB' "$ALLOW" -- "$HEAD_SHA" --preflight
[[ $RC -eq 4 && "$OUT" == *"interpolation"* ]] \
  && ok "env-var interpolation rejected" || bad "env-var interpolation rejected" "rc=$RC out=$OUT"

# ---- valid targets pass (exit 0), NO connection attempted ----
runx "$VALID_URL" "$ALLOW" -- "$HEAD_SHA" --preflight
if [[ $RC -eq 0 && "$OUT" == *"PREFLIGHT PASS"* ]]; then ok "valid URL DSN passes preflight"; \
  else bad "valid URL DSN passes preflight" "rc=$RC out=$OUT"; fi
if ! sentinel_any; then ok "valid URL preflight invoked NO psql/pg_isready/python3/nc/apply.sh"; \
  else bad "valid URL preflight invoked NO forbidden tool" "sentinels: $(ls "$SENT")"; fi
if [[ "$OUT" != *labuser* && "$OUT" != *labsecret* && "$OUT" != *"$VALID_URL"* ]]; then \
  ok "preflight output leaks no username/password/DSN"; \
  else bad "preflight output leaks no username/password/DSN" "$OUT"; fi
# spot-check the required gate-8 fields are present
if [[ "$OUT" == *"host=labhost"* && "$OUT" == *"port=6543"* && "$OUT" == *"database=agentic_lab"* \
      && "$OUT" == *"not_trade_ai=true"* && "$OUT" == *"non_production_port=true"* \
      && "$OUT" == *"allowlist_match=true"* && "$OUT" == *"agent_runs"* \
      && "$OUT" == *"agentic_runtime_reader"* && "$OUT" == *"evidence_path="* ]]; then \
  ok "preflight prints required identity + plan fields"; \
  else bad "preflight prints required identity + plan fields" "$OUT"; fi

runx "$VALID_KV" "$ALLOW" -- "$HEAD_SHA" --preflight
if [[ $RC -eq 0 && "$OUT" == *"PREFLIGHT PASS"* ]]; then ok "valid libpq key-value DSN passes preflight"; \
  else bad "valid libpq key-value DSN passes preflight" "rc=$RC out=$OUT"; fi
if ! sentinel_any; then ok "valid libpq preflight invoked NO forbidden tool"; \
  else bad "valid libpq preflight invoked NO forbidden tool" "sentinels: $(ls "$SENT")"; fi
if [[ "$OUT" != *labuser* && "$OUT" != *labsecret* ]]; then ok "libpq preflight leaks no creds"; \
  else bad "libpq preflight leaks no creds" "$OUT"; fi

# ---- execute path: revalidates BEFORE any psql (prod DSN rejected pre-connect) ----
runx "postgresql://labuser:labsecret@labhost:6543/trade_ai" "labhost:6543/trade_ai" \
     -- "$HEAD_SHA" --execute --ack APPLY-A1-LAB-PERSISTENCE
if [[ $RC -eq 4 ]] && ! sentinel_any; then ok "execute rejects bad target BEFORE first psql"; \
  else bad "execute rejects bad target BEFORE first psql" "rc=$RC sentinels: $(ls "$SENT" 2>/dev/null)"; fi

# ---- execute path: valid target passes validation, THEN reaches psql (not before) ----
runx "$VALID_URL" "$ALLOW" -- "$HEAD_SHA" --execute --ack APPLY-A1-LAB-PERSISTENCE
if [[ -f "$SENT/psql.called" && ! -f "$SENT/apply.sh.called" ]]; then \
  ok "execute reaches psql only after passing validation (applier untouched)"; \
  else bad "execute reaches psql only after passing validation" "rc=$RC sentinels: $(ls "$SENT" 2>/dev/null)"; fi

# ---- --execute --down remains separately ack-gated ----
runx "$VALID_URL" "$ALLOW" -- "$HEAD_SHA" --execute --down
if [[ $RC -eq 2 && "$OUT" == *"requires --ack"* ]] && ! sentinel_any; then \
  ok "--down still requires --ack (no mutation without token)"; \
  else bad "--down still requires --ack" "rc=$RC out=$OUT"; fi

# ---- no-args stays prepare-only and mutates nothing ----
runx "$VALID_URL" "$ALLOW" --
if [[ $RC -eq 2 && "$OUT" == *"PREPARE-ONLY"* ]] && ! sentinel_any; then \
  ok "no-args prepare-only, mutates nothing"; \
  else bad "no-args prepare-only, mutates nothing" "rc=$RC"; fi

# ---- SHA-only (no flags) stays exit-3 plan, no connection ----
runx "$VALID_URL" "$ALLOW" -- "$HEAD_SHA"
if [[ $RC -eq 3 ]] && ! sentinel_any; then ok "SHA-only stays exit-3 prepare plan (no connection)"; \
  else bad "SHA-only stays exit-3 prepare plan" "rc=$RC"; fi

echo
echo "== RESULT: $PASS passed, $FAIL failed =="
[[ $FAIL -eq 0 ]]
