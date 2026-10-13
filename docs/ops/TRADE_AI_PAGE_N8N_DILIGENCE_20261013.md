# Trade AI page — n8n diligence (host vs n8n)

Status: ACTIVE  
as_of: 2026-10-13 (America/New_York)  
Authority: Trade AI page diligence plan + live audit  
See also: `OBSERVER_ACTIVATION_STATUS_20261013.md`, `scripts/lib/n8n_momentum_lifecycle.py`, `docs/ops/TRADE_AI_SCALP_5MIN_2026-10-09.md`

## One-sentence version

n8n **coordinates and shadows**; the **host** owns Command Center Trade truth, GO/WAIT/NOGO production, underfill heal, CONFLICT resolution, Active Trader sessions, YouTube cookie storage, and STALE Telegram from the health agent.

## Ownership table

| Concern | Owner today | n8n role |
|---|---|---|
| Scanner slots 0400/0700/0900 + orchestrator 1730 | Host `continuous_runner` / cron `orchestrator-slot` | Do **not** bulk-cutover; midday already RETIRED |
| `trade_ai_cache.json` / `setup_run_summary` / `RUN_UNDERFILLED` | Host orchestrator + API | Shadow observe only |
| SharedMomentumCandidates projection write | Host (reconcile lane dry_run) | `momentum-cache-reconcile` stays **dry_run** until five-facts enrichment proven; then canary write only (no CONFLICT winner) |
| GO/WAIT/NOGO classification | Host Trade AI | Never choose GO vs WAIT |
| Active Trader journal / scalp sessions | Host cron/systemd (`active-trader-*`, motion) | `trade-ai-scalp-live` allowlisted but **cron authoritative** until per-lane cutover |
| Scalp GO Telegram body | Host communications | n8n may schedule/trigger; must not bypass senders |
| STALE flood (Finviz / orchestrator / proposals) | Host `system_health_agent` | Not n8n; host dedupe extended for `retry_disarmed` (12h) |
| YouTube cookies (`config/youtube_cookies.txt`) | Host CC Ops UI + human export | **MONITOR_ONLY** — never fetch browser cookies, never write the file |
| `tradeai-momentum-lifecycle-candidate` | Imported, **inactive** | Leave inactive until first-fire failure (relay metadata) is fixed and re-granted |
| `n8n-monitor-trade-ai` | **RETIRED** | Wave B emit = research-intake / watch-refresh only |

## MONITOR_ONLY watches (additive)

`scripts/lib/n8n_momentum_lifecycle.py` now projects completeness signals from host caches into the monitor snapshot and emits advisory findings (no repair):

| Signal | Finding item | Severity |
|---|---|---|
| `freshness_status` / `run_health_status` == `RUN_UNDERFILLED` | `trade-ai-scan:RUN_UNDERFILLED` | P2 |
| `count_integrity` != `RECONCILED` | `trade-ai-scan:COUNT_INTEGRITY_*` | P2 |
| Shared projection `status` == `PARTIAL` | `shared-candidates:PROJECTION_PARTIAL` | P2 |
| CURRENT_SESSION TradeAI rows with `passed_count==0` | `shared-candidates:FIVE_FACTS_ZERO_CURRENT_SESSION` | P2 |
| CONFLICT count ≥ 3 | `shared-candidates:CONFLICT_SPIKE` | P2 |

Authority remains `READ_ONLY_ADVISORY` / `MONITOR_ONLY`. Recovery intents stay empty unless separately admitted.

## Explicit non-goals

- n8n inventing a second orchestrator or resolving TradeAI↔AT CONFLICT
- n8n replacing Finviz credentials or YouTube cookies
- Re-arming `retry_disarmed` auto-heal without a grant
- Reactivating `tradeai-momentum-lifecycle-candidate` before relay/first-fire fix
- Bulk move of FULL orchestrator slots onto n8n

## Recommended n8n ladder (not this UI PR)

1. `momentum-cache-reconcile` → canary after five-facts enrichment  
2. `momentum-lifecycle-monitor` → live MONITOR_ONLY notify  
3. `trade-ai-scalp-live` → n8n scheduler of record (cron twin until lock proof)  
4. Ordered fan-out tick (Finviz → scalp → AT)  
5. AT → one-symbol TradeAI attach bridge  
6. Projection-age watchdog  
7. YouTube RED delivery via incident-router (check stays host; Ops upload stays host)

## Host STALE dedupe (this package)

`system_health_agent._escalate`: default 2h ESCALATION window; **12h** when `action_taken` starts with `retry_disarmed`, so disarmed autoheal does not re-page every 5-minute STALE poll.
