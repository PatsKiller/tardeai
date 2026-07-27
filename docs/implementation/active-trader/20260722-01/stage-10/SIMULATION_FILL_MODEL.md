# Simulation Fill Model — Stage 10
Partial fills first-class: filled_qty accumulates, avg_fill = size-weighted mean, remaining tracked;
final or remaining<=0 -> FILLED. Late fill after a terminal state is ignored (no phantom exposure).
Deterministic (scripted fills) → replay-equal. Protection modeled separately (PENDING/CONFIRMED).
