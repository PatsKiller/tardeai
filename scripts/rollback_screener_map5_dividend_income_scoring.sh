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
