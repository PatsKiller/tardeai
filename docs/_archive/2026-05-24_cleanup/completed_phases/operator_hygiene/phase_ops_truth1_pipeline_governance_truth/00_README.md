# OPS-TRUTH-1 — Pipeline Operations and Governance Truth-Layer Fix

**Status:** COMPLETE

## What Was Fixed

1. **Pipeline Health false nominal**: Changed "X/X stages nominal (no runs yet today)" to "0/X stages completed today — waiting for schedule" when no stages have run. Truth audit: 13/29 nominal, 5 waiting, 6 not started, 5 stale.

2. **Governance scorecard contradiction**: Changed "No closed paper trades yet" to explain eligibility when closed trades exist but scorecards are empty: "10 closed paper trades exist, but no strategy has enough trades for scorecard eligibility yet."

3. **Audit scripts**: Pipeline truth audit (29 stages) and governance count consistency report.

## Before/After

| Issue | Before | After |
|-------|--------|-------|
| Pipeline zero runs | "31/31 stages nominal" | "0/31 completed — waiting for schedule" |
| Governance empty scorecard | "No closed paper trades yet" | "10 closed trades exist, none meet sample size" |

## Tests

9/9 pass. Frontend built 207ms.
