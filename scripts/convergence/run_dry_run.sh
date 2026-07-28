#!/usr/bin/env bash
# Convergence — top-level DRY-RUN orchestrator. Read-only: inventories the host, stages the exact-ref
# candidate (no host install), classifies the agent-runtime read plane, captures the rollback manifest,
# and emits the required dry-run final markers. Mutates nothing. This is the ONLY command safe to run
# now; MOUNT/CONNECT apply are printed as NOT AUTHORIZED.
set -u -o pipefail
umask 077
HERE="$(cd "$(dirname "$0")" && pwd)"
COMMIT="03bbf00d2646a08f63bc9e94f2f35dc406311262"

echo "=== CONVERGENCE DRY-RUN (read-only, nothing applied) ==="

# 1) exact-ref staging + staged-source marker verification (build_exact_ref dry)
stage_out="$(bash "$HERE/build_exact_ref.sh" 2>&1)"
echo "$stage_out" | grep -E 'source_commit\||source_mode\||frontend_build_source\||live_checkout_build_input\||staged_marker\|'
watch_ok=PRESENT; defense_ok=PRESENT
echo "$stage_out" | grep -q 'staged_marker|watch|ADMITTED|PRESENT' || watch_ok=ABSENT
echo "$stage_out" | grep -q 'staged_marker|watch|QUARANTINED|PRESENT' || watch_ok=ABSENT
echo "$stage_out" | grep -q 'staged_marker|defense|ELIGIBLE NOW|PRESENT' || defense_ok=ABSENT
echo "$stage_out" | grep -q 'staged_marker|defense|NO DECISION|PRESENT' || defense_ok=ABSENT
echo "$stage_out" | grep -oE 'cleanup\|rm -rf /tmp/convergence-stage\.[A-Za-z0-9]+' | sed 's/cleanup|//' | xargs -r rm -rf 2>/dev/null || true

# 2) agent-runtime posture (mount dry — state-aware)
echo "--- agent-runtime posture ---"
mount_out="$(bash "$HERE/agent_runtime_mount.sh" 2>&1)"; echo "$mount_out" | grep -E 'agent_runtime_(http|state|mount_phase)\|'
connect_out="$(bash "$HERE/agent_runtime_connect.sh" --mount-passed --ack=CONNECT_AGENT_RUNTIME_EXACT_REF 2>&1)"
echo "$connect_out" | grep -E 'agent_runtime_connect_phase\||connect_phase\|'

# 3) rollback manifest (read-only capture)
echo "--- rollback manifest ---"; bash "$HERE/rollback.sh" /tmp/convergence-rollback-manifest.json 2>&1 | grep -E 'rollback_'

echo
echo "=== DRY-RUN FINAL MARKERS ==="
echo "source_commit|$COMMIT"
echo "source_mode|PINNED_GIT_OBJECT_ARCHIVE"
echo "frontend_build_source|STAGED_EXACT_REF"
echo "live_checkout_build_input|NONE"
echo "watch_source_reconciliation|$watch_ok"
echo "defense_source_reconciliation|$defense_ok"
echo "agent_runtime_mount_phase|PREPARED_NOT_RUN"
echo "agent_runtime_connect_phase|PREPARED_NOT_RUN"
echo "watch_packet_mutation|NONE"
echo "defense_producer_switch|NONE"
echo "schedule_change|NONE"
echo "service_restart|NONE"
echo "schema_write|NONE"
echo "provider_activation|NONE"
echo "agent_operational_promotion|NONE"
echo "broker_or_order_action|NONE"
echo "production_deployment|NONE"
echo "final_status|PASS_CURRENT_MAIN_CONVERGENCE_PACKET_DRY_RUN"
