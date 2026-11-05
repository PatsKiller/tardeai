"""Market Risk Engine (DSN-20261031-market-risk-engine).

Deterministic, model-free market-level risk detection built after the 2026-10-30 selloff RCA
(docs/audits/MARKET_SELLOFF_ALERT_RCA_2026-10-30.md). Every threshold lives in
config/market_risk_policy.yaml; every output is advisory (MBI_BEHAVIOR = 0: no size, order or stop value
is ever produced). P0 ships the options-flow detector on data the system already stores.
"""
