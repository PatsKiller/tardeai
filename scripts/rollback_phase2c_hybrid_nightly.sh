#!/usr/bin/env bash
# rollback_phase2c_hybrid_nightly.sh — Disable Phase 2C nightly hybrid RAG.
#
# Preferred: restores the saved pre-change crontab backup.
# Fallback:  removes all Phase 2C hybrid flags via sed.
#
# Does NOT touch .env, broker, holdings, execution, or base daily deep window schedule.
# Does NOT affect Friday extended unless it had hybrid flags (currently it does not).
# Phase 2D remains blocked.
set -uo pipefail

PROJ=/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild
BACKUP="$PROJ/docs/llm_fleet/phase2_embedding_ab/crontab_pre_phase2c_nightly_hybrid_enable.txt"

echo "=== Phase 2C Hybrid RAG Rollback ==="
echo "Time: $(date)"
echo

# Preferred: restore backup crontab
if [ -f "$BACKUP" ]; then
    echo "Backup crontab found: $BACKUP"
    echo "Restoring pre-Phase-2C crontab..."
    crontab "$BACKUP"
    echo "Restored."
else
    echo "WARNING: Backup crontab not found. Using manual sed fallback."
    echo "Removing all Phase 2C hybrid flags..."
    crontab -l | sed \
      -e 's/ --enable-hybrid-rag//g' \
      -e 's/ --hybrid-prefetch-limit [0-9]*//g' \
      -e 's/ --hybrid-job-types [^ ]*//g' \
      -e 's/ --hybrid-context-file [^ ]*//g' \
      -e 's/ --hybrid-final-k [0-9]*//g' \
      -e 's/ --hybrid-mode [^ ]*//g' \
      -e 's/ --hybrid-strict [^ ]*//g' \
      | crontab -
    echo "Sed fallback applied."
fi

echo
echo "=== Resulting deep overnight cron lines ==="
crontab -l | grep run_deep_overnight_llm_window || echo "(none found)"
echo
echo "Rollback complete. Phase 2C nightly hybrid is now disabled."
echo "Phase 1 base deep overnight schedule is preserved."
