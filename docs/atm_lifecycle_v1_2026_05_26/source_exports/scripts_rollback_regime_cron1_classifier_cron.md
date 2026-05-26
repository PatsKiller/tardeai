# Source Export: scripts/rollback_regime_cron1_classifier_cron.sh

| Field | Value |
|-------|-------|
| **Original Path** | `scripts/rollback_regime_cron1_classifier_cron.sh` |
| **Git Branch** | `main` |
| **Git Commit** | `915876f` |
| **Export Timestamp** | `2026-05-26T19:48:00Z` |
| **SHA256** | `40f4a1115151e89deaf4cdd11d78ed6e8a562defe2aeca6d888f250ae4daa780` |
| **File Size** | 705 bytes |

## Full Source

```sh
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
```
