#!/usr/bin/env bash
# rollback_phase3_media_prose_routing.sh — Disable Phase 3C media/prose routing.
set -uo pipefail
PROJ=/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild
CONFIG="$PROJ/config/phase3_media_prose_routing.yaml"

case "${1:-}" in
    --dry-run) echo "DRY RUN — would set 'enabled: false' in $CONFIG"; grep "^enabled:" "$CONFIG" 2>/dev/null ;;
    --disable) [ -f "$CONFIG" ] && sed -i 's/^enabled: true/enabled: false/' "$CONFIG" && echo "Phase 3C DISABLED." && grep "^enabled:" "$CONFIG" || echo "Config not found" ;;
    --status) grep "^enabled:" "$CONFIG" 2>/dev/null || echo "Config not found" ;;
    *) echo "Usage: $0 [--dry-run|--disable|--status]" ;;
esac
