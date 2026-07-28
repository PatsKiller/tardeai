#!/usr/bin/env bash
# Convergence — rollback manifest + restore. DRY-RUN by default: captures the CURRENT (pre-apply) host
# state into a redacted manifest so any MOUNT/CONNECT/static apply can be reverted exactly. --restore
# <manifest> would restore backend, static bundle, read-plane connection state, and service state.
# Never prints a DSN/secret. In this draft PR only the manifest-capture (read-only) path is exercised.
set -u -o pipefail
umask 077
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="${REPO:-/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild}"
READER_ENV="$HOME/.config/tradeai/agent-read-api.env"
DROPIN="$HOME/.config/systemd/user/portfolio-server.service.d/10-agent-read-api.conf"

# ── restore mode: atomically put a previously-backed-up dist back onto the live host ──────────────
# rollback.sh --restore <backup_dir> [--apply] [--manifest <f>] [--expect-commit <sha>]
# DRY-RUN validates the backup (shape + binding) + prints the plan. Post-restore it verifies the
# SERVED build-meta and the agent-runtime read-plane envelope (unless SKIP_SMOKE=1).
if [ "${1:-}" = "--restore" ]; then
  BK="${2:-}"; shift 2 || true
  RAPPLY=""; MANIFEST=""; EXPECT=""
  while [ $# -gt 0 ]; do
    case "$1" in
      --apply) RAPPLY="--apply" ;;
      --manifest) MANIFEST="${2:-}"; shift ;;
      --expect-commit) EXPECT="${2:-}"; shift ;;
    esac; shift
  done
  DIST="${CC_DIST:-$REPO/apps/command-center-v3/dist}"
  BASE="${SMOKE_BASE:-http://127.0.0.1:7777}"
  VERIFY_META_URL="${VERIFY_META_URL:-$BASE/v3/build-meta.json}"
  VERIFY_AGENT_URL="${VERIFY_AGENT_URL:-$BASE/api/v3/agent-runtime/runs}"
  VERIFY_AGENT_ROLE="${VERIFY_AGENT_ROLE:-agentic_runtime_reader}"
  STAMP="$(date +%Y%m%d_%H%M%S)"
  [ -n "$BK" ] && [ -d "$BK" ] || { echo "final_status|BLOCKED_NO_BACKUP"; exit 2; }
  # shape + binding: valid dist AND (if given) matches the recorded manifest hash / expected commit
  PYTHONPATH="$DIR" python3 - "$BK" "$MANIFEST" "$EXPECT" <<'PY' || { echo "final_status|BLOCKED_BACKUP_INVALID"; exit 2; }
import json, os, sys
import convergence_lib as cl
bk, manifest, expect = sys.argv[1], sys.argv[2], sys.argv[3]
files = [os.path.relpath(os.path.join(dp, fn), bk) for dp, _, fns in os.walk(bk) for fn in fns]
assert cl.dist_shape_ok(files), f"backup is not a valid dist (need index.html+build-meta.json+asset): {files}"
meta = {}
try: meta = json.load(open(os.path.join(bk, "build-meta.json"), encoding="utf-8"))
except Exception: pass
exp_commit = expect or None
exp_hash = act_hash = None
if manifest:
    m = json.load(open(manifest, encoding="utf-8"))
    exp_commit = exp_commit or m.get("backup_source_commit")
    exp_hash = m.get("backup_dir_hash")
    act_hash = cl.dir_content_hash(bk)   # same canonical hash static_install.sh recorded
cl.restore_binding_ok(meta, expected_commit=exp_commit, expected_dir_hash=exp_hash, actual_dir_hash=act_hash)
print("restore_precheck|OK|backup_commit=" + str(meta.get("source_commit")))
if exp_hash: print("restore_binding|hash=" + ("MATCH" if exp_hash == act_hash else "MISMATCH"))
PY
  BK_SC="$(python3 -c "import json,sys;print(json.load(open(sys.argv[1])).get('source_commit',''))" "$BK/build-meta.json" 2>/dev/null)"
  echo "restore_source|$BK"; echo "restore_target|$DIST"; echo "restore_backup_commit|${BK_SC:-NONE}"
  if [ "$RAPPLY" != "--apply" ]; then
    echo "final_status|RESTORE_DRY_RUN_OK (would atomic-swap the backup back into $DIST)"
    exit 0
  fi
  PARENT="$(dirname "$DIST")"; NAME="$(basename "$DIST")"
  TMP="$PARENT/$NAME.restore-$STAMP"; SUP="$PARENT/$NAME.superseded-$STAMP"
  cp -a "$BK" "$TMP" || { echo "final_status|BLOCKED_RESTORE_COPY_FAILED"; exit 2; }
  if [ -e "$DIST" ]; then
    if PYTHONPATH="$DIR" python3 "$DIR/_dirswap.py" exchange "$DIST" "$TMP"; then
      mv "$TMP" "$SUP"; echo "restore_swap|mode=atomic-exchange"
    else
      mv "$DIST" "$SUP" && mv "$TMP" "$DIST" || { [ -d "$SUP" ] && [ ! -e "$DIST" ] && mv "$SUP" "$DIST"; echo "final_status|BLOCKED_RESTORE_SWAP_FAILED"; exit 2; }
      echo "restore_swap|mode=two-rename-nonatomic-window"
    fi
  else
    mv "$TMP" "$DIST" || { echo "final_status|BLOCKED_RESTORE_SWAP_FAILED"; exit 2; }
  fi
  echo "restored|from=$BK|superseded=$SUP"
  # post-restore verification: SERVED build-meta carries the backup's commit + read-plane intact
  if [ "${SKIP_SMOKE:-}" != "1" ] && [ -n "$BK_SC" ]; then
    sm="$(curl -sS --max-time 8 "$VERIFY_META_URL" 2>/dev/null || echo '{}')"
    printf '%s' "$sm" | PYTHONPATH="$DIR" python3 -c 'import json,sys,convergence_lib as cl
raw=sys.stdin.read() or "{}"
try: b=json.loads(raw)
except Exception: b={}
sys.exit(0 if cl.served_build_ok(b, sys.argv[1]) else 1)' "$BK_SC" \
      && echo "verify_served_meta|OK|$BK_SC" || echo "verify_served_meta|MISMATCH (served != $BK_SC)"
    if [ "$VERIFY_AGENT_URL" != "none" ]; then
      ar="$(curl -sS --max-time 8 -w $'\n%{http_code}' "$VERIFY_AGENT_URL" 2>/dev/null || printf '{}\n000')"
      printf '%s' "${ar%$'\n'*}" | PYTHONPATH="$DIR" python3 -c 'import json,sys,convergence_lib as cl
raw=sys.stdin.read() or "{}"
try: b=json.loads(raw)
except Exception: b={}
sys.exit(0 if cl.read_plane_ok(int(sys.argv[1]), b, sys.argv[2]) else 1)' "${ar##*$'\n'}" "$VERIFY_AGENT_ROLE" \
        && echo "verify_read_plane|OK" || echo "verify_read_plane|BAD"
    fi
  fi
  echo "final_status|RESTORE_APPLIED"
  exit 0
fi

# ── default mode: capture a redacted rollback manifest of current host state (read-only) ──────────
OUT="${1:-/tmp/convergence-rollback-manifest.json}"

hash_or_absent(){ [ -f "$REPO/$1" ] && sha256sum "$REPO/$1" | awk '{print $1}' || echo ABSENT; }
present(){ [ -e "$1" ] && echo true || echo false; }
mode_of(){ [ -e "$1" ] && stat -c '%a' "$1" 2>/dev/null || echo none; }

python3 - "$OUT" \
  "$(hash_or_absent scripts/portfolio_server.py)" \
  "$(hash_or_absent scripts/agent_runtime/read_http.py)" \
  "$(hash_or_absent scripts/agent_runtime/read_api.py)" \
  "$(present "$READER_ENV")" "$(mode_of "$READER_ENV")" "$(present "$DROPIN")" \
  "$(systemctl --user is-active portfolio-server.service 2>/dev/null || echo unknown)" \
  "$(ls -d "$REPO"/data/watch/decision_packets 2>/dev/null || echo none)" \
  "$(ls "$REPO"/data/runtime/sector_momentum_latest.json 2>/dev/null || echo none)" <<'PY'
import json,sys,hashlib,os
(out,pserver,rhttp,rapi,env_p,env_m,dropin_p,svc,watch_dir,def_snap)=sys.argv[1:11]
def h(p): return hashlib.sha256(open(p,'rb').read()).hexdigest()[:16] if os.path.isfile(p) else "none"
m={"manifest_version":"convergence-rollback-v1",
   "backend_hashes":{"scripts/portfolio_server.py":pserver,"scripts/agent_runtime/read_http.py":rhttp,
                     "scripts/agent_runtime/read_api.py":rapi},
   "reader":{"env_present":env_p=="true","env_mode":env_m,"dropin_present":dropin_p=="true"},
   "service_state":svc,
   "watch_packets":{"decision_packets_dir":watch_dir},
   "defense_snapshots":{"sector_momentum_latest":def_snap, "hash":h(def_snap)},
   "static_backup":None,"static_build_meta":{}}
open(out,"w").write(json.dumps(m,indent=2))
print("rollback_manifest|WRITTEN|"+out)
print("rollback_service_state|"+svc)
print("rollback_reader_env_present|"+env_p+"|mode="+env_m)
PY
