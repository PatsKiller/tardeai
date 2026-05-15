#!/usr/bin/env bash
# rollback_phase2g_canary.sh — Disable Phase 2G hybrid RAG canary.
# Does NOT affect Phase 2C deep wrapper or production nomic retrieval.
set -uo pipefail

PROJ=/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild
CONFIG="$PROJ/config/phase2g_hybrid_canary.yaml"

case "${1:-}" in
    --dry-run)
        echo "DRY RUN — would set 'enabled: false' in $CONFIG"
        grep "^enabled:" "$CONFIG" 2>/dev/null || echo "(config not found)"
        ;;
    --disable)
        if [ -f "$CONFIG" ]; then
            sed -i 's/^enabled: true/enabled: false/' "$CONFIG"
            echo "Phase 2G canary DISABLED."
            grep "^enabled:" "$CONFIG"
        else
            echo "Config not found: $CONFIG"
        fi
        ;;
    --status)
        grep "^enabled:" "$CONFIG" 2>/dev/null || echo "Config not found"
        ;;
    *)
        echo "Usage: $0 [--dry-run|--disable|--status]"
        ;;
esac
