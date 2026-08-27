# LLM Retry / Transient-Failure Rate Monitor (2026-06-08)
Tracks how often LLM calls hit transient failures + retry over time (network/provider health).

- `llm_net` now logs one incident per call that needed >=1 retry → data/runtime/llm_retry_events.jsonl
  {ts, kind (urlopen/post), error_type, retries, outcome (recovered|gave_up)}. Success-first-try logs nothing.
- `scripts/llm_retry_monitor.py` (daily 07:00, read-only, trims its own log): aggregates 24h/7d totals +
  14-day daily trend (incidents/recovered/gave_up + by error_type/kind) → data/runtime/llm_retry_health.json.
  status HEALTHY / ELEVATED (>=20 retries/24h) / DEGRADED (any gave_up/24h).
- v3: /api/v2/system/llm-retry-health + System→Hermes LLM Auth card "LLM resilience (24h)" line
  (status · retries · recovered · gave up).
- Verified with simulated incidents (3 → DEGRADED, recovered 2/gave_up 1); baseline now 0. As real transient
  blips occur, recovered counts show resilience working; gave_up>0 flags a real outage. Advisory infra; no scoring change.
