# Finviz & LLM Morning Control Plane

**Status: PASS**  
_Generated: 2026-06-29T10:57:58.064667_  

## Finviz

- screeners: **34** · cadence classes: {'scalp_fast': 3, 'scout_intraday': 3, 'swing_intraday': 4, 'swing_daily': 5, 'fundamental_daily': 9, 'income_weekly': 10, 'experimental_disabled': 0}
- scalp lane (targeted, NOT broad): ['momentum_scalp_primary_gappers', 'momentum_scalp_low_price_active_gappers', 'momentum_scalp_intraday_continuation']
- recommendations: {'keep': 28, 'reduce_cadence': 6, 'merge_duplicate': 0, 'disable_sunset': 0, 'promote': 0} · stale-screen warnings: 1

## Local LLM

- resident: ['gemma3:4b'] · backend: unknown · device: n/a
- blocked in market hours: ['gemma3:27b', 'gemma4-31b'] · embed timeouts today: 35
- enforcement: {'market_local_31b_27b': 'hard_block', 'paid_fallback': 'hard_fail', 'T3_cloud_unavailable': 'defer (never local-31B/paid)'}

## Cloud OAuth

- grok: calls=0 reachable=reachable auth_fails=0 paid_fallbacks=0
- chatgpt: calls=0 reachable=reachable auth_fails=0 paid_fallbacks=0

## Dashboard

- /api/health: {'http': '200', 'seconds': 0.002342} · threaded: True

## Scheduler

- 361 jobs (73 LLM) · market-window overload hours: {6: 14, 7: 13, 8: 15, 9: 16, 10: 13, 11: 12} · cloud-offload candidates: 23

## Findings

- [warning] 35 nomic-embed-text timeouts today — embed lane under contention

> Read-only morning control plane. No broker writes; operator/2FA untouched. LLMs advisory only.

