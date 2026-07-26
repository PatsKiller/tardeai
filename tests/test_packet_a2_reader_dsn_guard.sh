#!/usr/bin/env bash
# =============================================================================
# Focused tests for packet_a2_read_plane_deploy.sh :: validate_reader_dsn()
# =============================================================================
# Pure shell. Builds a throwaway git repo so the exact-RC-SHA gate is satisfied,
# and prepends a PATH of fail-on-invoke shims (psql, pg_isready, python3, nc — DB
# drivers / network) plus a curl shim and an inner deploy_read_mount.sh shim, each
# dropping a sentinel when invoked. The reader-DSN guard is pure local string
# parsing: it MUST reach its verdict without touching any DB driver or the network,
# so on every REJECT run zero sentinels appear (not even curl — the guard rejects
# BEFORE the pre-connect smoke). Uses ONLY fake DSNs and fake passwords; NO real
# DSN and NO real DB are ever supplied. The packet is NEVER run against a database.
#
# The bug under repair: the old guard matched *postgres*/*_rw*/*admin*/*prod*
# against the WHOLE DSN string, so it (a) rejected every legitimate postgresql://
# reader URI because the scheme contains "postgres", and (b) false-rejected on any
# password substring. The fix parses user/host/dbname and checks only those.
# =============================================================================
set -uo pipefail

SELF_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SRC_PACKET="$SELF_DIR/../scripts/operator_packets/packet_a2_read_plane_deploy.sh"
[[ -f "$SRC_PACKET" ]] || { echo "cannot find packet under test: $SRC_PACKET" >&2; exit 1; }

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

PASS=0; FAIL=0
ok()  { PASS=$((PASS+1)); printf '  PASS  %s\n' "$1"; }
bad() { FAIL=$((FAIL+1)); printf '  FAIL  %s\n     -> %s\n' "$1" "$2"; }

# --- fail-on-invoke shims: DB drivers / network tools must NEVER fire ----------
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
# curl: sentinels on invoke, returns 000 (no real network). Only the ACCEPT path
# reaches the pre-connect smoke; a REJECT verdict must land BEFORE curl is called.
cat > "$SHIMS/curl" <<SH
#!/usr/bin/env bash
: > "$SENT/curl.called"
echo "000"
exit 0
SH
chmod +x "$SHIMS/curl"
# git stays real; PATH keeps the system dirs after the shim dir.
SHPATH="$SHIMS:$PATH"

# --- throwaway repo: packet + an inner deploy shim (no-op, sentinels) ----------
REPO="$WORK/repo"
mkdir -p "$REPO/scripts/operator_packets" "$REPO/scripts/agent_runtime"
cp "$SRC_PACKET" "$REPO/scripts/operator_packets/packet_a2_read_plane_deploy.sh"
chmod +x "$REPO/scripts/operator_packets/packet_a2_read_plane_deploy.sh"
cat > "$REPO/scripts/agent_runtime/deploy_read_mount.sh" <<SH
#!/usr/bin/env bash
# harmless no-op stand-in for the real host-mutating inner deploy.
: > "$SENT/inner.called"
echo "[inner-shim] would deploy \$1 (no-op)"
exit 0
SH
chmod +x "$REPO/scripts/agent_runtime/deploy_read_mount.sh"
git -C "$REPO" init -q
git -C "$REPO" add -A
git -C "$REPO" -c user.email=t@t -c user.name=t commit -q -m init
HEAD_SHA="$(git -C "$REPO" rev-parse HEAD)"
SCRIPT="$REPO/scripts/operator_packets/packet_a2_read_plane_deploy.sh"

ACK="APPLY-A2-READ-PLANE"
READ_API="http://127.0.0.1:65535/agents/read"   # never contacted (curl is shimmed)

# Runner. Sets RC and OUT. Wipes sentinels first. Passes the DSN via env unless
# the special token __UNSET__ is given (then SHADOW_READER_DSN is unset).
# usage: runx <DSN|__UNSET__> -- <args...>
runx() {
  local dsn="$1"; shift
  [[ "$1" == "--" ]] && shift
  rm -f "$SENT"/*.called 2>/dev/null || true
  if [[ "$dsn" == "__UNSET__" ]]; then
    OUT="$(cd "$REPO" && PATH="$SHPATH" READ_API_URL="$READ_API" \
          env -u SHADOW_READER_DSN \
          bash "$SCRIPT" "$@" 2>&1)"; RC=$?
  else
    OUT="$(cd "$REPO" && PATH="$SHPATH" READ_API_URL="$READ_API" \
          SHADOW_READER_DSN="$dsn" \
          bash "$SCRIPT" "$@" 2>&1)"; RC=$?
  fi
}
sentinel_any()  { ls "$SENT"/*.called       >/dev/null 2>&1; }
db_sentinel()   { ls "$SENT"/psql.called "$SENT"/pg_isready.called \
                     "$SENT"/python3.called "$SENT"/nc.called 2>/dev/null | grep -q . ; }

# Fake, clearly-not-real DSNs. Passwords are deliberately loaded with rw/prod/
# postgres/admin substrings to prove the password is NEVER scanned.
READER_URL="postgresql://agentic_runtime_reader:SomePass@127.0.0.1:5433/trade_ai_agentic_lab"
READER_KV="host=127.0.0.1 port=5433 dbname=trade_ai_agentic_lab user=agentic_runtime_reader password=SomePass"
TRAP_PW="aRwProdPostgresAdmin123"
READER_TRAP_PW="postgresql://agentic_runtime_reader:${TRAP_PW}@127.0.0.1:5433/trade_ai_agentic_lab"

echo "== packet A2 validate_reader_dsn focused tests =="
echo "HEAD under test: $HEAD_SHA"

# ---- (1) empty SHADOW_READER_DSN rejected (exit 4) ---------------------------
runx "__UNSET__" -- "$HEAD_SHA" --execute --ack "$ACK"
if [[ $RC -eq 4 && "$OUT" == *"SHADOW_READER_DSN is not set"* ]] && ! sentinel_any; then
  ok "empty SHADOW_READER_DSN rejected (exit 4), no connection"
else bad "empty SHADOW_READER_DSN rejected" "rc=$RC out=$OUT sent=$(ls "$SENT" 2>/dev/null)"; fi

# ---- (2) THE BUG: URL-form reader DSN ACCEPTED (scheme contains 'postgres') ---
runx "$READER_URL" -- "$HEAD_SHA" --execute --ack "$ACK"
if [[ $RC -eq 0 && "$OUT" == *"SHADOW reader DSN accepted"* ]]; then
  ok "URL-form reader DSN ACCEPTED (postgresql:// scheme no longer false-rejects)"
else bad "URL-form reader DSN ACCEPTED" "rc=$RC out=$OUT"; fi
if ! db_sentinel; then ok "URL-form accept invoked NO psql/pg_isready/python3/nc (no DB driver)"; \
  else bad "URL-form accept invoked NO DB driver" "sent=$(ls "$SENT")"; fi

# ---- (3) libpq key=value reader DSN ACCEPTED ---------------------------------
runx "$READER_KV" -- "$HEAD_SHA" --execute --ack "$ACK"
if [[ $RC -eq 0 && "$OUT" == *"SHADOW reader DSN accepted"* ]]; then
  ok "libpq key-value reader DSN ACCEPTED"
else bad "libpq key-value reader DSN ACCEPTED" "rc=$RC out=$OUT"; fi
if ! db_sentinel; then ok "libpq accept invoked NO DB driver"; \
  else bad "libpq accept invoked NO DB driver" "sent=$(ls "$SENT")"; fi

# ---- (4) reader DSN whose PASSWORD carries rw/prod/postgres/admin: ACCEPTED ---
runx "$READER_TRAP_PW" -- "$HEAD_SHA" --execute --ack "$ACK"
if [[ $RC -eq 0 && "$OUT" == *"SHADOW reader DSN accepted"* ]]; then
  ok "reader DSN with rw/prod/postgres/admin PASSWORD ACCEPTED (password not scanned)"
else bad "reader DSN with trap password ACCEPTED" "rc=$RC out=$OUT"; fi
# ---- (also 'value never printed'): the fake password never appears in output -
if [[ "$OUT" != *"$TRAP_PW"* && "$OUT" != *"$READER_TRAP_PW"* ]]; then
  ok "guard output leaks no password / DSN value"
else bad "guard output leaks no password / DSN value" "$OUT"; fi

# ---- (5) writer user rejected ( *_rw ) ---------------------------------------
runx "postgresql://agentic_runtime_lab_rw:x@127.0.0.1:5433/db" -- "$HEAD_SHA" --execute --ack "$ACK"
if [[ $RC -eq 4 ]] && ! sentinel_any; then ok "writer user (agentic_runtime_lab_rw) REJECTED"; \
  else bad "writer user REJECTED" "rc=$RC out=$OUT sent=$(ls "$SENT" 2>/dev/null)"; fi

# ---- (6) superuser identity rejected ( postgres ) ----------------------------
runx "postgresql://postgres:x@127.0.0.1:5433/db" -- "$HEAD_SHA" --execute --ack "$ACK"
if [[ $RC -eq 4 ]] && ! sentinel_any; then ok "superuser user (postgres) REJECTED"; \
  else bad "superuser user REJECTED" "rc=$RC out=$OUT"; fi

# ---- (7) user containing admin / prod rejected -------------------------------
runx "postgresql://agentic_admin:x@127.0.0.1:5433/db" -- "$HEAD_SHA" --execute --ack "$ACK"
if [[ $RC -eq 4 ]] && ! sentinel_any; then ok "user containing 'admin' REJECTED"; \
  else bad "user containing 'admin' REJECTED" "rc=$RC out=$OUT"; fi
runx "postgresql://prod_reader:x@127.0.0.1:5433/db" -- "$HEAD_SHA" --execute --ack "$ACK"
if [[ $RC -eq 4 ]] && ! sentinel_any; then ok "user containing 'prod' REJECTED"; \
  else bad "user containing 'prod' REJECTED" "rc=$RC out=$OUT"; fi

# ---- (8) host / dbname containing prod rejected (user IS the reader) ----------
runx "postgresql://agentic_runtime_reader:x@prodhost:5433/trade_ai_agentic_lab" -- "$HEAD_SHA" --execute --ack "$ACK"
if [[ $RC -eq 4 && "$OUT" == *"host"* ]] && ! sentinel_any; then ok "host containing 'prod' REJECTED"; \
  else bad "host containing 'prod' REJECTED" "rc=$RC out=$OUT"; fi
runx "postgresql://agentic_runtime_reader:x@127.0.0.1:5433/prod_lab" -- "$HEAD_SHA" --execute --ack "$ACK"
if [[ $RC -eq 4 && "$OUT" == *"dbname"* ]] && ! sentinel_any; then ok "dbname containing 'prod' REJECTED"; \
  else bad "dbname containing 'prod' REJECTED" "rc=$RC out=$OUT"; fi

# ---- (9) dbname EXACTLY trade_ai rejected (even for the reader role) ----------
runx "postgresql://agentic_runtime_reader:x@127.0.0.1:5433/trade_ai" -- "$HEAD_SHA" --execute --ack "$ACK"
if [[ $RC -eq 4 && "$OUT" == *"trade_ai"* ]] && ! sentinel_any; then ok "dbname exactly 'trade_ai' REJECTED"; \
  else bad "dbname exactly 'trade_ai' REJECTED" "rc=$RC out=$OUT"; fi

# ---- (10) sanity: the LAB dbname trade_ai_agentic_lab is NOT rejected ---------
# (already proven ACCEPTED in tests 2/3/4; this asserts the substring guard did
#  not over-reach onto the legitimate lab dbname)
runx "$READER_URL" -- "$HEAD_SHA" --execute --ack "$ACK"
if [[ $RC -eq 0 ]]; then ok "lab dbname trade_ai_agentic_lab NOT over-rejected"; \
  else bad "lab dbname trade_ai_agentic_lab NOT over-rejected" "rc=$RC out=$OUT"; fi

# ---- (11) no-connection proof: a REJECT verdict fires with ZERO sentinels -----
# (the guard rejects by pure parsing, before the pre-connect curl smoke)
runx "postgresql://postgres:x@127.0.0.1:5433/db" -- "$HEAD_SHA" --execute --ack "$ACK"
if [[ $RC -eq 4 ]] && ! ls "$SENT"/curl.called >/dev/null 2>&1 && ! db_sentinel; then
  ok "REJECT reached before ANY curl/DB call (guard does no network)"
else bad "REJECT does no network" "rc=$RC sent=$(ls "$SENT" 2>/dev/null)"; fi

# ---- (12) malformed DSN (neither URL nor key=value) rejected -----------------
runx "not-a-dsn-at-all" -- "$HEAD_SHA" --execute --ack "$ACK"
if [[ $RC -eq 4 && "$OUT" == *"malformed"* ]] && ! sentinel_any; then ok "malformed DSN REJECTED"; \
  else bad "malformed DSN REJECTED" "rc=$RC out=$OUT"; fi

echo
echo "== RESULT: $PASS passed, $FAIL failed =="
[[ $FAIL -eq 0 ]]
