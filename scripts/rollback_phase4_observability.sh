#!/usr/bin/env bash
# rollback_phase4_observability.sh — Disable Phase 4 observability if needed.
# Does NOT change model fleet, routing, .env, or cron.
set -uo pipefail
PROJ=/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild
RULES="$PROJ/config/llm_fleet_alert_rules.yaml"

case "${1:-}" in
    --dry-run) echo "DRY RUN — would disable alert rules in $RULES"; grep "^enabled:" "$RULES" 2>/dev/null ;;
    --disable-alerts) [ -f "$RULES" ] && sed -i 's/^enabled: true/enabled: false/' "$RULES" && echo "Alerts DISABLED." && grep "^enabled:" "$RULES" || echo "Rules not found" ;;
    --status) grep "^enabled:" "$RULES" 2>/dev/null || echo "Rules not found" ;;
    *) echo "Usage: $0 [--dry-run|--disable-alerts|--status]" ;;
esac
