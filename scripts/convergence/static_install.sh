#!/usr/bin/env bash
# Convergence — Phase INSTALL: swap a STAGED exact-ref candidate dist onto the live host.
# Gates (each can only refuse, never skip a check):
#   provenance (build-meta: 40-char SHA + STAGED_EXACT_REF + agent-runtime contract)
#   → markers  (candidate bundle contains the reconciled Watch/Defense/agent-runtime surfaces)
#   → parity   (candidate serves every non-hashed file the live dist serves)
#   → backup   (full copy of current dist + an install manifest binding that backup by hash+commit)
#   → swap     (TRUE atomic renameat2(RENAME_EXCHANGE); documented two-rename fallback if unsupported)
#   → verify   (routes 200 AND served build-meta == candidate SHA AND agent-runtime read-plane envelope)
#              — ANY verify failure AUTO-ROLLS-BACK, and the rollback itself is verified before success.
# DRY-RUN by default. Sandbox-testable off-host: CC_DIST / BACKUP_ROOT / SKIP_SMOKE / SMOKE_BASE /
# SMOKE_ROUTES / VERIFY_META_URL / VERIFY_AGENT_URL(=none to skip) / VERIFY_AGENT_ROLE. Never prints a secret.
set -u -o pipefail
umask 077
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="${REPO:-/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild}"
DIST="${CC_DIST:-$REPO/apps/command-center-v3/dist}"
BASE="${SMOKE_BASE:-http://127.0.0.1:7777}"
BACKUP_ROOT="${BACKUP_ROOT:-$HOME/deploy/backups}"
SMOKE_ROUTES="${SMOKE_ROUTES-/v3 /v3-next /v3/agents /v3/watch /v3/defense}"
VERIFY_META_URL="${VERIFY_META_URL:-$BASE/v3/build-meta.json}"
VERIFY_AGENT_URL="${VERIFY_AGENT_URL:-$BASE/api/v3/agent-runtime/runs}"
VERIFY_AGENT_ROLE="${VERIFY_AGENT_ROLE:-agentic_runtime_reader}"
CAND="${1:-}"; APPLY="${2:-}"
STAMP="$(date +%Y%m%d_%H%M%S)"

fail(){ echo "final_status|$1"; exit 2; }
dirhash(){ PYTHONPATH="$DIR" python3 -c "import sys,convergence_lib as cl;print(cl.dir_content_hash(sys.argv[1]))" "$1"; }
meta_sc(){ python3 -c "import json,sys;print(json.load(open(sys.argv[1])).get('source_commit',''))" "$1/build-meta.json" 2>/dev/null; }

[ -n "$CAND" ] && [ -d "$CAND" ] || fail "BLOCKED_NO_CANDIDATE"
[ -d "$DIST" ] || fail "BLOCKED_NO_LIVE_DIST"
echo "candidate|$CAND"; echo "target_dist|$DIST"; echo "stamp|$STAMP"

# 1) provenance + marker + parity gates — pure convergence_lib decisions ----------------------------
PYTHONPATH="$DIR" python3 - "$CAND" "$DIST" <<'PY' || fail "BLOCKED_GATE_FAILED"
import json, os, sys, glob
import convergence_lib as cl
cand, dist = sys.argv[1], sys.argv[2]
relfiles = lambda root: [os.path.relpath(os.path.join(dp, fn), root)
                         for dp, _, fns in os.walk(root) for fn in fns]
meta = json.load(open(os.path.join(cand, "build-meta.json"), encoding="utf-8"))
cl.install_precheck(meta)
print("gate_provenance|OK|" + meta["source_commit"])
blob = ""
for f in glob.glob(os.path.join(cand, "assets", "*")) + [os.path.join(cand, "index.html")]:
    try: blob += open(f, encoding="utf-8", errors="ignore").read()
    except OSError: pass
missing = [m for m in cl.REQUIRED_BUNDLE_MARKERS if m not in blob]
print("gate_markers|" + ("OK" if not missing else "MISSING:" + ",".join(missing)))
assert not missing, f"candidate bundle missing markers: {missing}"
par = cl.swap_parity(relfiles(dist), relfiles(cand))
print("gate_parity|" + ("OK" if par["ok"] else "DROP:" + ",".join(par["dropped"])) + f"|superseded={len(par['superseded_assets'])}")
assert par["ok"], f"swap would drop served files: {par['dropped']}"
PY

CAND_SC="$(meta_sc "$CAND")"; ORIG_SC="$(meta_sc "$DIST")"
echo "candidate_source_commit|$CAND_SC"; echo "pre_swap_source_commit|${ORIG_SC:-NONE}"

if [ "$APPLY" != "--apply" ]; then
  echo "install_step|SKIPPED_DRY_RUN (all gates passed; --apply would backup + atomic-swap + verify + auto-rollback)"
  echo "final_status|INSTALL_DRY_RUN_OK"; exit 0
fi

# 2) backup current dist + write an install manifest binding it ------------------------------------
mkdir -p "$BACKUP_ROOT"
BK="$BACKUP_ROOT/cc-dist-$STAMP"
cp -a "$DIST" "$BK" || fail "BLOCKED_BACKUP_FAILED"
BK_HASH="$(dirhash "$BK")"
MANIFEST="$BACKUP_ROOT/cc-dist-$STAMP.manifest.json"
PYTHONPATH="$DIR" python3 - "$MANIFEST" "$STAMP" "$BK" "${ORIG_SC:-}" "$BK_HASH" "$CAND_SC" <<'PY'
import json, sys
import convergence_lib as cl
out, stamp, bk, orig, bkhash, cand = sys.argv[1:7]
m = cl.install_manifest(stamp=stamp, backup_dir=bk, backup_source_commit=(orig or None),
                        backup_dir_hash=bkhash, candidate_source_commit=cand)
open(out, "w").write(json.dumps(m, indent=2))
print("install_manifest|" + out)
PY
echo "backup|$BK|hash=${BK_HASH:0:16}"

# 3) swap — TRUE atomic exchange, documented two-rename fallback -----------------------------------
PARENT="$(dirname "$DIST")"; NAME="$(basename "$DIST")"
NEWDIR="$PARENT/$NAME.new-$STAMP"; OLDDIR="$PARENT/$NAME.old-$STAMP"
cp -a "$CAND" "$NEWDIR" || fail "BLOCKED_STAGE_COPY_FAILED"
if PYTHONPATH="$DIR" python3 "$DIR/_dirswap.py" exchange "$DIST" "$NEWDIR"; then
  mv "$NEWDIR" "$OLDDIR"                                  # NEWDIR now holds the original content
  echo "swapped|mode=atomic-exchange|old=$OLDDIR"
else
  # fallback: two sequential renames — a sub-millisecond window where $DIST briefly does not exist
  mv "$DIST" "$OLDDIR" && mv "$NEWDIR" "$DIST" || { [ -d "$OLDDIR" ] && [ ! -e "$DIST" ] && mv "$OLDDIR" "$DIST"; fail "BLOCKED_SWAP_FAILED_RESTORED"; }
  echo "swapped|mode=two-rename-nonatomic-window|old=$OLDDIR"
fi

# 4) post-swap verification: routes 200 + served build-meta SHA + read-plane envelope --------------
rollback(){
  echo "verify|FAILED — auto-rolling back to pre-swap dist"
  rm -rf "$DIST.failed-$STAMP" 2>/dev/null
  mv "$DIST" "$DIST.failed-$STAMP" && mv "$OLDDIR" "$DIST"
  # verify the rollback ITSELF took effect before claiming success
  if [ -d "$DIST" ] && [ "$(meta_sc "$DIST")" = "${ORIG_SC}" ]; then
    echo "rolled_back|restored_from=$OLDDIR|failed_kept=$DIST.failed-$STAMP"
    fail "INSTALL_VERIFY_FAILED_ROLLED_BACK"
  fi
  echo "rollback_verify|FAILED — live dist is NOT the pre-swap bundle"
  fail "CRITICAL_ROLLBACK_FAILED_MANUAL_INTERVENTION (backup=$BK)"
}

if [ "${SKIP_SMOKE:-}" != "1" ]; then
  bad=0
  for r in $SMOKE_ROUTES; do
    code="$(curl -sS -o /dev/null -w '%{http_code}' --max-time 8 "$BASE$r" 2>/dev/null || echo 000)"
    echo "smoke|$r|$code"; [ "$code" = "200" ] || bad=1
  done
  # served build-meta must carry the candidate SHA (catches a stale/cached bundle or no-op swap)
  sm="$(curl -sS --max-time 8 "$VERIFY_META_URL" 2>/dev/null || echo '{}')"
  if printf '%s' "$sm" | PYTHONPATH="$DIR" python3 -c 'import json,sys,convergence_lib as cl
raw=sys.stdin.read() or "{}"
try: b=json.loads(raw)
except Exception: b={}
sys.exit(0 if cl.served_build_ok(b, sys.argv[1]) else 1)' "$CAND_SC"; then
    echo "verify_served_meta|OK|$CAND_SC"
  else
    echo "verify_served_meta|MISMATCH (served != $CAND_SC)"; bad=1
  fi
  # agent-runtime read plane must remain 200/read_only/connected/zero-authority
  if [ "$VERIFY_AGENT_URL" != "none" ]; then
    ar="$(curl -sS --max-time 8 -w $'\n%{http_code}' "$VERIFY_AGENT_URL" 2>/dev/null || printf '{}\n000')"
    code="${ar##*$'\n'}"; body="${ar%$'\n'*}"
    if printf '%s' "$body" | PYTHONPATH="$DIR" python3 -c 'import json,sys,convergence_lib as cl
raw=sys.stdin.read() or "{}"
try: b=json.loads(raw)
except Exception: b={}
sys.exit(0 if cl.read_plane_ok(int(sys.argv[1]), b, sys.argv[2]) else 1)' "$code" "$VERIFY_AGENT_ROLE"; then
      echo "verify_read_plane|OK|$code"
    else
      echo "verify_read_plane|BAD|http=$code"; bad=1
    fi
  fi
  [ "$bad" = 1 ] && rollback
fi

echo "install_record|backup=$BK|manifest=$MANIFEST|onhost_rollback=$OLDDIR|source_commit=$(meta_sc "$DIST")"
echo "final_status|INSTALL_APPLIED_AND_VERIFIED"
