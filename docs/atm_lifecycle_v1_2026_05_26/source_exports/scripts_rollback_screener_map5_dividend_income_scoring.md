# Source Export: scripts/rollback_screener_map5_dividend_income_scoring.sh

| Field | Value |
|-------|-------|
| **Original Path** | `scripts/rollback_screener_map5_dividend_income_scoring.sh` |
| **Git Branch** | `main` |
| **Git Commit** | `915876f` |
| **Export Timestamp** | `2026-05-26T19:48:00Z` |
| **SHA256** | `6ad489a0428f55617a2a80751ae5d53b9207fd93ad9999edd4787b7896e454b2` |
| **File Size** | 465 bytes |

## Full Source

```sh
#!/usr/bin/env bash
# Rollback SCREENER-MAP-5 dividend income scoring changes.
set -eo pipefail
echo "SCREENER-MAP-5 Rollback"
echo "Current commit: $(git log --oneline -1)"
echo "To revert: git revert <MAP-5-commit-hash>"
echo "Changes to revert:"
echo "  - _DIVERSITY_SCORE_FLOOR back to 30 in incubator_proposal_promoter.py"
echo "  - min_score back to 10 in DIVIDEND_INCOME thresholds"
echo "  - Remove use_dividend_scoring flag"
echo "No data changes needed."
```
