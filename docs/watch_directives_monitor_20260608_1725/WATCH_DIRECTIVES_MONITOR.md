# Watch-Directive Hits + Promotions Monitor (2026-06-08)
- scripts/watch_directives_monitor.py (daily 06:20, read-only): snapshots active directives, hits 24h/7d by
  surfaced_by (trade_ai/hermes/operator) + promotion_status (PROMOTED/STAGED_FOR_REVIEW/MONITORED_NO_QUALIFY/
  REGISTERED_NO_TECH), promotions, watchpool-from-directives, Hermes staging backlog, servicing staleness →
  data/runtime/watch_directives_history.json (90d) with deltas + status (ACTIVE/IDLE/STALLED).
- STALLED if an active directive isn't serviced in 24h or Hermes staging backlog >=25 undrained.
- Baseline: 1 active directive, 3 hits/24h (operator 2, hermes 1; PROMOTED 1, STAGED 1, MONITORED 1),
  2 promoted, 0 staging backlog, status ACTIVE.
- Surfaced: /api/v2/watch-directives -> health (status + by_status + 14d trend); System->Hermes Watch
  Directives card "servicing" line. Advisory; no scoring/trade change.
