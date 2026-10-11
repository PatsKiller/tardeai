# Retiring the `market_quote_snapshots` writes (cron L92 / L128) — plan, not executed

```
Status:      DRAFT (plan only; nothing in it is executed)
as_of:       2026-10-10T18:10:00-04:00
Measured at: branch n8nmat/broker-domains-q1 (base e8a4a6815 + n8nmat/consolidation-step1); live DB read-only
```

**Decision this serves.** Operator, 2026-10-10 ~17:45 ET, `CONSOLIDATION_PLAN.md` §D.7: "add a `latest_quote`
projection now; plan (do not execute) retiring `market_quote_snapshots` writes (L92/L128) after a soak". The
projection is built on this branch (`scripts/lib/data_broker/latest_quote.py`). This document is the plan for the
second half. Every step below that changes the crontab, a store or a writer is operator-only (AGENTS.md §17) and
needs its own grant; the cron freeze (inventory-row approval + crontab-write grant) applies to L92 and L128.

## 1. What exists today `[M]` 2026-10-10 (read-only SELECTs, served release crontab)

| Item | Fact |
|---|---|
| Second quote store | `market_quote_snapshots`: 5,596 rows / 107 symbols in the last 7 days; providers schwab 3,824, alpaca 1,771, yfinance 1 |
| Writer | `market_quote_provider.store_quote` — the only `INSERT INTO market_quote_snapshots` |
| Callers of the writer | `run_proactive_quote_refresh.py` (cron **L92** `45 7,10,12,13,16 * * 1-5 --mode incubator`, **L128** `*/5 9-15 * * 1-5 --mode pending`) and `proposal_execution_readiness.py:189` |
| What L92/L128 fetch | legacy `get_best_quote` (four-provider fan-out) per target; the target selector computes age and never filters on it (`select_quote_refresh_targets.py:47-60`) — 639 Schwab requests on 2026-10-09 (`API_OVERLAP_CONSOLIDATION.md` §2.1) |
| Readers | `incubator_proposal_promoter.py:788` (quote-age gate, MAP-5D), `lib/data_broker/reentry_enrichment.py:47-77` (**VWAP, spread, volume** — columns `market_quotes` does not carry), `paper_execution_quality_analyzer.py:113`, `select_quote_refresh_targets.py:55,123`, `defense_cash_alternatives.py:92` (dividend_yield / pe_ratio), `report_intelligence_flow_health.py:52` |

The reentry reader is the blocker for a naive retirement: it reads bid/ask-derived fields (spread, VWAP) that the
primary store does not hold. Retiring the writes without moving it would turn its spread/VWAP into "none".

## 2. Soak — what must be true before any retirement step `[I]` until measured

Run after this branch is promoted (quote-only mode live for the six callers in `CONSOLIDATION_PLAN` §D.6):

1. **Five market days** with `QUOTE_ONLY_MODE` unset (on). Measure per day: quote-only calls served from the store
   (`provider == "market_quotes"`) vs provider calls, and Schwab 429s in `health_agent_cron.log`,
   `auto_enrichment.log`, `proposal_enrichment.log` (baseline 34 × 429 in 7 days).
2. **No reader regression**: the incubator promoter's skip reasons (`no_price`, drift) and the proposal alert's
   `auto_stale_price_drift_*` rejections at the same rate ±20% as the five days before promote.
3. **`market_quotes` freshness held**: `latest_quote` envelope `stale == false` for held + pending-proposal names at
   every */15 check during RTH (the store L438 writes is the only thing quote-only callers now read first).

If any check fails: `QUOTE_ONLY_MODE=0` in the lane env restores the pre-change behaviour everywhere (the Data
Broker fallback goes dead again, as it was), and the retirement does not start.

## 3. Retirement steps (each its own grant; none executed)

| # | Step | Kind | Rollback |
|---|---|---|---|
| R1 | Move `reentry_enrichment` spread/VWAP/volume to the `active_trader_microstructure` / bars projections or to a quote-only read that carries bid/ask; move the incubator quote-age gate to `latest_quote` (`age_seconds`); move `defense_cash_alternatives` yield/PE to `market_quotes` columns (the writer already stores `dividend_yield`, `pe_ratio`) | code PR | revert |
| R2 | `select_quote_refresh_targets` / `report_intelligence_flow_health` read `latest_quote` | code PR | revert |
| R3 | Prove zero readers: `grep -rn "FROM market_quote_snapshots" scripts/` → only the archive-tripwire allowlist | measurement | — |
| R4 | Retire cron **L92** and **L128** (registry rows marked RETIRED in the same window, or the supervisor raises NO_OUTPUT — retire-batch-1 lesson) | crontab-write grant + inventory approval | restore the two lines from the archived crontab |
| R5 | `proposal_execution_readiness.py:189` stops calling `store_quote` (it is an execution-readiness path: propose-only, separate decision) | code PR, **operator** | revert |
| R6 | The table stays (never delete). Writes stop; `config/data_retention_policy.json` keeps its row; the table is renamed or archived only on an explicit §17 decision | operator | — |

**Expected effect** `[I]`: −2 cron lines; −~640 Schwab requests per market day from L128 alone; one quote store
for readers (`market_quotes` through `latest_quote`).

## 4. What this plan does not touch

`broker_trade_plan_gate.py` (propose-only, `CONSOLIDATION_PLAN` §D.6) and every order, stop or paper-submit path.
`check_fresh_quote` keeps the legacy fan-out because its callers need a real-time bid/ask.
