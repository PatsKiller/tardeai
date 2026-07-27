# RES (Resilience) Specification — Stage 9 (version res-1)
Components (weights, seed): vwap_hold 12, higher_low 12, reclaim_speed <=10, bid_replenish <=10,
integrated_ofi 12, tape_response <=10, spread_recovery 6, volume_continuation <=8.
Value clamped 0..100; confidence HIGH/MEDIUM/LOW by fraction of present components; INSUFFICIENT when
none present (value None). Missing-data handled per-component (None excluded). No lookahead; replay-equal.
