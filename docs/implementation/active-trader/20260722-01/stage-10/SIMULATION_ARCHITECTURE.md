# Simulation Architecture — Stage 10
`scripts/active_trader/simulation.py`. BrokerSim (in-process, no network; behavior scripted for
reproducibility): submit(accept/reject/unreachable/idempotent), fill(partial/full+avg),
cancel(pending/confirmed), protect. Order states incl. BROKER_UNREACHABLE, PENDING_CANCEL/REPLACE;
TERMINAL set; late fill after terminal ignored. Excluded brokers: snaptrade/fidelity/tastytrade.
No requests/http/trade-context references (test-enforced).
