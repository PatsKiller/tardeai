# Shadow Decision Engine — Stage 9
`scripts/active_trader/shadow_engine.py` (version shadow-engine-1). `run_shadow(inp)` →
prime, fire, res, rrs, runner, journal. DecisionInput is a point-in-time feature snapshot;
`contains_future_data=True` is refused (no lookahead). Everything deterministic → replay equality
(tested). No LLM, no broker, no order, no authority — shadow support only.
