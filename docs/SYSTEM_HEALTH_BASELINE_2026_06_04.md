# System Health Baseline — 2026-06-04 (post catalyst/signal/watchdog work)

Status:      HISTORICAL
as_of:       2026-06-04T20:44:22-04:00
Measured at: efcc51365 / not measured

**Purpose:** the "where does everything actually stand" snapshot the freshness monitor is judged
against going forward. Read-only; nothing changed to produce it. Numbers are live from Postgres /
the scripts on 2026-06-04.

---

## 1. Signal health — `signal_fusion`, lanes live now

Fusion blends 5 lanes. Current status: **4 of 5 live** (research revived later 2026-06-04; only the
deprecated `social` lane is dark).

| Lane | Status | Source |
|------|--------|--------|
| catalyst | ✅ live | `catalyst_events` (repaired today; both writers parallel) |
| news | ✅ live | `news_articles` (fresh, ~100/day) |
| sentiment | ✅ live (today's repoint) | `sentiment_observations` (was `catalyst_sentiment_analysis`, producerless) |
| research | ✅ live (today's revive) | `research_insights` — `research_insight_extractor.py` scheduled (was frozen 2026-04-27, unscheduled); keyword, DB-only |
| social | ⛔ deprecated | `social_mentions` — no producer; fusion reweights for it |

**Worked examples:** RTX (`defense_thesis`) `catalyst 1.00 · news 0.204 · sentiment 0.633 · social
0 · research 0` → fused 0.586 (RTX had no research rows at snapshot time). After the research
revive, SCHD shows `research_score 0.24` (5 inputs) → **4 lanes contributing.**

---

## 2. Freshness registry — what's watched

`system_freshness_monitor` checks **12 entries**; **all currently fresh.**
Covered: `news_articles`, `catalyst_events` (+ empty-vs-news), `sentiment_observations`,
`research_insights` (added with the revive), `topic_monitor` (`last_searched` check, added with the
topic_ingestion fix), `fused_signals` (+ empty-vs-catalyst), `hermes_research_intelligence`,
`ticker_prices`, `cio_decisions`, drive-sync log. Kinds: fresh / empty-vs-input / cron-logfile.
Weekday-aware. (The `fresh` check now supports a per-entry `ts_col`, e.g. `last_searched`.)

**Not yet in the registry that arguably should be (honest gap):**
- Broader operational tables (e.g. `screener_run_health`, agent calibration, broker-recon) — the
  registry is currently **signal-pipeline-focused**; wider operational coverage is a deliberate
  future expansion. The original 5-week gap was an *unwatched* table, so "what's not watched" is
  itself a standing question — this list is the current known answer.

---

## 3. The 4 gates — live-trading gate (`live_trading_gate_v1`)

Policy is active; **live trading = blocked** (correctly). Today (2026-06-04):

| Gate | Required | Current | Status |
|------|----------|---------|--------|
| Validation days | ≥ 183 (6 mo, from 2026-05-08) | ~27 days | ❌ |
| Closed trades | ≥ 100 | 31 closed paper_trades | ❌ |
| Win rate | ≥ 55% | 41.9% (closed paper_trades) | ❌ |
| Profit factor | ≥ 1.30 | mixed by strategy (swing_breakout 5.87, momentum_scalp 2.55, dividend 0.16) | ⚠️ partial |

All strategies: `governance_state = PAPER_ONLY`, `live_eligible = False`,
reason *"Requires six months of validated paper results."*

**Did the catalyst/signal repairs move the gates? No — and that's expected.** The gates measure
*realized* paper performance over time; the repairs improve *signal quality feeding new trades*.
The payoff is forward-looking (better-quality trades accumulating toward the gate), not a
same-day metric change.

**Metric-scope note (honest):** the v3 dashboard shows "win rate 55.3% · 121" — a broader dataset
(the `trades` table / all accounts, ~349 rows) than the gate-relevant `paper_trades` (31 closed,
41.9%). The gate evaluates paper validation, so the 41.9%/31 figures are the gate-relevant ones;
the dashboard's 121/55.3% is a different scope, not a contradiction.

---

## 4. Open silent-failure / quality risks (status)

| Item | Status | Note |
|------|--------|------|
| `research_insights` stale (2026-04-27) → fusion research lane dark | **Resolved — revived** | `research_insight_extractor.py` scheduled (50 6,12,18); fusion now 4/5; added to monitor registry |
| `topic_ingestion` dead 25 days (`topic_monitor` last_searched 2026-05-10) | **Resolved (cycling)** | root cause = cron `--all` invalid flag; corrected to `--use-llm-queries`, proven (ssdi 26 articles); cadence 2×/wk→daily; monitor watches **oldest** topic (`agg=min`, 72h — won't mask per-topic staleness); engine processes **oldest-first** so the daily cron cycles all 17 fairly. Throughput-limited (~7 topics/30min run from per-article LLM curation) → ~3 days to fully cycle; monitor currently (correctly) flags P2 until it catches up |
| Keyword classifier ~94% `other` | Open | precision low; candidate for LLM classifier |
| Fusion `confidence × impact_score` over-weights weak catalysts | Open | scaling design fix |
| `signal_fusion --full` heavy at 2,714 symbols | Open | consider `priority_only` cadence |
| Learning/self-improvement batch | **Decided: asleep** | propose-with-governance, not woken at low trust |
| `social_mentions` | **Decided: deprecated** | no producer |
| `market_ohlcv_bars` (frozen 2026-05-07) | **Decided: deprecate/defer** | consumers dormant; only a rarely-hit volume fallback live |
| `catalyst_sentiment_analysis` empty | **Resolved** | fusion repointed to `sentiment_observations` |

---

## 5. Watchdog coverage — 3 layers

| Layer | Covers | Status |
|-------|--------|--------|
| `system_freshness_monitor` (`*/20`, detect→SIEM→Telegram→capped auto-fix) | silent data/pipeline failures | ✅ **live + fail-tested** (chain proven, Telegram reached operator device) |
| `freshness_watchdog_heartbeat` (`*/30`, independent) | the monitor itself dying (host alive) | ✅ **live + verified** (backdated 90m → P0 SIEM; restored → OK) |
| off-host ping (`FRESHNESS_HEARTBEAT_PING_URL`) | total-host death | ⛔ **wired but INACTIVE — URL not set** |

**Correction to two claims in the prompt:** (1) `FRESHNESS_HEARTBEAT_PING_URL` is **not set** —
layer 3 is wired, not live. (2) The box is **not air-gapped** — egress is open (`api.telegram.org`
HTTP 302, `googleapis.com` HTTP 404, 369 logged Drive syncs, confirmed Telegram delivery). So
layer 3 *can* work; it just needs a URL.

**One operator action for full coverage:** create an external dead-man check (e.g. healthchecks.io),
put its ping URL in `.env` as `FRESHNESS_HEARTBEAT_PING_URL`, then verify by pausing pings and
confirming the external service pages you. Until then, layers 1–2 are live; layer 3 is dormant.

---

## Bottom line
Catalyst pipeline repaired and flowing; fusion on 4/5 lanes (was 2/5, was effectively 0 catalyst
for ~5 weeks; only the deprecated social lane remains dark); the gate is honestly shut on time +
trade-count + win-rate; the watchdog stack is
live and tested for layers 1–2, dormant for layer 3 (needs a URL). The repairs improve forward
signal quality, not today's gate numbers. **Trust is earned from here by the monitor catching the
next *real* silent failure and paging honestly — not by anything in this baseline.**

*Read-only snapshot, live Postgres `trade_ai` + scripts, 2026-06-04. No changes made to produce it.*
