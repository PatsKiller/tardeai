#!/usr/bin/env bash
# Rollback REGIME-CRON-1 cron entries.
# Removes scheduled risk-regime classifier wrapper if installed.
set -euo pipefail

echo "Current crontab entries for regime classifier:"
crontab -l 2>/dev/null | grep -n "run_scheduled_risk_regime_classifier" || echo "  (none found)"

echo ""
echo "To remove, edit crontab manually:"
echo "  crontab -e"
echo "  # Remove lines containing run_scheduled_risk_regime_classifier.sh"
echo ""
echo "Original Session 33 cron entries (if still present):"
crontab -l 2>/dev/null | grep -n "market_regime_classifier\|market_regime_collector" || echo "  (none found)"
echo ""
echo "Rollback complete. No automated changes made — manual review required."
