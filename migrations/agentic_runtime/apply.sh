#!/usr/bin/env bash
# apply.sh — PREPARE-ONLY migration + role applier for the agentic_runtime schema.
#
# This wrapper NEVER applies anything unless invoked with an explicit --apply flag.
# Without --apply it prints exactly what it WOULD run and exits non-zero. Even with
# --apply it refuses a production-looking DSN and requires an isolated LAB/SHADOW DSN.
#
# It has no broker, order, approval, 2FA, secret, or production-config authority. It
# only creates the isolated agentic_runtime schema (0001), its least-privilege
# roles (0002), and the governed trigger intake queue (0003), or rolls them back.
#
# Usage:
#   ./apply.sh                      # prepare-only: print plan, exit 3
#   ./apply.sh --apply up           # apply schema + roles (requires TRADE_AI_LAB_DSN)
#   ./apply.sh --apply down         # roll back roles + schema
#   TRADE_AI_LAB_DSN=... ./apply.sh --apply up

set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APPLY=0
DIRECTION="up"

for arg in "$@"; do
    case "$arg" in
        --apply) APPLY=1 ;;
        up|down) DIRECTION="$arg" ;;
        *) echo "unknown argument: $arg" >&2; exit 2 ;;
    esac
done

if [ "$DIRECTION" = "up" ]; then
    FILES=("0001_mvl.up.sql" "0002_roles.up.sql" "0003_trigger_intake.up.sql" "0004_pipeline_health_approvals.up.sql")
else
    FILES=("0004_pipeline_health_approvals.down.sql" "0003_trigger_intake.down.sql" "0002_roles.down.sql" "0001_mvl.down.sql")
fi

echo "=============================================================="
echo " agentic_runtime migration applier — PREPARE-ONLY"
echo " direction : ${DIRECTION}"
echo " files     : ${FILES[*]}"
echo "=============================================================="

if [ "$APPLY" -ne 1 ]; then
    echo
    echo "PREPARE-ONLY: no --apply flag supplied. Nothing was applied."
    echo "This script is default-disabled. It would run, in order:"
    for f in "${FILES[@]}"; do
        echo "  psql \"\$TRADE_AI_LAB_DSN\" -v ON_ERROR_STOP=1 -f ${HERE}/${f}"
    done
    echo
    echo "Re-run with --apply against an isolated LAB/SHADOW database to apply."
    exit 3
fi

# --apply path: hard guards before any DB contact.
DSN="${TRADE_AI_LAB_DSN:-}"
if [ -z "$DSN" ]; then
    echo "refusing to apply: TRADE_AI_LAB_DSN is not set (isolated LAB/SHADOW DSN required)." >&2
    exit 4
fi
case "$DSN" in
    *prod*|*production*|*trade_ai_prod*)
        echo "refusing to apply: DSN looks like production; this schema is LAB/SHADOW only." >&2
        exit 5 ;;
esac

echo "applying ${DIRECTION} migration to the configured LAB/SHADOW database..."
for f in "${FILES[@]}"; do
    echo "-> ${f}"
    psql "$DSN" -v ON_ERROR_STOP=1 -f "${HERE}/${f}"
done
echo "done. Set role passwords out-of-band from the secret store; do not store them here."
