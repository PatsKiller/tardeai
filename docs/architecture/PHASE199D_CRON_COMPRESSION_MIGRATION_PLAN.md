# Phase 199D — Cron Compression & Migration Plan

Status:      HISTORICAL
as_of:       2026-06-04T22:40:47-04:00
Measured at: efcc51365 / not measured

Plan only. **No crons removed or modified in this phase.** Any change below requires explicit
operator approval before execution (later phase).

## Critical framing (read first)
The 31 "duplicate" scripts are overwhelmingly the **same script scheduled at different times**
(e.g. `run_scheduled_quote_refresh.sh` ×11 = market-hours intervals; `finviz_screener_runner.py`
×7 = different screeners/windows). **That is legitimate multi-cadence scheduling, not redundant
duplication.** Therefore "compression" here means **ownership consolidation** — grouping each
script's many cron lines under a single pipeline controller (199C/199E) that invokes it at the
required cadences — plus **visibility** in the v3 Queue Control Tower. It does **not** mean deleting
runs. `can_retire` is therefore **NO** for nearly all; the win is one owner + one log + one
disable command per pipeline, and no more "where is this scheduled?" ambiguity.

## Migration table (multi-scheduled scripts → owner pipeline)
| Script | cron× | Owner pipeline | Deps | Risk | Priority | Retire? | Approval? |
|--------|------:|----------------|------|------|----------|---------|-----------|
| `trade_ai_orchestrator.py` | 6 | market-pipeline | db,llm,tg,mkt | proposal-gen | **P0** | NO | YES |
| `process_watchlist_agent_jobs.py` | 4 | market-pipeline | db,llm,tg,mkt | proposal/agent | **P0** | NO | YES |
| `run_scheduled_stale_proposal_sweeper.sh` | 3 | market-pipeline | broker(paper) | proposal lifecycle | **P0** | NO | YES |
| `cleanup_stale_proposals.py` | 2 | market-pipeline | db | proposal lifecycle | **P0** | NO | YES |
| `atm_position_reconciler.py` | 2 | market-pipeline | db,broker(paper) | paper protection | **P0** | NO | YES |
| `alpaca_paper_reconciler.py` | 2 | market-pipeline | db,broker(paper) | paper recon | **P0** | NO | YES |
| `run_protection_pipeline.sh` | 2 | hermes-advisory | — | protection (paused) | **P0** | NO | YES |
| `catalyst_momentum_engine.py` | 3 | hermes-research | db,llm,broker | research+llm | **P0** | NO | YES |
| `trade_close_llm_analyzer.py` | 2 | after-close | db,llm,broker | llm | **P0** | NO | YES |
| `multi_tier_trade_reviewer.py` | 3 | after-close | db,llm | llm | **P0** | NO | YES |
| `system_health_alerts.py` | 2 | governance | tg | telegram | **P0** | NO | YES |
| `send_alert_digest.py` | 2 | after-close | db,tg | telegram | **P0** | NO | YES |
| `system_health_agent.py` | 3 | governance | db,tg,broker | telegram/health | **P0** | NO | YES |
| `run_scheduled_quote_refresh.sh` | 11 | market-pipeline | broker(paper) | data feed | P1 | NO | YES |
| `finviz_screener_runner.py` | 7 | market-pipeline | db | screeners | P1 | NO | YES |
| `run_scheduled_watchpool_alerts.sh` | 5 | market-pipeline | broker(paper) | alerts | P1 | NO | YES |
| `run_alex_daily.py` | 3 | market-morning | db,tg | morning brief | P1 | NO | YES |
| `finviz_enrichment.py` | 2 | market-pipeline | db | enrichment | P1 | NO | NO |
| `news_ingestion.py` | 3 | data-feed→market | db | feed | P1 | NO | NO |
| `news_to_catalyst.py` | 2 | data-feed→market | db | feed | P1 | NO | NO |
| `external_market_data_ingest.py` | 2 | data-feed→market | db | feed | P1 | NO | NO |
| `market_regime_collector.py` | 2 | data-feed→market | db | feed | P1 | NO | NO |
| `data_gap_resolver.py` | 3 | data-feed→market | db | feed | P1 | NO | NO |
| `hermes_news_bridge.py` | 2 | hermes-research | db,mkt | research bridge | P1 | NO | NO |
| `intel_auto_discovery.py` | 2 | hermes-research | db,tg | research | P1 | NO | NO |
| `run_scheduled_atp2_research_cycle.sh` | 5 | hermes-research | broker(paper) | research | P1 | NO | YES |
| `run_scheduled_a1a_check.sh` | 2 | governance | — | docs audit | P1 | NO | NO |
| `backup_secrets_state.sh` | 2 | portfolio-maint | — | backup | P1 | NO | NO |
| `backtest_history_snapshot.py` | 2 | governance | db | snapshot | P2 | NO | NO |
| `agent_router_cron.sh` | 3 | UNKNOWN→triage | — | agent routing | P2 | **operator decision** | YES |
| `agent_intelligence_cron.sh` | 3 | UNKNOWN→triage | — | agent intel | P2 | **operator decision** | YES |

## Priority bands
- **P0 (do first, approval required):** anything touching proposal generation, paper protection,
  LLM queue, or Telegram alerts. Group these under their owner pipeline first; they carry the most
  silent-failure risk if a schedule is dropped or doubled.
- **P1:** market data feeds, screeners, morning brief, Hermes research bridges, governance/readiness.
- **P2:** legacy/unknown (`agent_router_cron`, `agent_intelligence_cron` — need operator decision on
  whether still required), historical snapshots.

## Execution rules (for the later, approved migration phase)
1. Move one pipeline's scripts under its controller (199E), keeping the **exact same cadences**.
2. Comment (don't delete) the old cron lines; run controller + old in parallel for one cycle; diff outputs.
3. Only after a clean parallel cycle, remove the commented cron lines.
4. Never drop a schedule for a P0 (proposal/protection/LLM/Telegram) job without an explicit go.
5. The freshness monitor + watchdog (governance) stay untouched throughout — they are the safety net.

## Lock files
No true lock-file collisions (same lock, different scripts) were found — shared locks (e.g.
`screener_pm.lock`) are the SAME script across cadences, i.e. already-serialized multi-cadence runs.
These become a single controller-owned step.

---
*Plan only. No cron removed/modified. Approval-gated migration; P0 group first; cadences preserved.*
