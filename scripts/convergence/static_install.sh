#!/usr/bin/env bash
# Convergence — Phase INSTALL: atomically swap a STAGED exact-ref candidate dist onto the live host.
# Order of operations (each gate can only make the swap SAFER, never skip a check):
#   provenance gate (build-meta: 40-char SHA + STAGED_EXACT_REF + agent-runtime contract)
#   → marker gate   (candidate bundle actually contains the reconciled Watch/Defense/agent-runtime surfaces)
#   → parity gate   (candidate provides every non-hashed served file the live dist serves)
#   → backup        (full copy of current dist to an archived rollback point)
#   → atomic swap   (rename pair on one filesystem: dist→dist.old-<stamp>, dist.new-<stamp>→dist)
#   → HTTP smoke    (every route must be 200) — ANY failure AUTO-ROLLS-BACK to the pre-swap dist.
# DRY-RUN by default (runs all gates, prints the plan, touches nothing). --apply performs the swap.
# Sandbox-testable without the host: CC_DIST overrides target, BACKUP_ROOT overrides backups,
# SKIP_SMOKE=1 skips HTTP, SMOKE_BASE/SMOKE_ROUTES override the probe. Never prints a secret.
set -u -o pipefail
umask 077
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="${REPO:-/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild}"
DIST="${CC_DIST:-$REPO/apps/command-center-v3/dist}"
BASE="${SMOKE_BASE:-http://127.0.0.1:7777}"
BACKUP_ROOT="${BACKUP_ROOT:-$HOME/deploy/backups}"
SMOKE_ROUTES="${SMOKE_ROUTES:-/v3 /v3-next /v3/agents /v3/watch /v3/defense}"
CAND="${1:-}"; APPLY="${2:-}"
STAMP="$(date +%Y%m%d_%H%M%S)"

fail(){ echo "final_status|$1"; exit 2; }

[ -n "$CAND" ] && [ -d "$CAND" ] || fail "BLOCKED_NO_CANDIDATE"
[ -d "$DIST" ] || fail "BLOCKED_NO_LIVE_DIST"
echo "candidate|$CAND"
echo "target_dist|$DIST"
echo "stamp|$STAMP"

# 1) provenance + marker + parity gates — all pure convergence_lib decisions -----------------------
PYTHONPATH="$DIR" python3 - "$CAND" "$DIST" <<'PY' || fail "BLOCKED_GATE_FAILED"
import json, os, sys, glob
import convergence_lib as cl
cand, dist = sys.argv[1], sys.argv[2]

def relfiles(root):
    return [os.path.relpath(os.path.join(dp, fn), root)
            for dp, _, fns in os.walk(root) for fn in fns]

meta = json.load(open(os.path.join(cand, "build-meta.json"), encoding="utf-8"))
cl.install_precheck(meta)                                   # 40-char SHA + EXACT + agent-runtime contract
print("gate_provenance|OK|" + meta["source_commit"])

blob = ""
for f in glob.glob(os.path.join(cand, "assets", "*")) + [os.path.join(cand, "index.html")]:
    try:
        blob += open(f, encoding="utf-8", errors="ignore").read()
    except OSError:
        pass
missing = [m for m in cl.REQUIRED_BUNDLE_MARKERS if m not in blob]
print("gate_markers|" + ("OK" if not missing else "MISSING:" + ",".join(missing)))
assert not missing, f"candidate bundle missing markers: {missing}"

par = cl.swap_parity(relfiles(dist), relfiles(cand))
print("gate_parity|" + ("OK" if par["ok"] else "DROP:" + ",".join(par["dropped"]))
      + "|superseded=" + str(len(par["superseded_assets"])))
assert par["ok"], f"swap would drop served files: {par['dropped']}"
PY

if [ "$APPLY" != "--apply" ]; then
  echo "install_step|SKIPPED_DRY_RUN (all gates passed; --apply would backup + atomic-swap + smoke + auto-rollback)"
  echo "final_status|INSTALL_DRY_RUN_OK"
  exit 0
fi

# 2) backup current dist (archived rollback point) ------------------------------------------------
mkdir -p "$BACKUP_ROOT"
BK="$BACKUP_ROOT/cc-dist-$STAMP"
cp -a "$DIST" "$BK" || fail "BLOCKED_BACKUP_FAILED"
echo "backup|$BK"

# 3) atomic swap (rename pair on one filesystem) --------------------------------------------------
PARENT="$(dirname "$DIST")"; NAME="$(basename "$DIST")"
NEWDIR="$PARENT/$NAME.new-$STAMP"; OLDDIR="$PARENT/$NAME.old-$STAMP"
cp -a "$CAND" "$NEWDIR" || fail "BLOCKED_STAGE_COPY_FAILED"
mv "$DIST" "$OLDDIR" && mv "$NEWDIR" "$DIST" || {
  [ -d "$OLDDIR" ] && [ ! -e "$DIST" ] && mv "$OLDDIR" "$DIST"; fail "BLOCKED_SWAP_FAILED_RESTORED"; }
echo "swapped|old=$OLDDIR"

# 4) HTTP smoke — AUTO-ROLLBACK on any non-200 ----------------------------------------------------
if [ "${SKIP_SMOKE:-}" != "1" ]; then
  bad=0
  for r in $SMOKE_ROUTES; do
    code="$(curl -sS -o /dev/null -w '%{http_code}' --max-time 8 "$BASE$r" 2>/dev/null || echo 000)"
    echo "smoke|$r|$code"; [ "$code" = "200" ] || bad=1
  done
  if [ "$bad" = 1 ]; then
    echo "smoke|FAILED — auto-rolling back to pre-swap dist"
    rm -rf "$DIST.failed-$STAMP" 2>/dev/null
    mv "$DIST" "$DIST.failed-$STAMP" && mv "$OLDDIR" "$DIST"
    echo "rolled_back|restored_from=$OLDDIR|failed_kept=$DIST.failed-$STAMP"
    fail "INSTALL_SMOKE_FAILED_ROLLED_BACK"
  fi
fi

echo "install_record|backup=$BK|onhost_rollback=$OLDDIR|source_commit=$(python3 -c "import json;print(json.load(open('$DIST/build-meta.json'))['source_commit'])")"
echo "final_status|INSTALL_APPLIED_AND_SMOKED"
