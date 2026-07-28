#!/usr/bin/env bash
# Convergence — rollback manifest + restore. DRY-RUN by default: captures the CURRENT (pre-apply) host
# state into a redacted manifest so any MOUNT/CONNECT/static apply can be reverted exactly. --restore
# <manifest> would restore backend, static bundle, read-plane connection state, and service state.
# Never prints a DSN/secret. In this draft PR only the manifest-capture (read-only) path is exercised.
set -u -o pipefail
umask 077
REPO="/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild"
READER_ENV="$HOME/.config/tradeai/agent-read-api.env"
DROPIN="$HOME/.config/systemd/user/portfolio-server.service.d/10-agent-read-api.conf"
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
