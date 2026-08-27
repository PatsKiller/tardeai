# Internal-vs-Professional Divergence Monitor (2026-06-08)

## Fix that made divergence computable
fused_signals.direction is EMPTY for all rows (signal_fusion doesn't populate it) — divergence was stuck at
"unavailable" for every symbol. build_pro_analyst_read_model.internal_dir now falls back to the catalyst
classifier's directional consensus (majority of recent catalyst_events raw_payload->direction, bullish/bearish)
when fused direction is blank. Result: divergence now computes.

## Monitor (in pro_analyst_monitor.py, daily 06:10 chain, read-only)
Snapshots divergence_counts {aligned/mixed/divergent/unavailable} + comparable (both-sides-known) + the
divergent symbol map → 90-day history. Diffs vs prior: newly_divergent / resolved_divergence; flags NEW
divergences for operator review.

## Baseline today
comparable=4 · aligned: RTX, V (internal bullish = Street bullish) · DIVERGENT: LHX (internal bearish vs
Street bullish), RKLB (internal bearish vs Street bullish) — review candidates · 120 unavailable (no internal
direction yet). As fused/catalyst coverage grows, comparable rises and divergence populates further.

## Surfaced
/api/v2/pro-analyst/pills → coverage_health.divergence_counts/comparable/divergent_symbols/newly_divergent +
14-day trend. System→Hermes Professional Analyst card shows the divergence line (aligned/divergent + the
divergent symbols with internal↔street). Advisory; no scoring/GO-WAIT change.
