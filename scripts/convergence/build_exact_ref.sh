#!/usr/bin/env bash
# Convergence — Phase STAGE: build the Command Center candidate from an EXACT git object, never the
# live checkout. DRY-RUN by default (stages + verifies source markers + prints the plan). --apply
# additionally runs `npm ci` + build inside the staged tree and stamps build-meta with the 40-char SHA.
# Read-only vs the host until --apply; --apply writes ONLY into a scratch staging dir (no host install).
set -u -o pipefail
umask 077
REPO="/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild"
COMMIT="21366635ce6e2a8610e0ea1ea716036016df299b"
CC="apps/command-center-v3"
APPLY="${1:-}"
STAGE="$(mktemp -d /tmp/convergence-stage.XXXXXX)"

echo "source_commit|$COMMIT"
echo "source_mode|PINNED_GIT_OBJECT_ARCHIVE"
echo "stage_dir|$STAGE"

# 1) export the EXACT ref (no live-checkout, no uncommitted files can enter) ------------------------
git -C "$REPO" archive --format=tar "$COMMIT" | tar -x -C "$STAGE" || { echo "final_status|BLOCKED_ARCHIVE_FAILED"; exit 2; }
echo "frontend_build_source|STAGED_EXACT_REF"
echo "live_checkout_build_input|NONE"

# 2) prove the reconciled behavior is present in the STAGED SOURCE (Watch / Defense / agents) -------
verify() { grep -Rqs -- "$2" "$STAGE/$CC/src" && echo "staged_marker|$1|$2|PRESENT" || echo "staged_marker|$1|$2|ABSENT"; }
verify watch  "ADMITTED"
verify watch  "RESEARCH_ONLY"
verify watch  "QUARANTINED"
verify defense "ELIGIBLE NOW"
verify defense "RESEARCH WATCH"
verify defense "NO DECISION"
grep -Rqs -- "agent-runtime-command-center-read-api-v1" "$STAGE/$CC/src" "$STAGE/scripts/agent_runtime" \
  && echo "staged_marker|agent_runtime|contract|PRESENT" || echo "staged_marker|agent_runtime|contract|ABSENT"

# 3) hash the staged backend files (candidate provenance) ------------------------------------------
for f in scripts/portfolio_server.py scripts/agent_runtime/read_http.py scripts/agent_runtime/read_api.py \
         scripts/watch_quality_policy.py scripts/defense_data_quality.py; do
  [ -f "$STAGE/$f" ] && echo "staged_backend_hash|$f|$(sha256sum "$STAGE/$f" | awk '{print $1}')"
done

if [ "$APPLY" != "--apply" ]; then
  echo "build_step|SKIPPED_DRY_RUN (would run: cd $STAGE/$CC && npm ci && npm run build)"
  echo "candidate_bundle|NOT_BUILT (dry-run)"
  echo "final_status|STAGE_DRY_RUN_OK"
  echo "cleanup|rm -rf $STAGE"
  exit 0
fi

# --apply: build inside the staged tree ONLY -------------------------------------------------------
( cd "$STAGE/$CC" && npm ci --no-audit --no-fund && npm run build ) || { echo "final_status|BUILD_FAILED"; exit 2; }
BUILD_SHA=$(git -C "$REPO" rev-parse "$COMMIT")
python3 - "$STAGE/$CC/dist/build-meta.json" "$BUILD_SHA" <<'PY'
import json,sys
p,sha=sys.argv[1],sys.argv[2]
m={"source_commit":sha,"source_mode":"PINNED_GIT_OBJECT_ARCHIVE","frontend_build_source":"STAGED_EXACT_REF",
   "live_checkout_build_input":"NONE","contracts":{"agent_runtime":"agent-runtime-command-center-read-api-v1"}}
open(p,"w").write(json.dumps(m,indent=2)); print("build_meta_written|"+sha)
PY
echo "candidate_bundle_hash|$(find "$STAGE/$CC/dist" -type f -exec sha256sum {} \; | sha256sum | awk '{print $1}')"
echo "candidate_dist|$STAGE/$CC/dist"
echo "next_step|scripts/convergence/static_install.sh $STAGE/$CC/dist --apply  (backup + gate + atomic swap + smoke + auto-rollback)"
echo "final_status|STAGE_BUILT (candidate in $STAGE — NOT installed to host)"
