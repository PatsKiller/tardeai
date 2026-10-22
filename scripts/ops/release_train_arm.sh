#!/usr/bin/env bash
# release_train_arm.sh: OPERATOR ONLY. Arms Release Train v2, packet steps A-G
# (docs/ops/packets/release-train-arming-20261021/README.md). Each step is a separate operator act (AGENTS §17).
#
#   bash scripts/ops/release_train_arm.sh plan                 dry run of A..G in order (writes nothing)
#   bash scripts/ops/release_train_arm.sh status               one read-only line per step
#   bash scripts/ops/release_train_arm.sh <step>               dry run of one step (the default; writes nothing)
#   bash scripts/ops/release_train_arm.sh <step> --verify      read-only check that the step is in place
#   TRADEAI_RELEASE_TRAIN_ARM_ACK=<LETTER> bash scripts/ops/release_train_arm.sh <step> --apply
#
# Steps (letter = packet section):
#   A migrate         apply migrations/2026_10_21_release_queue.sql (psql args in RTARM_PSQL_ARGS)
#   B capability-key  create ~/.config/tradeai/release_train/capability.key (32 random bytes, hex; mode 600)
#   C delegation      create ~/.config/tradeai/release_train/delegation.json from the example: PAUSED, windows off
#   D claimer-units   install + enable tradeai-release-train-claim.{path,timer,service} (user systemd)
#   E live-lanes      add the 4 release-train-request-* lanes + pr-hygiene-audit to TRADEAI_N8N_RELAY_LIVE_LANES,
#                     restart relay + gateway, run check_n8n_relay_contract.py (needs TRADEAI_CONFIG_WRITE_GRANT)
#   F workflow        import + publish tradeai-fabric-release-train in m8m-n8n (needs TRADEAI_FABRIC_GRANT);
#                     refused while the AGENTS §23.24 import gate refuses it
#   G state-dir       compare the CC STOP state_dir with the runner / CLI / gateway / path unit (read-only always)
#
# Rails. Dry run is the default. --apply needs TRADEAI_RELEASE_TRAIN_ARM_ACK set to that step's letter (one
# acknowledgement per step, so one exported variable cannot arm everything). Every invocation refuses unless it runs
# on host ms01-openclaw as the portfolio-server user (johnclaw, not root). Every step is idempotent: a step already
# in place is NOOP. Nothing is ever deleted or overwritten in place without a backup (§0 rule 6); a file that exists
# and differs is a refusal, never a replacement. Every --apply attempt appends one ReleaseTrainArmReceipt@v1 line to
# <state root>/data/runtime/release_train_arm/receipts.jsonl (append-only, fsync). No credential is read or printed:
# the capability key is generated into its file and only its mode/owner/length are reported; the DB password comes
# from the operator's own ~/.pgpass through psql. MBI_BEHAVIOR = 0: no broker, no order path.
#
# Test sandbox. RTARM_SANDBOX=<dir> (a dir under $TMPDIR or /tmp holding a .rtarm-sandbox marker) rebases HOME and
# every path into the sandbox, requires psql/systemctl/docker/curl to resolve INSIDE the sandbox (stubs), and only
# then honours the RTARM_* test overrides. Without it those overrides are ignored.
#
# Exit: 0 ok (dry run, applied, NOOP, verified), 1 verification failed, 2 refused, 3 usage.
set -euo pipefail

EXPECT_USER_DEFAULT="johnclaw"
EXPECT_HOST_DEFAULT="ms01-openclaw"
CANONICAL_DEFAULT="/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild"
RELAY_URL="http://172.19.0.1:18092"
CC_BASE="http://127.0.0.1:7777"
WF_ID="tradeai-fabric-release-train"
ERROR_WF_ID="tradeai-fabric-error"
LANES=(release-train-request-1800 release-train-request-0000 release-train-request-0600 release-train-request-0800
       pr-hygiene-audit)
UNITS=(tradeai-release-train-claim.service tradeai-release-train-claim.path tradeai-release-train-claim.timer)
MIGRATION_REL="migrations/2026_10_21_release_queue.sql"
UNIT_SRC_REL="docs/ops/packets/release-train-20261021"
WF_REL="docs/implementation/n8n-maturity/workflows/fabric/${WF_ID}.json"
PENDING_REL="docs/ops/packets/release-train-arming-20261021/framework_pending_evidence.json"   # finding 2: what the gate still needs
EXAMPLE_REL="config/release_train_delegation.example.json"

die_usage() { echo "usage: $0 plan|status|<A..G|step-name> [--apply|--verify]" >&2; exit 3; }
refuse() { echo "REFUSED: $*"; exit 2; }
say() { echo "$*"; }

# ── arguments ──────────────────────────────────────────────────────────────────────────────────────────
[[ $# -ge 1 ]] || die_usage
CMD="$1"; shift
MODE="dry"
for a in "$@"; do
  case "$a" in
    --apply) MODE="apply" ;;
    --verify) MODE="verify" ;;
    --dry-run) MODE="dry" ;;
    *) die_usage ;;
  esac
done

step_letter() {
  case "$1" in
    A|a|migrate) echo A ;; B|b|capability-key) echo B ;; C|c|delegation) echo C ;;
    D|d|claimer-units) echo D ;; E|e|live-lanes) echo E ;; F|f|workflow) echo F ;; G|g|state-dir) echo G ;;
    *) echo "" ;;
  esac
}

# ── sandbox and paths ──────────────────────────────────────────────────────────────────────────────────
SANDBOX=""
if [[ -n "${RTARM_SANDBOX:-}" ]]; then
  SANDBOX="$(realpath -e -- "$RTARM_SANDBOX" 2>/dev/null)" || refuse "RTARM_SANDBOX does not exist"
  [[ -f "$SANDBOX/.rtarm-sandbox" ]] || refuse "RTARM_SANDBOX has no .rtarm-sandbox marker"
  tmp_root="$(realpath -e -- "${TMPDIR:-/tmp}")"
  case "$SANDBOX/" in
    "$tmp_root"/*|/tmp/*) ;;
    *) refuse "RTARM_SANDBOX must be under \$TMPDIR ($tmp_root) or /tmp" ;;
  esac
  [[ "$SANDBOX" != "$tmp_root" ]] || refuse "RTARM_SANDBOX must be a dir below \$TMPDIR, not \$TMPDIR itself"
  export HOME="$SANDBOX/home"
  mkdir -p "$HOME"
  export TRADEAI_STATE_ROOT="$HOME/trade-ai-releases/persistent-state"
  export TRADEAI_RELEASE_WINDOW_STATE_DIR="$TRADEAI_STATE_ROOT/data/runtime/release_window"
  for tool in psql systemctl docker curl; do
    p="$(command -v "$tool" || true)"
    [[ -z "$p" ]] && continue
    p="$(realpath -e -- "$p")"
    case "$p" in "$SANDBOX"/*) ;; *) refuse "sandbox: $tool resolves outside the sandbox ($p); put a stub first on PATH" ;; esac
  done
  EXPECT_USER="${RTARM_EXPECT_USER:-$EXPECT_USER_DEFAULT}"
  EXPECT_HOST="${RTARM_EXPECT_HOST:-$EXPECT_HOST_DEFAULT}"
  CODE_ROOT="${RTARM_CODE_ROOT:?sandbox needs RTARM_CODE_ROOT}"
  PY="${RTARM_PY:?sandbox needs RTARM_PY}"
  RELAY_PROBE="${RTARM_RELAY_PROBE:-1}"
  IMPORT_GATE="${RTARM_IMPORT_GATE:-real}"
  NOW_HM="${RTARM_NOW_HM:-}"
  USE_CC_CURL=0
else
  EXPECT_USER="$EXPECT_USER_DEFAULT"
  EXPECT_HOST="$EXPECT_HOST_DEFAULT"
  CODE_ROOT="$HOME/trade-ai-releases/portfolio-server/CURRENT"
  PY="$CODE_ROOT/.venv/bin/python"
  [[ -x "$PY" ]] || PY="$CANONICAL_DEFAULT/.venv/bin/python"
  RELAY_PROBE=1
  IMPORT_GATE="real"
  NOW_HM=""
  USE_CC_CURL=1
fi
# The release_window resolution (scripts/release_window.py STATE_ROOT / STATE_DIR), at call time.
STATE_ROOT="${TRADEAI_STATE_ROOT:-$HOME/trade-ai-releases/persistent-state}"
STATE_DIR="${TRADEAI_RELEASE_WINDOW_STATE_DIR:-$STATE_ROOT/data/runtime/release_window}"
STATE_DIR_SOURCE="default"
[[ -n "${TRADEAI_STATE_ROOT:-}" ]] && STATE_DIR_SOURCE="env:TRADEAI_STATE_ROOT"
[[ -n "${TRADEAI_RELEASE_WINDOW_STATE_DIR:-}" ]] && STATE_DIR_SOURCE="env:TRADEAI_RELEASE_WINDOW_STATE_DIR"
UNIT_STATE_DIR="$HOME/trade-ai-releases/persistent-state/data/runtime/release_window"   # what the .path unit hardcodes
CONF_DIR="$HOME/.config/tradeai/release_train"
KEY_PATH="$CONF_DIR/capability.key"
DELEG_PATH="$CONF_DIR/delegation.json"
UNIT_DIR="$HOME/.config/systemd/user"
LIVE_ENV="$HOME/.config/tradeai/n8n-live-lanes.env"
ARM_DIR="$STATE_ROOT/data/runtime/release_train_arm"
RECEIPTS="$ARM_DIR/receipts.jsonl"

if [[ -n "$SANDBOX" ]]; then
  for v in STATE_ROOT STATE_DIR CONF_DIR UNIT_DIR LIVE_ENV ARM_DIR; do
    case "${!v}/" in "$SANDBOX"/*) ;; *) refuse "sandbox: $v=${!v} is outside the sandbox" ;; esac
  done
fi

# ── identity: on the host, as the portfolio-server user ───────────────────────────────────────────────
identity_check() {
  [[ "$(id -u)" != "0" ]] || refuse "never as root"
  [[ "$(id -un)" == "$EXPECT_USER" ]] || refuse "run as the portfolio-server user $EXPECT_USER (now $(id -un))"
  [[ "$(hostname -s)" == "$EXPECT_HOST" ]] || refuse "run on host $EXPECT_HOST (now $(hostname -s))"
  systemctl --user cat portfolio-server.service >/dev/null 2>&1 \
    || refuse "portfolio-server.service is not a user unit of $(id -un): not the portfolio-server user"
}

# ── receipts (append-only) ─────────────────────────────────────────────────────────────────────────────
receipt() {   # receipt <step> <outcome> <detail>
  local step="$1" outcome="$2" detail="${3:-}"
  local code_sha
  code_sha="$(basename "$(readlink -f "$CODE_ROOT" 2>/dev/null || echo "$CODE_ROOT")")"
  install -d -m 700 "$ARM_DIR"
  RTARM_R_STEP="$step" RTARM_R_OUT="$outcome" RTARM_R_DETAIL="$detail" RTARM_R_CODE="$code_sha" \
  RTARM_R_GRANT="${TRADEAI_CONFIG_WRITE_GRANT:-}${TRADEAI_FABRIC_GRANT:+ fabric:$TRADEAI_FABRIC_GRANT}" \
  "$PY" - "$RECEIPTS" <<'PYEOF'
import fcntl, json, os, socket, sys, time
from datetime import datetime, timezone
path = sys.argv[1]
row = {"schema": "ReleaseTrainArmReceipt@v1",
       "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
       "step": os.environ["RTARM_R_STEP"], "mode": "apply", "outcome": os.environ["RTARM_R_OUT"],
       "detail": os.environ.get("RTARM_R_DETAIL", "")[:800], "user": os.environ.get("USER") or str(os.getuid()),
       "uid": os.getuid(), "host": socket.gethostname(), "code_root_release": os.environ.get("RTARM_R_CODE"),
       "grant": os.environ.get("RTARM_R_GRANT") or None, "tool": "scripts/ops/release_train_arm.sh"}
fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
try:
    fcntl.flock(fd, fcntl.LOCK_EX)
    os.write(fd, (json.dumps(row, sort_keys=True) + "\n").encode())
    os.fsync(fd)
finally:
    os.close(fd)
PYEOF
}

need_ack() {   # need_ack <letter>
  if [[ "${TRADEAI_RELEASE_TRAIN_ARM_ACK:-}" != "$1" ]]; then
    receipt "$1" "REFUSED_NO_ACK" "TRADEAI_RELEASE_TRAIN_ARM_ACK != $1"
    refuse "--apply for step $1 needs TRADEAI_RELEASE_TRAIN_ARM_ACK=$1 (operator acknowledgement, one per step)"
  fi
}

stamp() { date -u +%Y%m%dT%H%M%SZ; }

code_has() {   # code_has <rel> <needle>
  [[ -f "$CODE_ROOT/$1" ]] && grep -q -- "$2" "$CODE_ROOT/$1"
}

require_train_code() {
  code_has scripts/release_window.py "train-claim" \
    || refuse "$CODE_ROOT does not carry the release-train code (release Release 2 first; scripts/release_window.py has no train-claim)"
}

# ══ A: queue migration ═════════════════════════════════════════════════════════════════════════════════
psql_q() { # shellcheck disable=SC2086
  psql ${RTARM_PSQL_ARGS:-} -X -tA -v ON_ERROR_STOP=1 -c "$1"
}

a_scan() {
  "$PY" - "$CODE_ROOT/$MIGRATION_REL" <<'PYEOF'
import hashlib, re, sys
p = sys.argv[1]
raw = open(p, "rb").read()
text = "\n".join(l.split("--", 1)[0] for l in raw.decode().splitlines())
bad = []
for rx in (r"\bDROP\s+(TABLE|INDEX|TRIGGER|FUNCTION|SCHEMA|VIEW)\b", r"\bDELETE\s+FROM\b", r"(^|;)\s*TRUNCATE\b",
           r"\bALTER\s+TABLE\b", r"\bUPDATE\s+\w+\s+SET\b"):
    if re.search(rx, text, re.I | re.M):
        bad.append(rx)
creates = re.findall(r"CREATE\s+(?:TABLE|INDEX)\s+IF\s+NOT\s+EXISTS\s+(\w+)", text, re.I)
print(f"migration {p}")
print(f"  sha256 {hashlib.sha256(raw).hexdigest()}  creates (IF NOT EXISTS): {', '.join(creates)}")
print("  destructive statements: " + (", ".join(bad) if bad else "none (additive)"))
sys.exit(1 if bad else 0)
PYEOF
}

a_state() {   # prints APPLIED | ABSENT | PARTIAL ; needs RTARM_PSQL_ARGS
  local n t
  n="$(psql_q "SELECT (to_regclass('public.release_queue_events') IS NOT NULL)::int + (to_regclass('public.release_queue') IS NOT NULL)::int")"
  t="$(psql_q "SELECT count(*) FROM pg_trigger WHERE tgname IN ('release_queue_events_no_update_delete','release_queue_events_no_truncate')")"
  if [[ "$n" == "2" && "$t" == "2" ]]; then echo APPLIED
  elif [[ "$n" == "0" ]]; then echo ABSENT
  else echo "PARTIAL(tables=$n,triggers=$t)"; fi
}

step_A() {
  [[ -f "$CODE_ROOT/$MIGRATION_REL" ]] || refuse "no $MIGRATION_REL under $CODE_ROOT (release Release 2 first)"
  local role_expect="trade_ai"
  case "$MODE" in
    dry)
      a_scan || refuse "the migration carries a destructive statement"
      say "  WOULD (apply): psql \$RTARM_PSQL_ARGS -X -v ON_ERROR_STOP=1 -f $CODE_ROOT/$MIGRATION_REL"
      say "  as DB role $role_expect (the controller's DB_USER, so it owns the tables); RTARM_PSQL_ARGS e.g. '-h 127.0.0.1 -U trade_ai -d trade_ai'"
      say "  idempotent: CREATE ... IF NOT EXISTS; skipped when both tables and both append-only triggers exist"
      say "  verify: to_regclass(release_queue_events, release_queue) both set + 2 triggers; CC store.value.state = OK"
      ;;
    verify)
      [[ -n "${RTARM_PSQL_ARGS:-}" ]] || refuse "set RTARM_PSQL_ARGS (psql connection args) to verify"
      local s; s="$(a_state)"; say "  store: $s"
      [[ "$s" == "APPLIED" ]] || exit 1
      ;;
    apply)
      need_ack A
      [[ -n "${RTARM_PSQL_ARGS:-}" ]] || { receipt A REFUSED "RTARM_PSQL_ARGS unset"; refuse "set RTARM_PSQL_ARGS"; }
      a_scan >/dev/null || { receipt A REFUSED "destructive statement"; refuse "destructive statement in the migration"; }
      local role; role="$(psql_q "SELECT current_user")"
      [[ "$role" == "$role_expect" ]] || { receipt A REFUSED "role $role"; refuse "connected as DB role '$role'; apply as '$role_expect' so the controller's role owns the tables"; }
      local s; s="$(a_state)"
      if [[ "$s" == "APPLIED" ]]; then receipt A NOOP "already applied"; say "NOOP: release_queue store already migrated"; return 0; fi
      # shellcheck disable=SC2086
      psql ${RTARM_PSQL_ARGS} -X -v ON_ERROR_STOP=1 -f "$CODE_ROOT/$MIGRATION_REL"
      s="$(a_state)"
      if [[ "$s" != "APPLIED" ]]; then receipt A FAILED "after apply: $s"; echo "FAILED: store reads $s after apply; reverse: migrations/2026_10_21_release_queue.down.sql (renames, never drops)"; exit 1; fi
      receipt A APPLIED "release_queue_events + release_queue + 2 triggers"
      say "APPLIED: store migrated (2 tables, 2 append-only triggers)"
      ;;
  esac
}

# ══ B: capability key ══════════════════════════════════════════════════════════════════════════════════
b_state() {   # ABSENT | OK | BAD:<why>   (stat only; the key's bytes are never read here)
  [[ -e "$KEY_PATH" || -L "$KEY_PATH" ]] || { echo ABSENT; return; }
  [[ ! -L "$KEY_PATH" ]] || { echo "BAD:symlink"; return; }
  [[ -f "$KEY_PATH" ]] || { echo "BAD:not_a_regular_file"; return; }
  local mode owner size
  mode="$(stat -c '%a' "$KEY_PATH")"; owner="$(stat -c '%u' "$KEY_PATH")"; size="$(stat -c '%s' "$KEY_PATH")"
  [[ "$owner" == "$(id -u)" ]] || { echo "BAD:owner_uid_$owner"; return; }
  [[ "$mode" == "600" ]] || { echo "BAD:mode_$mode"; return; }
  [[ "$size" -ge 64 ]] || { echo "BAD:size_${size}_lt_64"; return; }
  echo OK
}

step_B() {
  local s; s="$(b_state)"
  case "$MODE" in
    dry)
      say "  key $KEY_PATH: $s"
      case "$s" in
        ABSENT) say "  WOULD: install -d -m 700 $CONF_DIR; write 32 random bytes as 64 hex chars + newline, O_EXCL, mode 600, fsync" ;;
        OK) say "  WOULD: NOOP (present, mode 600, owner $(id -un), >= 64 bytes); never regenerated" ;;
        *) say "  WOULD REFUSE: present but $s; never overwritten. Archive it by rename (mv capability.key capability.key.archived-<stamp>) and re-run" ;;
      esac
      say "  verify: release_capability.load_key(path) accepts it (regular file, owner, mode 600, >= 32 bytes)"
      ;;
    verify)
      say "  key: $s"
      [[ "$s" == OK ]] || exit 1
      ( cd "$CODE_ROOT" && "$PY" -c 'import sys; from pathlib import Path; from scripts.lib import release_capability as C
try:
    C.load_key(Path(sys.argv[1])); print("  load_key: KEY_OK")
except C.CapabilityRefused as e:
    print("  load_key:", e.code); sys.exit(1)' "$KEY_PATH" ) || exit 1
      ;;
    apply)
      need_ack B
      case "$s" in
        OK) receipt B NOOP "present"; say "NOOP: capability key present and valid (never regenerated)"; return 0 ;;
        ABSENT) ;;
        *) receipt B REFUSED "$s"; refuse "key present but $s; archive it by rename first" ;;
      esac
      install -d -m 700 "$CONF_DIR"
      chmod 700 "$CONF_DIR"
      "$PY" - "$KEY_PATH" <<'PYEOF'
import os, secrets, sys
fd = os.open(sys.argv[1], os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
try:
    os.write(fd, (secrets.token_hex(32) + "\n").encode())
    os.fsync(fd)
finally:
    os.close(fd)
PYEOF
      s="$(b_state)"
      [[ "$s" == OK ]] || { receipt B FAILED "$s"; echo "FAILED: key reads $s after creation"; exit 1; }
      receipt B APPLIED "created mode 600, 65 bytes (hex)"
      say "APPLIED: capability key created at $KEY_PATH (mode 600; contents never printed)"
      ;;
  esac
}

# ══ C: delegation record ═══════════════════════════════════════════════════════════════════════════════
c_render() {   # prints the delegation JSON the step would write (to stdout)
  ( cd "$CODE_ROOT" && "$PY" - "$EXAMPLE_REL" <<'PYEOF'
import json, sys
from datetime import datetime
from zoneinfo import ZoneInfo
from scripts.lib import release_delegation as RD
d = json.load(open(sys.argv[1]))
now = datetime.now(ZoneInfo("America/New_York"))
assert d.get("status") == "PAUSED", "example is not PAUSED"
assert all(s.get("enabled") is False for s in d["windows"]["slots"]), "example has an enabled window"
d["delegation_id"] = "rtd-" + now.strftime("%Y%m%d") + "-operator"
d["operator"]["approved_at"] = now.isoformat(timespec="seconds")
d["operator"]["approved_via"] = "host_cli"
d["notes"] = ("Created " + now.isoformat(timespec="seconds") + " by scripts/ops/release_train_arm.sh delegation "
              "--apply from config/release_train_delegation.example.json. PAUSED, every window disabled: nothing is "
              "armed. Arming is packet step I (release_control_cli.py arm, at the host TTY).")
errs = RD.validate(d)
if errs:
    print("INVALID: " + "; ".join(errs), file=sys.stderr)
    sys.exit(1)
print(json.dumps(d, indent=2, sort_keys=False))
PYEOF
  )
}

c_verdict() {   # prints "<code> <digest|-> <enabled windows>"
  ( cd "$CODE_ROOT" && "$PY" - "$DELEG_PATH" <<'PYEOF'
import sys
from pathlib import Path
from scripts.lib import release_delegation as RD
v = RD.load(Path(sys.argv[1]))
en = [s["window_id"] for s in ((v.delegation or {}).get("windows") or {}).get("slots", []) if s.get("enabled")]
print(v.code, v.digest or "-", ",".join(en) or "none")
PYEOF
  )
}

step_C() {
  local present=0; [[ -e "$DELEG_PATH" || -L "$DELEG_PATH" ]] && present=1
  case "$MODE" in
    dry)
      if [[ $present == 1 ]]; then
        say "  delegation $DELEG_PATH present: $(c_verdict) (mode $(stat -c '%a' "$DELEG_PATH"))"
        say "  WOULD: NOOP (never overwritten; status edits are the operator's, then change-scope/arm)"
      else
        local body; body="$(c_render)" || refuse "the example does not render to a valid PAUSED record"
        local dg; dg="$(printf '%s' "$body" | "$PY" -c 'import sys,json,hashlib; d=json.load(sys.stdin); print(hashlib.sha256(json.dumps(d,sort_keys=True,separators=(",",":"),ensure_ascii=False).encode()).hexdigest())')"
        say "  WOULD write $DELEG_PATH (O_EXCL, mode 600): status PAUSED, windows 1800/0000/0600/0800 all disabled"
        say "  rendered delegation_id $(printf '%s' "$body" | "$PY" -c 'import sys,json; print(json.load(sys.stdin)["delegation_id"])'), digest $dg (approved_at is stamped at write time, so the applied digest differs)"
      fi
      say "  then at the host TTY (operator, step C.3): python3 scripts/release_control_cli.py arm --delegation $DELEG_PATH --reason '...' --dry-run"
      say "    expected while PAUSED: REFUSED DELEGATION_PAUSED (arm accepts only an ACTIVE record; acceptance is step I)"
      ;;
    verify)
      [[ $present == 1 ]] || { say "  delegation: MISSING"; exit 1; }
      local v; v="$(c_verdict)"; say "  delegation: $v; mode $(stat -c '%a' "$DELEG_PATH")"
      [[ "$(stat -c '%a' "$DELEG_PATH")" == 600 ]] || exit 1
      case "$v" in PAUSED*|AUTHORIZED*) ;; *) exit 1 ;; esac
      ( cd "$CODE_ROOT" && "$PY" scripts/release_control_cli.py --state-dir "$STATE_DIR" status ) | sed 's/^/  /'
      ;;
    apply)
      need_ack C
      if [[ $present == 1 ]]; then
        local v; v="$(c_verdict)"
        case "$v" in
          PAUSED*|AUTHORIZED*|REVOKED*)
            [[ "$(stat -c '%a' "$DELEG_PATH")" == 600 ]] || chmod 600 "$DELEG_PATH"
            receipt C NOOP "present: $v"; say "NOOP: delegation present ($v); never overwritten"; return 0 ;;
          *) receipt C REFUSED "present but $v"; refuse "delegation present but $v; archive it by rename, then re-run" ;;
        esac
      fi
      local body; body="$(c_render)" || { receipt C REFUSED "example invalid"; refuse "example does not render"; }
      install -d -m 700 "$CONF_DIR"
      printf '%s\n' "$body" | "$PY" -c '
import os, sys
data = sys.stdin.buffer.read()
fd = os.open(sys.argv[1], os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
try:
    os.write(fd, data); os.fsync(fd)
finally:
    os.close(fd)' "$DELEG_PATH"
      local v; v="$(c_verdict)"
      case "$v" in PAUSED*) ;; *) receipt C FAILED "$v"; echo "FAILED: written record reads $v"; exit 1 ;; esac
      receipt C APPLIED "PAUSED, windows none; $v"
      say "APPLIED: $DELEG_PATH written (mode 600): $v"
      say "NEXT (operator, TTY): python3 scripts/release_control_cli.py arm --delegation $DELEG_PATH --reason 'C.3 check' --dry-run   -> REFUSED DELEGATION_PAUSED"
      ;;
  esac
}

# ══ D: claimer units ═══════════════════════════════════════════════════════════════════════════════════
d_files_state() {   # ABSENT | SAME | DIFFERS:<unit> | PARTIAL
  local n_same=0 n_abs=0 u
  for u in "${UNITS[@]}"; do
    if [[ ! -e "$UNIT_DIR/$u" ]]; then n_abs=$((n_abs+1))
    elif cmp -s "$CODE_ROOT/$UNIT_SRC_REL/$u.proposed" "$UNIT_DIR/$u"; then n_same=$((n_same+1))
    else echo "DIFFERS:$u"; return; fi
  done
  if [[ $n_abs == 3 ]]; then echo ABSENT; elif [[ $n_same == 3 ]]; then echo SAME; else echo PARTIAL; fi
}

d_enabled() {   # ENABLED when path + timer are enabled and active
  local u
  for u in tradeai-release-train-claim.path tradeai-release-train-claim.timer; do
    [[ "$(systemctl --user is-enabled "$u" 2>/dev/null || true)" == enabled ]] || { echo NOT_ENABLED; return; }
    [[ "$(systemctl --user is-active "$u" 2>/dev/null || true)" == active ]] || { echo NOT_ACTIVE; return; }
  done
  echo ENABLED
}

d_preflight() {
  require_train_code
  local u
  for u in "${UNITS[@]}"; do
    [[ -f "$CODE_ROOT/$UNIT_SRC_REL/$u.proposed" ]] || refuse "missing $UNIT_SRC_REL/$u.proposed under $CODE_ROOT"
  done
  [[ -x "$CODE_ROOT/.venv/bin/python" ]] || refuse "the unit's ExecStart interpreter $CODE_ROOT/.venv/bin/python is missing"
  [[ "$STATE_DIR" == "$UNIT_STATE_DIR" ]] \
    || refuse "state dir mismatch: the runner resolves $STATE_DIR ($STATE_DIR_SOURCE) but the .path unit watches $UNIT_STATE_DIR/train_requests/pending (step G; never auto-remediated)"
  # Finding 7: the superseded 12:00/17:30 release_window timer must never run beside the train (two release paths).
  local old
  for old in tradeai-release-window.timer tradeai-release-window.service; do
    if [[ -e "$UNIT_DIR/$old" ]] || [[ "$(systemctl --user is-enabled "$old" 2>/dev/null || true)" == enabled ]]; then
      refuse "the superseded $old (12:00/17:30 release_window run) is installed; archive it first: TRADEAI_OPERATOR_INSTALL=1 bash $UNIT_SRC_REL/install_release_window_timer.sh --disable (never both release paths)"
    fi
  done
}

step_D() {
  local fs en
  case "$MODE" in
    dry)
      d_preflight
      fs="$(d_files_state)"; en="$(d_enabled)"
      say "  units in $UNIT_DIR: $fs; path+timer: $en"
      say "  claimer dry run (read-only: lists pending requests, claims nothing):"
      ( cd "$CODE_ROOT" && "$PY" scripts/release_window.py train-claim ) 2>&1 | sed 's/^/    /' | head -20
      case "$fs" in
        DIFFERS:*|PARTIAL) say "  WOULD REFUSE: an installed unit differs from the reviewed .proposed file; archive it first" ;;
        *) say "  WOULD: install -d -m 700 $STATE_DIR/train_requests/pending"
           for u in "${UNITS[@]}"; do say "  WOULD: install -m 0644 $UNIT_SRC_REL/$u.proposed $UNIT_DIR/$u"; done
           say "  WOULD: systemctl --user daemon-reload"
           say "  WOULD: systemctl --user enable --now tradeai-release-train-claim.path tradeai-release-train-claim.timer" ;;
      esac
      ;;
    verify)
      fs="$(d_files_state)"; en="$(d_enabled)"
      say "  units: $fs; path+timer: $en"
      systemctl --user list-timers tradeai-release-train-claim.timer --no-pager 2>/dev/null | sed 's/^/  /' | head -4 || true
      [[ "$fs" == SAME && "$en" == ENABLED ]] || exit 1
      ;;
    apply)
      need_ack D
      d_preflight
      fs="$(d_files_state)"; en="$(d_enabled)"
      if [[ "$fs" == SAME && "$en" == ENABLED ]]; then receipt D NOOP "installed + enabled"; say "NOOP: claimer units installed and enabled"; return 0; fi
      case "$fs" in DIFFERS:*|PARTIAL) receipt D REFUSED "$fs"; refuse "installed units differ from the reviewed files ($fs); archive them (rollback D) first" ;; esac
      ( cd "$CODE_ROOT" && "$PY" scripts/release_window.py train-claim >/dev/null ) \
        || { receipt D REFUSED "claimer dry run failed"; refuse "release_window.py train-claim (dry run) failed"; }
      install -d -m 700 "$STATE_DIR" "$STATE_DIR/train_requests" "$STATE_DIR/train_requests/pending"
      install -d -m 755 "$UNIT_DIR"
      if [[ "$fs" == ABSENT ]]; then
        for u in "${UNITS[@]}"; do install -m 0644 "$CODE_ROOT/$UNIT_SRC_REL/$u.proposed" "$UNIT_DIR/$u"; done
      fi
      systemctl --user daemon-reload
      systemctl --user enable --now tradeai-release-train-claim.path tradeai-release-train-claim.timer
      fs="$(d_files_state)"; en="$(d_enabled)"
      [[ "$fs" == SAME && "$en" == ENABLED ]] || { receipt D FAILED "$fs $en"; echo "FAILED: units $fs, $en; rollback D"; exit 1; }
      receipt D APPLIED "3 units installed; path + timer enabled --now"
      say "APPLIED: claimer units installed; path + timer enabled and active"
      ;;
  esac
}

# ══ E: relay live list ═════════════════════════════════════════════════════════════════════════════════
e_current() {   # the lane names on the TRADEAI_N8N_RELAY_LIVE_LANES= line only (nothing else is read out)
  [[ -f "$LIVE_ENV" ]] || { echo ""; return; }
  "$PY" - "$LIVE_ENV" <<'PYEOF'
import re, sys
names = []
for line in open(sys.argv[1], encoding="utf-8"):
    if line.startswith("TRADEAI_N8N_RELAY_LIVE_LANES="):
        val = line.split("=", 1)[1].strip().strip("'\"")
        names = [n for n in re.split(r"[,\s]+", val) if n]
print(" ".join(names))
PYEOF
}

e_missing() {
  local cur; cur=" $(e_current) "
  local l out=()
  for l in "${LANES[@]}"; do [[ "$cur" == *" $l "* ]] || out+=("$l"); done
  echo "${out[*]:-}"
}

e_relay_check() {   # run check_n8n_relay_contract.py for the release-train workflow
  local probe_args=()
  [[ "$1" == probe && "$RELAY_PROBE" == 1 ]] || probe_args=(--no-probe)
  ( cd "$CODE_ROOT" && "$PY" scripts/check_n8n_relay_contract.py --relay-root "$CODE_ROOT" \
      --workflows "$CODE_ROOT/docs/implementation/n8n-maturity/workflows/fabric" --ids "$WF_ID" "${probe_args[@]}" )
}

e_preflight_warn() {
  code_has scripts/n8n_run_relay.py "release-train-window" \
    || refuse "$CODE_ROOT/scripts/n8n_run_relay.py serves no /release-train-window (release Release 2 first)"
  ( cd "$CODE_ROOT" && "$PY" - "${LANES[@]}" <<'PYEOF'
import json, sys
a = json.load(open("config/n8n_run_allowlist.json"))
rows = {r.get("lane_id"): r for r in (a.get("lanes") if isinstance(a, dict) else a) if isinstance(r, dict)}
for lane in sys.argv[1:]:
    r = rows.get(lane)
    if r is None:
        print(f"  REFUSE: {lane} has no allowlist row in the served release"); sys.exit(2)
    if r.get("live_arg") is None:
        print(f"  WARN: {lane} live_arg is null in the served release: live-listed, it still runs --dry-run "
              "(PR H.0 sets live_arg and stage canary)")
PYEOF
  ) || refuse "a lane is not allowlisted in $CODE_ROOT"
}

e_restart_needed() {   # 1 when the env file is newer than either service's last start
  [[ -f "$LIVE_ENV" ]] || { echo 0; return; }
  local m s u
  m="$(stat -c '%Y' "$LIVE_ENV")"
  for u in tradeai-n8n-run-relay.service tradeai-n8n-coordination-gateway.service; do
    s="$(systemctl --user show "$u" -p ActiveEnterTimestamp --value 2>/dev/null || true)"
    s="$(date -d "$s" +%s 2>/dev/null || echo 0)"
    [[ "$s" -ge "$m" ]] || { echo 1; return; }
  done
  echo 0
}

step_E() {
  local miss
  case "$MODE" in
    dry)
      e_preflight_warn
      miss="$(e_missing)"
      say "  live list $LIVE_ENV: $( [[ -f $LIVE_ENV ]] && echo present || echo absent ); missing: ${miss:-none}"
      if [[ -n "$miss" ]]; then
        say "  WOULD: cp -p $LIVE_ENV $LIVE_ENV.bak-<stamp>-release-train-arm (archive; never deleted)"
        say "  WOULD: rewrite ONLY the TRADEAI_N8N_RELAY_LIVE_LANES= line, adding: $miss (mode 600, tmp + rename); read back"
        say "  WOULD: systemctl --user restart tradeai-n8n-run-relay.service tradeai-n8n-coordination-gateway.service; is-active both"
      else
        say "  WOULD: NOOP (all 5 lanes listed)$( [[ "$(e_restart_needed)" == 1 ]] && echo '; restart relay + gateway (env file newer than a service start)' )"
      fi
      say "  WOULD: check_n8n_relay_contract.py --ids $WF_ID (scratch relay probe; never the live relay). Static pass now:"
      e_relay_check static 2>&1 | tail -1 | sed 's/^/    /'
      ;;
    verify)
      miss="$(e_missing)"; say "  missing lanes: ${miss:-none}; restart pending: $(e_restart_needed)"
      local u; for u in tradeai-n8n-run-relay.service tradeai-n8n-coordination-gateway.service; do
        say "  $u: $(systemctl --user is-active "$u" 2>/dev/null || true)"; done
      [[ -z "$miss" && "$(e_restart_needed)" == 0 ]] || exit 1
      e_relay_check static >/dev/null || exit 1
      ;;
    apply)
      need_ack E
      [[ -n "${TRADEAI_CONFIG_WRITE_GRANT:-}" ]] || { receipt E REFUSED "no grant"; refuse "set TRADEAI_CONFIG_WRITE_GRANT=<config-write grant id naming n8n-live-lanes.env>"; }
      e_preflight_warn >/dev/null
      miss="$(e_missing)"
      if [[ -z "$miss" && "$(e_restart_needed)" == 0 ]]; then receipt E NOOP "listed; services current"; say "NOOP: all 5 lanes listed and both services started after the last edit"; return 0; fi
      if [[ -n "$miss" ]]; then
        install -d -m 700 "$(dirname "$LIVE_ENV")"
        [[ -f "$LIVE_ENV" ]] && cp -p "$LIVE_ENV" "$LIVE_ENV.bak-$(stamp)-release-train-arm"
        "$PY" - "$LIVE_ENV" "${LANES[@]}" <<'PYEOF'
import os, re, sys
path, add = sys.argv[1], sys.argv[2:]
lines = open(path, encoding="utf-8").read().splitlines(keepends=True) if os.path.exists(path) else []
key = "TRADEAI_N8N_RELAY_LIVE_LANES="
cur, idx = [], None
for i, line in enumerate(lines):
    if line.startswith(key):
        idx = i
        cur = [n for n in re.split(r"[,\s]+", line.split("=", 1)[1].strip().strip("'\"")) if n]
new = cur + [l for l in add if l not in cur]
out = key + " ".join(new) + "\n"
if idx is None:
    lines.append(out)
else:
    lines[idx] = out
tmp = path + ".tmp-rtarm"
fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
with os.fdopen(fd, "w", encoding="utf-8") as f:
    f.write("".join(lines)); f.flush(); os.fsync(f.fileno())
os.replace(tmp, path)
PYEOF
        miss="$(e_missing)"
        [[ -z "$miss" ]] || { receipt E FAILED "read-back missing $miss"; echo "FAILED: read-back missing $miss; restore the .bak file"; exit 1; }
      fi
      systemctl --user restart tradeai-n8n-run-relay.service tradeai-n8n-coordination-gateway.service
      local u; for u in tradeai-n8n-run-relay.service tradeai-n8n-coordination-gateway.service; do
        [[ "$(systemctl --user is-active "$u" 2>/dev/null || true)" == active ]] \
          || { receipt E FAILED "$u not active"; echo "FAILED: $u not active after restart; rollback E"; exit 1; }
      done
      if ! e_relay_check probe; then receipt E FAILED "relay contract check"; echo "FAILED: check_n8n_relay_contract.py refused; rollback E"; exit 1; fi
      receipt E APPLIED "lanes listed; relay + gateway restarted; relay contract PASS"
      say "APPLIED: 5 lanes on the relay live list; relay + gateway restarted; relay contract PASS"
      ;;
  esac
}

# ══ F: n8n workflow import + publish ═══════════════════════════════════════════════════════════════════
N8N_DB=(docker exec m8m-n8n-db psql -U n8n -d n8n -tA)
N8N_CLI=(docker exec -e N8N_RUNNERS_BROKER_PORT=5690 m8m-n8n n8n)

f_row() {   # ABSENT | INACTIVE | ACTIVE | ARCHIVED
  local r
  r="$("${N8N_DB[@]}" -c "SELECT active::text||'|'||coalesce(\"activeVersionId\",'NULL')||'|'||\"isArchived\"::text FROM workflow_entity WHERE id='$1'" 2>/dev/null | tr -d '[:space:]')"
  case "$r" in
    "") echo ABSENT ;; *"|true") echo ARCHIVED ;; true\|*) [[ "$r" == *"|NULL|"* ]] && echo INACTIVE || echo ACTIVE ;;
    *) echo INACTIVE ;;
  esac
}

f_gate() {
  if [[ "$IMPORT_GATE" == "stub-pass" ]]; then echo "  import gate: STUB PASS (sandbox only)"; return 0; fi
  # The packet pattern (comms-intent-consumer-live, hermes-*-cutover): the activation gate, with the host-signed
  # runtime evidence (N8nFrameworkRuntimeEvidence@v2) when the operator supplies it. Never an exception file.
  local ev=()
  [[ -n "${N8N_FRAMEWORK_RUNTIME_EVIDENCE:-}" ]] && ev=(--runtime-evidence "$N8N_FRAMEWORK_RUNTIME_EVIDENCE")
  ( cd "$CODE_ROOT" && "$PY" scripts/check_n8n_import_ready.py "$CODE_ROOT/$WF_REL" --relay-url "$RELAY_URL" \
      --known-id "$ERROR_WF_ID" --framework-gate activation "${ev[@]}" ) 2>&1 | sed 's/^/  /' | tail -3
  return "${PIPESTATUS[0]}"
}

f_pending() {   # what the §23.24 gate still needs, from the committed pending-evidence record (finding 2)
  "$PY" -c 'import json,sys; d=json.load(open(sys.argv[1])); print("platform blocking %s; runtime obligations pending %d (%s)" % (",".join(sorted(d["platform_blocking"])) or "none", len(d["runtime_pending"]), sys.argv[1].split("/docs/",1)[-1]))' \
    "$CODE_ROOT/$PENDING_REL" 2>/dev/null || echo "pending-evidence record unavailable"
}

f_quiet_now() {   # refuse an n8n restart within 10 min of any release-train tick (ET)
  local hm="${NOW_HM:-$(TZ=America/New_York date +%H%M)}"
  local m=$((10#${hm:0:2} * 60 + 10#${hm:2:2})) t
  for t in 1630 1800 1915 2230 0000 0115 0430 0600 0715 0630 0800 0915; do
    local tm=$((10#${t:0:2} * 60 + 10#${t:2:2}))
    local d=$(( m > tm ? m - tm : tm - m )); (( d > 720 )) && d=$((1440 - d))
    (( d > 10 )) || { echo "$t"; return; }
  done
  echo ""
}

step_F() {
  [[ -f "$CODE_ROOT/$WF_REL" ]] || refuse "no $WF_REL under $CODE_ROOT (release Release 2 first)"
  local row gate_rc
  case "$MODE" in
    dry)
      row="$(f_row "$WF_ID")"; say "  n8n row $WF_ID: $row; error workflow $ERROR_WF_ID: $(f_row "$ERROR_WF_ID")"
      say "  runtime evidence: ${N8N_FRAMEWORK_RUNTIME_EVIDENCE:-NOT SUPPLIED (N8N_FRAMEWORK_RUNTIME_EVIDENCE)}; $(f_pending)"
      set +e; f_gate; gate_rc=$?; set -e
      [[ $gate_rc == 0 ]] || say "  WOULD REFUSE --apply: the mandatory import gate (AGENTS §23.24, check_n8n_import_ready.py) refuses this workflow"
      say "  graph check: $( ( cd "$CODE_ROOT" && "$PY" scripts/n8n_workflow_templates.py build-fabric --verify "$CODE_ROOT/$WF_REL" ) 2>/dev/null | "$PY" -c 'import json,sys; d=json.load(sys.stdin); print("ok" if d.get("ok") else "MISMATCH", d["workflows"][0]["graph_sha256"][:12])' 2>/dev/null || echo unavailable)"
      case "$row" in
        ABSENT) say "  WOULD: docker cp <stage>/in -> m8m-n8n; n8n import:workflow --separate (INACTIVE); export + build-fabric --verify (graph hash)" ;&
        INACTIVE) say "  WOULD: n8n publish:workflow --id=$WF_ID; docker restart m8m-n8n (not within 10 min of a train tick); verify active + activeVersionId" ;;
        ACTIVE) say "  WOULD: NOOP (already active)" ;;
        ARCHIVED) say "  WOULD REFUSE: the row is archived; un-archive is an operator decision" ;;
      esac
      ;;
    verify)
      row="$(f_row "$WF_ID")"; say "  n8n row $WF_ID: $row"
      [[ "$row" == ACTIVE ]] || exit 1
      ;;
    apply)
      need_ack F
      [[ -n "${TRADEAI_FABRIC_GRANT:-}" ]] || { receipt F REFUSED "no grant"; refuse "set TRADEAI_FABRIC_GRANT=<cron grant id naming $WF_ID> (AGENTS §23.2)"; }
      row="$(f_row "$WF_ID")"
      if [[ "$row" == ACTIVE ]]; then receipt F NOOP "already active"; say "NOOP: $WF_ID already active"; return 0; fi
      [[ "$row" != ARCHIVED ]] || { receipt F REFUSED "archived"; refuse "$WF_ID is archived in n8n"; }
      [[ "$(f_row "$ERROR_WF_ID")" == ACTIVE ]] || { receipt F REFUSED "error workflow not active"; refuse "$ERROR_WF_ID (settings.errorWorkflow) is not active"; }
      if [[ "$IMPORT_GATE" != "stub-pass" && ! -f "${N8N_FRAMEWORK_RUNTIME_EVIDENCE:-}" ]]; then
        receipt F REFUSED "framework evidence unavailable"
        refuse "framework evidence unavailable (AGENTS §23.24): set N8N_FRAMEWORK_RUNTIME_EVIDENCE to the host-signed N8nFrameworkRuntimeEvidence@v2 file ($(f_pending)); not routed around"
      fi
      set +e; f_gate >/dev/null; gate_rc=$?; set -e
      [[ $gate_rc == 0 ]] || { receipt F REFUSED "import gate §23.24 refused"; refuse "check_n8n_import_ready.py refuses $WF_ID (AGENTS §23.24 activation bar); not routed around"; }
      local busy; busy="$(f_quiet_now)"
      [[ -z "$busy" ]] || { receipt F REFUSED "inside tick $busy"; refuse "within 10 min of the $busy ET release-train tick; n8n restarts there are refused"; }
      local st; st="$(stamp)"
      local stage="$ARM_DIR/wf-stage-$st" cstage="/tmp/tradeai-rtarm-wf-$st"
      install -d -m 700 "$stage/in" "$stage/out"
      cp "$CODE_ROOT/$WF_REL" "$stage/in/"
      if [[ "$row" == ABSENT ]]; then
        docker exec m8m-n8n mkdir -p "$cstage/in" "$cstage/out"
        docker cp "$stage/in/." "m8m-n8n:$cstage/in/"
        "${N8N_CLI[@]}" import:workflow --separate --input="$cstage/in/"
        [[ "$(f_row "$WF_ID")" == INACTIVE ]] || { receipt F FAILED "post-import state"; echo "FAILED: post-import state wrong; rollback F"; exit 1; }
        "${N8N_CLI[@]}" export:workflow --id="$WF_ID" --output="$cstage/out/$WF_ID.json"
        docker cp "m8m-n8n:$cstage/out/$WF_ID.json" "$stage/out/$WF_ID.json"
        ( cd "$CODE_ROOT" && "$PY" scripts/n8n_workflow_templates.py build-fabric --verify "$stage/out/$WF_ID.json" >/dev/null ) \
          || { receipt F FAILED "graph mismatch"; echo "FAILED: n8n holds a graph that is not the reviewed one; rollback F"; exit 1; }
      fi
      "${N8N_CLI[@]}" publish:workflow --id="$WF_ID"
      docker restart m8m-n8n >/dev/null
      local i; for i in 1 2 3 4 5 6; do [[ "$(f_row "$WF_ID")" == ACTIVE ]] && break; sleep "${RTARM_SLEEP:-5}"; done
      [[ "$(f_row "$WF_ID")" == ACTIVE ]] || { receipt F FAILED "publish did not take"; echo "FAILED: publish did not take; rollback F"; exit 1; }
      receipt F APPLIED "imported (graph verified) + published; stage $stage"
      say "APPLIED: $WF_ID imported (graph verified) and published; stage kept at $stage"
      ;;
  esac
}

# ══ G: state-dir comparison (read-only in every mode) ══════════════════════════════════════════════════
g_cc_get() {   # g_cc_get <path>
  if [[ "$USE_CC_CURL" == 1 ]]; then bash "$CODE_ROOT/scripts/cc_curl.sh" -s --max-time 10 "$CC_BASE$1"
  else curl -s --max-time 10 "$CC_BASE$1"; fi
}

g_unit_env() {   # g_unit_env <unit> -> STATE_ROOT/STATE_DIR from inline Environment= only (no env files read)
  systemctl --user show "$1" -p Environment --value 2>/dev/null | tr ' ' '\n' \
    | grep -E '^(TRADEAI_STATE_ROOT|TRADEAI_RELEASE_WINDOW_STATE_DIR)=' || true
}

step_G() {
  require_train_code
  local summary stop
  summary="$(g_cc_get /api/v2/coordination/release-train || true)"
  stop="$(g_cc_get /api/v2/coordination/release-train/stop || true)"
  local claimer_env gw_env
  claimer_env="$(g_unit_env tradeai-release-train-claim.service)"
  gw_env="$(g_unit_env tradeai-n8n-coordination-gateway.service)"
  local runner_dir runner_status runner_json cli_dir
  # The runner as the claimer unit runs it: the unit's inline env only (the .proposed unit sets none).
  # release_window.py status prints state_dir + state_dir_source (finding 4, fixed); a served release that predates the
  # fix lacks them, and then the directory falls back to release_window.STATE_DIR read directly (labelled as such).
  runner_json="$(cd "$CODE_ROOT" && env -u TRADEAI_STATE_ROOT -u TRADEAI_RELEASE_WINDOW_STATE_DIR $claimer_env \
                 "$PY" scripts/release_window.py status 2>/dev/null || true)"
  runner_status="$(printf '%s' "$runner_json" | "$PY" -c 'import json,sys; print(json.load(sys.stdin).get("latch_state"))' 2>/dev/null || echo UNAVAILABLE)"
  runner_dir="$(printf '%s' "$runner_json" | "$PY" -c 'import json,sys; d=json.load(sys.stdin); print(d["state_dir"] + " [" + d["state_dir_source"] + "]")' 2>/dev/null || true)"
  if [[ -z "$runner_dir" ]]; then
    runner_dir="$(cd "$CODE_ROOT" && env -u TRADEAI_STATE_ROOT -u TRADEAI_RELEASE_WINDOW_STATE_DIR $claimer_env \
                  "$PY" -c 'from scripts import release_window as RW; print(RW.STATE_DIR)' 2>/dev/null || echo UNAVAILABLE)"
    [[ "$runner_dir" == UNAVAILABLE ]] || runner_dir="$runner_dir [release_window.STATE_DIR; status has no state_dir]"
  fi
  cli_dir="$(cd "$CODE_ROOT" && env -u TRADEAI_STATE_ROOT -u TRADEAI_RELEASE_WINDOW_STATE_DIR $claimer_env \
             "$PY" scripts/release_control_cli.py status 2>/dev/null | "$PY" -c 'import json,sys; print(json.load(sys.stdin)["state_dir"])' 2>/dev/null || echo UNAVAILABLE)"
  local gw_dir
  gw_dir="$(env -i HOME="$HOME" $gw_env bash -c 'echo "${TRADEAI_RELEASE_WINDOW_STATE_DIR:-${TRADEAI_STATE_ROOT:-$HOME/trade-ai-releases/persistent-state}/data/runtime/release_window}"')"
  local path_dir="UNAVAILABLE"
  if [[ -f "$UNIT_DIR/tradeai-release-train-claim.path" ]]; then
    path_dir="$(sed -n 's/^PathChanged=//p' "$UNIT_DIR/tradeai-release-train-claim.path" | sed "s#%h#$HOME#; s#/train_requests/pending\$##")"
  else
    path_dir="$(sed -n 's/^PathChanged=//p' "$CODE_ROOT/$UNIT_SRC_REL/tradeai-release-train-claim.path.proposed" | sed "s#%h#$HOME#; s#/train_requests/pending\$##") (proposed; not installed)"
  fi
  local rc=0
  RTARM_G_SUMMARY="$summary" RTARM_G_STOP="$stop" RTARM_G_RUNNER="$runner_dir" RTARM_G_RSTATUS="$runner_status" \
  RTARM_G_CLI="$cli_dir" RTARM_G_GW="$gw_dir" RTARM_G_PATH="$path_dir" "$PY" - <<'PYEOF' || rc=$?
import json, os, sys
def j(name):
    try:
        return json.loads(os.environ.get(name) or "")
    except ValueError:
        return None
s, st = j("RTARM_G_SUMMARY"), j("RTARM_G_STOP")
cc_sum = ((((s or {}).get("data") or {}).get("state_dir") or {}).get("value") or {})
cc_stop = ((st or {}).get("data") or {})
rows = [
    ("CC summary state_dir", cc_sum.get("path") or "UNAVAILABLE", cc_sum.get("source")),
    ("CC GET /stop state_dir", cc_stop.get("state_dir") or "UNAVAILABLE", None),
    ("release_window.py status state_dir (claimer env)", os.environ["RTARM_G_RUNNER"].split(" [", 1)[0],
     os.environ["RTARM_G_RUNNER"].split(" [", 1)[1].rstrip("]") if " [" in os.environ["RTARM_G_RUNNER"] else None),
    ("release_control_cli.py status state_dir", os.environ["RTARM_G_CLI"], None),
    ("gateway (inline env) state dir", os.environ["RTARM_G_GW"], None),
    ("claimer .path unit watch dir", os.environ["RTARM_G_PATH"].replace(" (proposed; not installed)", ""), None),
]
for label, val, src in rows:
    print(f"  {label:48s} {val}" + (f"  [{src}]" if src else ""))
latch_cc = ((cc_stop.get("latch") or {}).get("status")) or "UNAVAILABLE"
print(f"  {'latch: CC /stop vs release_window.py status':48s} {latch_cc} vs {os.environ['RTARM_G_RSTATUS']}")
vals = {v for _, v, _ in rows}
ok = len(vals) == 1 and "UNAVAILABLE" not in vals and latch_cc == os.environ["RTARM_G_RSTATUS"]
print("  verdict: " + ("MATCH" if ok else "MISMATCH or UNAVAILABLE: report both paths, hashes and timestamps to the "
                       "operator; never auto-remediate (AGENTS §0 rule 5)"))
sys.exit(0 if ok else 1)
PYEOF
  if [[ "$MODE" == apply ]]; then receipt G "$([[ $rc == 0 ]] && echo MATCH || echo MISMATCH)" "read-only comparison"; fi
  [[ "$MODE" == dry ]] && return 0
  return $rc
}

# ── status / plan ──────────────────────────────────────────────────────────────────────────────────────
status_all() {
  say "release train arming status (read-only) — code root $CODE_ROOT -> $(readlink -f "$CODE_ROOT" 2>/dev/null || echo '?')"
  say "  state dir $STATE_DIR ($STATE_DIR_SOURCE)"
  if [[ -n "${RTARM_PSQL_ARGS:-}" ]]; then say "  A store: $(a_state 2>/dev/null || echo UNAVAILABLE)"; else say "  A store: (set RTARM_PSQL_ARGS to probe)"; fi
  say "  B capability key: $(b_state)"
  if [[ -e "$DELEG_PATH" ]]; then say "  C delegation: $(c_verdict 2>/dev/null || echo UNREADABLE)"; else say "  C delegation: MISSING"; fi
  say "  D claimer units: $(d_files_state); $(d_enabled)"
  local m; m="$(e_missing)"; say "  E live list missing: ${m:-none}"
  say "  F n8n $WF_ID: $(f_row "$WF_ID")"
  if [[ -f "$RECEIPTS" ]]; then say "  receipts: $(wc -l < "$RECEIPTS") rows in $RECEIPTS"; else say "  receipts: none"; fi
}

case "$CMD" in plan|status) ;; *) [[ -n "$(step_letter "$CMD")" ]] || die_usage ;; esac
identity_check

case "$CMD" in
  plan)
    [[ "$MODE" == dry ]] || die_usage
    say "== release train arming PLAN (dry run; nothing is written) $(date -u +%FT%TZ)"
    say "   user $(id -un) host $(hostname -s); code root $CODE_ROOT; state dir $STATE_DIR ($STATE_DIR_SOURCE)"
    for L in A B C D E F G; do
      say "== $L"
      ( "step_$L" ) || say "  ($L dry run stopped: see the refusal above)"
    done
    ;;
  status) status_all ;;
  *)
    L="$(step_letter "$CMD")"
    [[ -n "$L" ]] || die_usage
    say "== $L ($MODE)"
    "step_$L"
    ;;
esac
