# Quick-Add Policy — Stage 7
Presets 100/200/500/1000; units SHARES or DOLLARS (explicit selector). Quick-add uses the SAME
sizing + cap validation as normal entry (per-account share cap, notional cap, session gross
notional remaining). Returns {shares, notional, blocked, violations}. NO order is created —
validation only. Tested: preset within caps passes; over-cap blocks; DOLLARS→shares by price;
bad config rejected.
