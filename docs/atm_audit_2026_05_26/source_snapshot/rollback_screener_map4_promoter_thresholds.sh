#!/usr/bin/env bash
# Rollback SCREENER-MAP-4 promoter family threshold wiring.
# Default: dry-run. Use --apply to actually revert.
set -eo pipefail

PROJ="/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild"
APPLY=false
[ "$1" = "--apply" ] && APPLY=true

echo "SCREENER-MAP-4 Rollback"
echo "Current commit: $(git -C $PROJ log --oneline -1)"
echo "Mode: $([ "$APPLY" = true ] && echo 'APPLY' || echo 'DRY RUN')"
echo ""
echo "To revert MAP-4 changes:"
echo "  git revert <MAP-4-commit-hash>"
echo ""
echo "Manual alternative:"
echo "  In scripts/incubator_proposal_promoter.py:"
echo "    Replace family-specific spread gate with: _spread > 3.0"
echo "    Remove strategy_id='screener' blocker"
echo ""
echo "No data changes needed — MAP-4 only changed promoter evaluation logic."
