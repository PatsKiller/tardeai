# Session Summary — 2026-06-04

Status:      HISTORICAL
as_of:       2026-06-04T21:38:20-04:00
Measured at: efcc51365 / not measured

**Doc name:** `docs/SESSION_2026_06_04_SUMMARY.md` (session index; links to detailed docs).
**Theme:** premarket proposal correctness → catalyst pipeline repair → Hermes catalyst integration → ops fix.
**Discipline:** paper only / live blocked; verify-first; backups per IRON RULE; all changes synced to Drive.

---

## Changes (in order)

| # | Change | Files | Status |
|---|--------|-------|--------|
| 1 | **Intraday quote-freshness alignment** — readiness no longer relaxes to 24h for intraday outside RTH, so it can't show ACTIONABLE_READY on a stale premarket quote the executor (flat 15-min) will reject | `proposal_execution_readiness.py` | ✅ |
| 2 | **Dead Telegram dedup fix** — `_db_query` never committed + ran the UPDATE through the fetch path (silently aborted txn); `last_alert_at` never persisted → identical cards every 2 min. Added `fetch="none"` write mode + rollback | `send_telegram_proposal_alert.py` | ✅ |
| 3 | **RTH-gate on intraday proposal GENERATION** — defer `momentum_scalp`/`gap_and_go` generation to regular hours so GO signals become approvable instead of expiring premarket (XOS/FOFO case) | `auto_proposal_generator.py` | ✅ |
| 4 | **Catalyst pipeline repair (Prompt #1)** — `catalyst_events` dead since 2026-04-27 (silent column-mismatch in inline write + never-scheduled classifier), starving `signal_fusion` (dark since 2026-05-11). Restored via Writer B (`news_to_catalyst.py`, scheduled); dedup via unique index; re-wired fusion; staleness monitor. **Correction→RESOLVED (Hermes §15.1): Writer A + the twin `sentiment_observations` bug are now both fixed & verified (#9); both writers run parallel.** | `news_to_catalyst.py`, `signal_fusion.py` (cron), `news_ingestion.py`, **new** `intel_table_staleness_monitor.py` (superseded by #10) | ✅ |
| 5 | **Hermes news bridge (Prompt #2)** — bridge Hermes ticker-level `momentum_catalyst` → `news_articles` → catalyst chain; Hermes wall intact (read-only on `hermes_*`) | **new** `hermes_news_bridge.py` | ✅ |
| 6 | **Tiered scalp cadence (Prompt #3)** — quota-free SCALP tier (`*/10 4-11` ET, SearXNG+DB only), operator-approved; external APIs kept low-cadence (NewsAPI/AlphaVantage quotas) | crontab | ✅ enabled |
| 7 | **Cron Drive-sync PATH fix** — hourly sync failed silently (`gog: command not found`; cron PATH omits `~/.local/bin`). Prepended absolute dir so the mirror stays current automatically | `sync-docs-to-drive.sh` | ✅ |
| 8 | **System-wide staleness scan (STEP 0)** — read-only sweep of every timestamped table; found a *family* of the same silent-failure class (schema-rename column mismatches swallowed by `except:pass` + unscheduled jobs). Death clusters ~04-27, ~05-10, ~05-11. Also caught an incomplete earlier fix | scan only | ✅ |
| 9 | **sentiment_observations twin-bug fix** — same class as #4 (`source/sentiment/score/raw_text` → `source_type/overall_sentiment/sentiment_score/raw_text_snippet`); frozen since 05-10. Fixed + Writer A verified end-to-end (both catalyst writers now genuinely parallel) | `news_ingestion.py` | ✅ verified |
| 10 | **System freshness & silent-failure monitor** — registry-driven (10 entries: fresh / empty-vs-input / cron-logfile); SIEM + Telegram P0/P1; narrow safe auto-fix (allowlist of idempotent DB-only re-runs, capped, always logged+escalated, never schema/trading writes); weekday-aware. Supersedes intel monitor | **new** `system_freshness_monitor.py` | ✅ enabled |
| 11 | **Sentiment lane repoint** — `signal_fusion` read producerless `catalyst_sentiment_analysis` (sentiment_score stuck 0.5); repointed to now-flowing `sentiment_observations`. Fusion now on 3/5 lanes (was 2/5). Verified: RTX 0.5→0.567, sentiments 0→3. Dormant-subsystem decisions recorded (Hermes §17): social_mentions + market_ohlcv_bars deprecate; learning batch stays asleep | `signal_fusion.py` | ✅ verified |
| 12 | **Watchdog fail-test (Hermes §18)** — forced P1 through real `run()`: detect → SIEM (urgent) → auto-fix (capped 2, escalates-on-success) → Telegram accepted (both chats) → **delivered to operator device (confirmed verbatim)**; `*/20` cron confirmed firing (12:00). Test artifacts cleaned. Out-of-band link proven | (verification) | ✅ PASSED |
| 13 | **Watch-the-watchman dead-man's switch** — monitor writes heartbeat on completed run; independent self-contained `freshness_watchdog_heartbeat.py` (`*/30`) pages P0 if heartbeat >70m stale. Verified (backdated 90m→P0 SIEM 469, restored→OK). Off-host terminus env-gated (`FRESHNESS_HEARTBEAT_PING_URL`) | **new** `freshness_watchdog_heartbeat.py` + `system_freshness_monitor.py` | ✅ enabled |
| 14 | **Research lane revived** (operator-approved) — scheduled `research_insight_extractor.py` (keyword, DB-only, frozen since 2026-04-27 unscheduled); reads now-flowing news_articles + catalyst_events → `research_insights` → fusion research lane. Verified: 200 new (200 existing preserved), SCHD research_score 0.24, **fusion 3/5 → 4/5**. Added to monitor registry (11 entries) + safe-auto-fix allowlist | `research_insight_extractor.py` (cron), `system_freshness_monitor.py` | ✅ verified |
| 16 | **Research Topic Registry + v3 management modal** — `owner` column on `topic_monitor` (tradeai\|hermes\|shared); GET `/research-topics/registry` + guarded POST upsert/toggle/delete (via existing `admin_write` → `admin_audit_log`); `topic_ingestion` filters `owner IN (tradeai,shared)`; new `ResearchTopicsModal.tsx` (add/edit/delete/pause + keywords + owner map) wired into IntelligenceHub. Backend verified end-to-end (preview→confirm→audit→delete); v3 build clean. **Hermes pickup now WIRED** (`hermes_topic_monitor_bridge.py`, cron 30 7): enqueues owner IN (hermes,shared) → staged `hermes_research_intelligence` (topic_research); symmetric to topic_ingestion (tradeai,shared) → **shared = co-owned by both** (answer to "can two own the same topic"). Verified (staged hermes#719/720, dedup holds). **Bridge reconcile-then-enqueue: stamps `topic_monitor.last_searched` from Hermes's actual COMPLETION (promotion) time, not enqueue** (verified: promote→reconcile moved trust_estate to completion time). **UI screenshotted (Playwright) + live-server (:7777) smoke test 7/7 green** (GET registry → upsert preview→confirm → toggle → delete, all via the running stack). See `RESEARCH_TOPIC_REGISTRY_2026_06_04.md` | `api_v2.py`, **new** `ResearchTopicsModal.tsx` + `hermes_topic_monitor_bridge.py`, `IntelligenceHub.tsx`, `topic_ingestion.py`, schema | ✅ verified |
| 20 | **Editable ATM + proposal controls — PAPER-ONLY, GATE-INTERLOCKED** (#2 arm-execution, scoped safe). Built+proved the hard interlock FIRST (`live_trading_interlock.py`, fail-closed): live accounts → 403 until `live_trading_allowed`; paper writable. ATM state control (paper), risk-limit editor (atm_config + IRON-RULE backup), proposal approve/adjust/edit — all via admin_write guard. v3 TradingHub "ATM Controls" tab: gate banner, account cards (4 live 🔒, alpaca writable), proposal actions, Schwab readiness checklist (NOT READY — broker_confirm_schwab missing). NO live-money switch wired. Server hot-reload stalled mid-edit → restarted (MainPID 2045519). See `ATM_PROPOSAL_CONTROLS_2026_06_04.md` | `live_trading_interlock.py`, `api_v2.py`, **new** `ATMControlPanel.tsx`, `TradingHub.tsx` | ✅ verified |
| 19 | **Hermes now auto-researches held positions (all 6 accounts) + open proposals 24/7** — closed the gap where Hermes only researched closed trades. `get_ticker_targets()` expanded: held (`trades`+`paper_trades` open) + open proposals prioritized w/ 24h re-research window, then closed-trade reflection; CUSIP filter excludes Schwab bond IDs. **Account-agnostic** — no hardcoded accounts; new positions/accounts auto-included on add, auto-dropped on sell (verified all 6 accounts). Verified: ADBE held_position → VALIDATED 0.85 → COMMITTED id=788. Rides existing coordinator `*/15 --apply`. See `HERMES_POSITION_PROPOSAL_RESEARCH_2026_06_04.md` | `hermes_autonomous_loop.py` | ✅ verified |
| 18 | **Watchdog layer 3 (in-network) + admin token armed + watch-mode** — restarted portfolio server → `ADMIN_WRITE_TOKEN` enforcing (UI-verified: tokenless 403, token→two-step confirm→applied+audited); in-network layer 3 live (`heartbeat_receiver.py` systemd user service + watchdog off-host-ping check, dead-man verified, partial/same-host); session moved to **let-it-run/catch-watch** (monitor+watchdog autonomous + paging; hourly analyst pass for first real catch, baseline alert id 515). See `CONSOLIDATION_CHECKPOINT_2026_06_04.md` | `portfolio_server`(restart), `heartbeat_receiver.py`, `freshness_watchdog_heartbeat.py`, `.env`, systemd user service | ✅ verified |
| 17 | **Rating alignment + LLM-stage definition + Intelligence Workflow tab + admin token** — (A) `hermes_news_bridge` now scores Hermes articles with `content_scoring` (same framework as TradeAI; verified new article relevance 0.13 from content_scoring vs old 0.7 confidence). (B) Defined LLM enhancement stages per system + target (most enhancement → Hermes; topic-curation move flagged). (C) NEW `IntelligenceWorkflow.tsx` React Flow tab in IntelligenceHub (mirrors Agents/Hermes; live `/api/v2/system/pipeline-health`; screenshotted). (D) `ADMIN_WRITE_TOKEN` configured in `.env` (staged; activate via server restart + browser token). See `INTELLIGENCE_RATING_AND_LLM_STAGES_2026_06_04.md` | `hermes_news_bridge.py`, **new** `IntelligenceWorkflow.tsx`, `IntelligenceHub.tsx`, `.env` | ✅ verified |
| 15 | **topic_ingestion root-caused + fixed** — dead 25 days because cron passed `--all` (invalid argparse arg → instant exit; `job_coverage_monitor` even cited it as the canonical "scheduled but produces nothing" example). Flag already corrected to `--use-llm-queries` in live cron; **proven** (ssdi run: 26 articles, last_searched unstuck 05-10→today); full 17-topic run launched (processing one-by-one; daily cron backstops the rest). **Cadence bumped 2×/week → daily** (`0 9 * * *`; YouTube/Google-RSS quota fine, Brave-independent). Topic freshness added to monitor registry (12 entries, `last_searched` check, detect+escalate — no auto-fix since it hits external APIs). **Refinements:** monitor uses **oldest-topic** (`agg=min`, 72h) so per-topic staleness isn't masked by one fresh topic; `topic_ingestion` now processes **oldest-first** (`ORDER BY last_searched ASC NULLS FIRST`) so the daily cron cycles all 17 fairly (full run only covers ~7/30min due to per-article LLM curation — manual run unstuck 7/17, 185 articles; daily cron grinds the rest over ~3 days) | crontab, `system_freshness_monitor.py`, `topic_ingestion.py` | ✅ verified |

---

## Cron jobs added/affected (all flock-guarded; server TZ America/New_York)
```
# Catalyst repair (#1)
45 6,12,18 * * *   news_to_catalyst.py
0  7,13   * * 1-5  signal_fusion.py --full (timeout 20m)
15 9      * * 1-5  intel_table_staleness_monitor.py --send
# Hermes bridge (#2)
40 6,12,18 * * *   hermes_news_bridge.py
# SCALP tier (#3, approved)
*/10 4-11 * * 1-5  hermes_news_bridge.py     # 04:00-12:00 ET, quota-free
*/10 4-11 * * 1-5  news_to_catalyst.py
# System freshness monitor (#10) — supersedes intel_table_staleness_monitor
*/20 * * * *       system_freshness_monitor.py --send --auto-fix
```

## Proof highlights
- 487+ catalyst_events flowing; existing 345 unchanged.
- `signal_fusion` un-starved: NOC catalyst_score 0.9 (5 catalysts) vs ZZZZ 0; `fused_signals` writing again (was stuck 2026-05-11).
- Hermes bridge: ABTS traced `hermes#302 → news_articles → catalyst_events(source=hermes) → signal_fusion 0.9`; re-run = 0 (dedup holds).
- Cron-sync PATH: `gog` NOT FOUND under minimal PATH before → resolves after fix.

## Backups (IRON RULE)
`backups/catalyst_repair_<ts>/` (news_ingestion, news_to_catalyst, signal_fusion, crontab) +
DB tables `bak_catalyst_events_<ts>` (345), `bak_fused_signals_<ts>` (2362).

## Detailed docs
- **Catalyst / bridge / tiered cadence:** `docs/HERMES_NEWS_TO_SCALP_CATALYST_INTEGRATION_2026_06_04.md` (§1–14: STEP 0 grounding, root-cause forensics, repair, bridge, tiered design).
- **Canonical:** `docs/project/Trade_AI_v12_Reference_Architecture.docx` (Session 2026-06-04 addenda: freshness/dedup, RTH-gate, catalyst repair, Hermes bridge + tiered cadence).
- **Inline:** `docs/MASTER_SYSTEM_DOCUMENTATION.md` (lifecycle note, alert section, catalyst companion pointer).

## Dormant-subsystem decisions (Hermes §17)
- **Sentiment lane** → built (repointed to `sentiment_observations`). ✅
- **`social_mentions`** → **deprecate** (no producer; fusion reweights for it). Left off, not monitored.
- **`market_ohlcv_bars`** → **deprecate/defer** (consumers dormant; only a rarely-hit volume fallback live). Left off.
- **Learning/self-improvement batch** → **stays asleep** (operator-approved propose model, but high bar at low trust). Revive insight/shadow-only if ever; never auto-apply.

## Open follow-ups (flagged, not done — out of scope this session)
- Keyword classifier under-matches (~94% `other`) — candidate for LLM classifier.
- `signal_fusion` `confidence × impact_score` over-weights weak catalysts (scaling fix).
- `signal_fusion --full` heavy at 2,714 symbols — consider `priority_only` cadence.
- ~~`research_insights` stale~~ **REVIVED (2026-06-04):** `research_insight_extractor.py` scheduled; fusion now 4/5 lanes; in monitor registry. (Of the 4 dormant subsystems: research revived, sentiment built, social + ohlcv deprecated, learning asleep.)
- Telegram proposal dedup is purely time-based (state changes suppressed within 30-min window) — optional state-aware enhancement.
- ~~**Watch-the-watchman**~~ **DONE (2026-06-04):** `system_freshness_monitor` writes a heartbeat on each completed run; independent self-contained cron `freshness_watchdog_heartbeat.py` (`*/30`) pages P0 if it goes >70m stale (verified: backdated 90m→P0 SIEM, restored→OK). Off-host terminus wired via env `FRESHNESS_HEARTBEAT_PING_URL` (set the URL to activate). See Hermes §18.

---
*All changes applied to live code + live Postgres `trade_ai` on 2026-06-04 with backups; docs synced to Drive (Trade_AI_Docs_v2), hash-verified.*
