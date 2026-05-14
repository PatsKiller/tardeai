#!/usr/bin/env bash
# rollback_phase2c_hybrid_nightly.sh — Disable Phase 2C hybrid RAG from deep overnight cron.
#
# Usage:
#   ./scripts/rollback_phase2c_hybrid_nightly.sh --all              # rollback daily + Friday
#   ./scripts/rollback_phase2c_hybrid_nightly.sh --daily            # rollback daily only
#   ./scripts/rollback_phase2c_hybrid_nightly.sh --friday           # rollback Friday only
#   ./scripts/rollback_phase2c_hybrid_nightly.sh --all --dry-run    # show what would change
#
# Preferred: restores saved pre-change crontab backup.
# Fallback:  removes all Phase 2C hybrid flags via sed.
#
# Does NOT touch .env, broker, holdings, execution, or base daily deep window schedule.
# Phase 2D global promotion remains blocked.
set -uo pipefail

PROJ=/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild
BACKUP_PRE="$PROJ/docs/llm_fleet/phase2_embedding_ab/crontab_pre_phase2c_nightly_hybrid_enable.txt"

ROLLBACK_DAILY=false
ROLLBACK_FRIDAY=false
DRY_RUN=false

while [[ $# -gt 0 ]]; do
    case "$1" in
        --daily)   ROLLBACK_DAILY=true; shift ;;
        --friday)  ROLLBACK_FRIDAY=true; shift ;;
        --all)     ROLLBACK_DAILY=true; ROLLBACK_FRIDAY=true; shift ;;
        --dry-run) DRY_RUN=true; shift ;;
        *) echo "Usage: $0 [--daily|--friday|--all] [--dry-run]" >&2; exit 1 ;;
    esac
done

if [ "$ROLLBACK_DAILY" = false ] && [ "$ROLLBACK_FRIDAY" = false ]; then
    echo "ERROR: Specify --daily, --friday, or --all" >&2
    exit 1
fi

echo "=== Phase 2C Hybrid RAG Rollback ==="
echo "Time: $(date)"
echo "Daily:  $ROLLBACK_DAILY"
echo "Friday: $ROLLBACK_FRIDAY"
echo "Dry-run: $DRY_RUN"
echo

# Build sed expressions based on scope
SED_ARGS=()
if [ "$ROLLBACK_DAILY" = true ] && [ "$ROLLBACK_FRIDAY" = true ]; then
    # Remove all hybrid flags from all deep window lines
    SED_ARGS=(
        -e 's/ --enable-hybrid-rag//g'
        -e 's/ --hybrid-prefetch-limit [0-9]*//g'
        -e 's/ --hybrid-job-types [^ ]*//g'
        -e 's/ --hybrid-context-file [^ ]*//g'
        -e 's/ --hybrid-final-k [0-9]*//g'
        -e 's/ --hybrid-mode [^ ]*//g'
        -e 's/ --hybrid-strict [^ ]*//g'
    )
elif [ "$ROLLBACK_DAILY" = true ]; then
    # Only the daily 23:00 line (line starting with "0 23")
    SED_ARGS=(
        -e '/^0 23/s/ --enable-hybrid-rag//g'
        -e '/^0 23/s/ --hybrid-prefetch-limit [0-9]*//g'
        -e '/^0 23/s/ --hybrid-job-types [^ ]*//g'
        -e '/^0 23/s/ --hybrid-final-k [0-9]*//g'
        -e '/^0 23/s/ --hybrid-mode [^ ]*//g'
    )
elif [ "$ROLLBACK_FRIDAY" = true ]; then
    # Only the Friday 16:00 line (line starting with "0 16" containing "5")
    SED_ARGS=(
        -e '/^0 16.*5/s/ --enable-hybrid-rag//g'
        -e '/^0 16.*5/s/ --hybrid-prefetch-limit [0-9]*//g'
        -e '/^0 16.*5/s/ --hybrid-job-types [^ ]*//g'
        -e '/^0 16.*5/s/ --hybrid-final-k [0-9]*//g'
        -e '/^0 16.*5/s/ --hybrid-mode [^ ]*//g'
    )
fi

if [ "$DRY_RUN" = true ]; then
    echo "=== DRY RUN — would produce these deep window cron lines ==="
    if [ "$ROLLBACK_DAILY" = true ] && [ "$ROLLBACK_FRIDAY" = true ] && [ -f "$BACKUP_PRE" ]; then
        echo "(would restore from backup: $BACKUP_PRE)"
        grep run_deep_overnight_llm_window "$BACKUP_PRE" || true
    else
        crontab -l | sed "${SED_ARGS[@]}" | grep run_deep_overnight_llm_window || true
    fi
    echo "=== DRY RUN COMPLETE — no changes made ==="
    exit 0
fi

# Apply rollback
if [ "$ROLLBACK_DAILY" = true ] && [ "$ROLLBACK_FRIDAY" = true ] && [ -f "$BACKUP_PRE" ]; then
    echo "Restoring pre-Phase-2C crontab backup..."
    crontab "$BACKUP_PRE"
    echo "Restored from: $BACKUP_PRE"
else
    echo "Applying sed rollback..."
    crontab -l | sed "${SED_ARGS[@]}" | crontab -
    echo "Sed rollback applied."
fi

echo
echo "=== Resulting deep overnight cron lines ==="
crontab -l | grep run_deep_overnight_llm_window || echo "(none found)"
echo
echo "Rollback complete. Phase 1 base deep overnight schedule preserved."
