# Simulation P&L Report — Stage 10
compute_pnl: unrealized=(mark-avg_entry)*shares; total=unrealized+realized-fees; per account/symbol.
Mark unavailable -> unrealized/total None (never fabricated). Fees/slippage/MFE/MAE carried.
Tested (values + unavailable-mark). Aggregation by account/symbol/session is deterministic.
