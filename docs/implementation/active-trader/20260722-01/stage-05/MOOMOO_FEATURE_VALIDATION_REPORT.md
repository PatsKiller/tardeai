# Moomoo Feature Validation Report — Stage 5

`scripts/active_trader/moomoo/features.py` — deterministic market-data features computed
OUTSIDE callbacks. Versioned (`moomoo-features-1`), no lookahead, no LLM, no authority,
null when input absent. Does NOT implement RES/RRS or any trade decision.

## Implemented + unit-tested
last/bid/ask/mid, spread cents + bps, microprice, weighted mid, top imbalance,
level-weighted imbalance (level-decayed), depth-by-level, VWAP/RVOL/ROC pass-through,
session high/low, data_age_ms, gap_state. Formula spot-checks: mid(10.00,10.10)=10.05;
spread 10.0¢ / ~99.5 bps; microprice(10.00,10.10,100,300)=10.025; top_imbalance(300,100)=0.5.
Nulls verified when any input is absent (no fabrication).

## Deterministic replay equivalence
Identical inputs → byte-identical FeatureSnapshot dicts (tested). This is the property that
lets replay reproduce live features exactly; full live-vs-replay equivalence over captured
data is pending a working login + capture session.
