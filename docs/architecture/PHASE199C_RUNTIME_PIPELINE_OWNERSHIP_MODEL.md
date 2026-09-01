# Phase 199C — Runtime Pipeline Ownership Model (target architecture)

Status:      HISTORICAL
as_of:       2026-06-04T22:39:43-04:00
Measured at: efcc51365 / not measured

Design only. Defines the seven target pipelines that the ~211 cron lines + 32 timers + 30 services
should consolidate into, each with a single owner, a clear trigger window, and explicit allowed /
prohibited writes. **No runtime change here** — this is the model 199D plans migration toward and
199E stubs as dry-run controllers. v3 is the canonical control surface (Queue Control Tower, 199F–H).

Global invariants for ALL pipelines: paper-only; **no live trading / no live Alpaca endpoint / no
Level 7**; no GO/WAIT/NO-GO or strategy-scoring mutation; protection workstream paused (observe-only).

---

## 1. tradeai-market-pipeline
- **Owner:** Trade AI core (Alex/CIO)
- **Trigger window:** market hours, gated by `market_day_gate.sh` (RTH; scalp window 04:00–12:00 where already configured)
- **Steps:** market feed checks · screeners (finviz) · proposal generation · paper eligibility · protection *verification* (read-only while paused) · advisory generation · paper-only submit/approval checks already authorized
- **Allowed writes:** `paper_trade_proposals`, `fused_signals`, screener tables, quote cache, paper eligibility flags
- **Prohibited writes:** live orders, holdings, GO/WAIT logic, strategy scores, broker mutation, Level 7
- **Dependencies:** Alpaca **paper** API, quote feed, DB, market-hours gate
- **Logs:** `logs/pipelines/tradeai-market-pipeline.log` (target) · today: per-script logs
- **SIEM:** proposal-gate failures, eligibility blocks · **Telegram:** new-proposal alerts (existing dedup)
- **QCT category:** `MARKET_PIPELINE`
- **Disable:** `systemctl --user disable --now tradeai-market-pipeline.timer` (target) / comment cron block
- **SLO:** a market-pipeline run each gated interval; failure → SIEM + no silent skip (freshness monitor covers staleness)

## 2. tradeai-after-close-pipeline
- **Owner:** Trade AI core
- **Trigger window:** after 16:00 ET (post-close), once daily
- **Steps:** journal reconciliation · MFE analysis · outcome reconciliation · advisory outcome scoring · learning snapshots · daily digest
- **Allowed writes:** journal/outcome tables, learning snapshots, digest artifacts
- **Prohibited writes:** orders, holdings, strategy scores, GO/WAIT, live anything
- **Dependencies:** DB, Alpaca paper (read), LLM (optional, for analysis)
- **Logs:** `logs/pipelines/tradeai-after-close-pipeline.log` · **SIEM:** reconciliation mismatches · **Telegram:** daily digest
- **QCT category:** `AFTER_CLOSE` · **Disable:** disable after-close timer / comment cron block
- **SLO:** one successful run per trading day; mismatch → SIEM

## 3. hermes-advisory-pipeline
- **Owner:** Hermes (advisory fleet)
- **Trigger window:** continuous / interval (advisory cache worker, observation checks)
- **Steps:** protection checks (observe-only) · advisory cache worker · Hermes second opinion · safe-view checks
- **Allowed writes:** advisory cache, Hermes advisory tables, SIEM
- **Prohibited writes:** **NO broker mutation**, no orders/holdings/stops, no GO/WAIT, no strategy scores, no live
- **Dependencies:** DB safe-views (read-only of Trade AI core), LLM
- **Logs:** `logs/pipelines/hermes-advisory-pipeline.log` · **SIEM:** advisory anomalies · **Telegram:** advisory escalations only
- **QCT category:** `HERMES_ADVISORY` · **Disable:** disable hermes-advisory-cache-worker.timer + related
- **SLO:** advisory cache fresh < interval; staleness → SIEM

## 4. hermes-research-pipeline
- **Owner:** Hermes (research fleet) — driven by `hermes_coordinator` `*/15`
- **Trigger window:** 24/7 (continuous research) + morning momentum window
- **Steps:** source discovery · backlog research · catalyst research · morning momentum-catalyst enrichment · high-LLM queue submission · held-position/proposal research (2026-06-04)
- **Allowed writes:** `hermes_research_intelligence` (staged→promoted), embeddings, `topic_monitor.last_searched` (reconcile), high-LLM queue submissions
- **Prohibited writes:** orders/holdings, GO/WAIT, strategy scores, live anything
- **Dependencies:** SearXNG, LLM (gemma/qwen), DB
- **Logs:** `logs/hermes_coordinator.log` + `logs/pipelines/hermes-research-pipeline.log` · **SIEM:** research stalls · **Telegram:** none (internal)
- **QCT category:** `HERMES_RESEARCH` · **Disable:** `touch` kill-switch / disable hermes timers
- **SLO:** hermes_research_intelligence write < 30 min (verified by freshness monitor)

## 5. llm-control-pipeline
- **Owner:** LLM control plane
- **Trigger window:** overnight batch window + on-demand queue scheduling
- **Steps:** high-LLM queue scheduling · model allocation · retry policy · failure drilldown
- **Allowed writes:** LLM queue tables (`high_llm_job_queue`, `deep_overnight_llm_queue`), results
- **Prohibited writes:** **no direct trading mutations**, no orders/holdings, no GO/WAIT, no strategy scores, no live
- **Dependencies:** Ollama (gemma3/qwen3), GPU, DB
- **Logs:** `logs/pipelines/llm-control-pipeline.log` · **SIEM:** queue backlog / model failures · **Telegram:** P0 queue failures
- **QCT category:** `LLM_QUEUE` · **Disable:** disable deep-overnight-llm window timer
- **SLO:** queue drains within window; failures retried per policy, then SIEM

## 6. governance-pipeline
- **Owner:** Governance / operator-readiness
- **Trigger window:** daily + periodic (readiness, health, snapshots)
- **Steps:** readiness reports · safety facts · maturity board · job health · repo/state snapshot · **freshness monitor + watchdog** (silent-failure detection)
- **Allowed writes:** report artifacts, `alert_events` (SIEM), state snapshots, heartbeat files
- **Prohibited writes:** orders/holdings, GO/WAIT, strategy scores, live anything
- **Dependencies:** DB (read), filesystem, Telegram, off-host ping (layer 3)
- **Logs:** `logs/pipelines/governance-pipeline.log` · **SIEM:** all silent-failure catches · **Telegram:** P0/P1 pages
- **QCT category:** `GOVERNANCE` · **Disable:** disable governance timer (NOT the freshness monitor/watchdog — those are the safety net)
- **SLO:** monitor `*/20`, watchdog `*/30`; dead-man's switch covers monitor death

## 7. portfolio-maintenance-pipeline
- **Owner:** Portfolio maintenance
- **Trigger window:** off-hours (backups 02:00, price cache, retention)
- **Steps:** backups (incl. encrypted offsite to Drive) · price cache refresh · tax/rebalance **read-only** analysis · retention
- **Allowed writes:** backups, price cache, retention pruning (per policy), read-only analysis artifacts
- **Prohibited writes:** orders/holdings, GO/WAIT, strategy scores, live anything
- **Dependencies:** DB, Drive (gog), filesystem
- **Logs:** `logs/pipelines/portfolio-maintenance-pipeline.log` · **SIEM:** backup failures · **Telegram:** backup failure only
- **QCT category:** `PORTFOLIO_MAINTENANCE` · **Disable:** disable portfolio-* timers
- **SLO:** nightly backup success; failure → SIEM + Telegram

---

## Standalone 24/7 services (NOT pipelines — long-running)
`tradeai-portfolio-server` (v3 API + UI), `hermes-gateway` (messaging), `heartbeat-receiver`
(watchdog layer 3). These are `24_7_SERVICE`; they stay as services, surfaced in the QCT but not
folded into a timer pipeline.

## Mapping (inventory → pipeline)
MARKET_PIPELINE + MARKET_MORNING + most DATA_FEED → **market-pipeline** (DATA_FEED feeds also research).
AFTER_CLOSE → **after-close**. HERMES_ADVISORY → **advisory**. HERMES_RESEARCH (+ catalyst/news feed)
→ **research**. LLM_QUEUE → **llm-control**. GOVERNANCE → **governance**. PORTFOLIO_MAINTENANCE →
**portfolio-maintenance**. UNKNOWN (108) → triaged in 199D (per-job operator decision).

---
*Design only — no runtime change. Each pipeline gets a dry-run controller skeleton in 199E and a
v3 Queue Control Tower category in 199F–H.*
