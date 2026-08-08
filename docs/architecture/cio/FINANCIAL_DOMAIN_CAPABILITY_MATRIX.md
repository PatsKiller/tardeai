# Financial Domain Capability Matrix

**Date:** 2026-08-08
**Phase:** P2.2 Deterministic Financial Model / Evidence Layer
**Status:** FROZEN — truthful assessment of all 16 financial domains

---

## 1. Capability Assessment

| Domain | Available | Canonical Data Source | Deterministic Model | Model Version | Freshness Policy | Health Dependencies | Known Gaps | Specialist Owner | Alex Usage |
|--------|-----------|----------------------|---------------------|---------------|-------------------|---------------------|------------|------------------|------------|
| Portfolio / Holdings | YES | `holdings.json`, `portfolio_snapshot.py` | `portfolio_snapshot.py` (v1), `holding_day_change.py`, `holdings_lifecycle.py` | portfolio-snapshot-v1 | 45s max age on snapshot | holdings.json liveness, price data freshness | None | Steph | Read holdings, day change, lifecycle stage |
| Allocation | YES | `holdings.json`, `redeploy_capital_book.py` | `redeploy_capital_book.py` (v1.1.0), `redeploy_decision.py` (v1.1.0), `redeploy_plan_engine.py` (v2.0.0), `redeploy_pro_forma.py` (v1.1.0) | phase_b_2.0.0 | 30m quote staleness, 5d plan staleness | holdings.json, mark_quotes DB | None | Steph | Read allocation state, plan readiness, pro forma |
| Performance | YES | `ticker_prices`, `ticker_dividends` | `redeploy_performance.py` (v1.2.0), `portfolio_benchmarks.py` | performance_1.2.0 | Real-time price feed | ticker_prices DB, instrument_facts cache | None | Steph | Read plan/leg performance, benchmark comparison |
| Attribution | **NOT_SUPPORTED** | N/A | No dedicated attribution engine | N/A | N/A | N/A | No Brinson-style or factor-based attribution. Excess return and benchmark comparison metadata exists in performance module but no standalone attribution model. | N/A | Report DATA_UNAVAILABLE |
| Risk | YES | `risk_management.json`, `stops.json` | `risk_snapshot.py` (v1), `research_intelligence_portfolio.py` | risk-snapshot-v1 | 45s max age | risk_management.json, stops.json, mark_quotes | No VaR engine (approximations only). Correlation limited to top 15. | Guardian | Read portfolio heat, beta, correlation, concentration |
| Cash / Liquidity | YES | `holdings.json`, `redeploy_capital_book.py` | `defense_cash_alternatives.py`, `redeploy_capital_book.py` | capital_book_1.1.0 | Real-time | holdings.json, market quotes | Cash alternative scoring is advisory only. No automated cash sweep recommendations. | Steph | Read deployable cash, stale plans, cash alternatives |
| Income / Dividends | YES | `ticker_dividends`, `ticker_prices` | `redeploy_income.py` (v1.0.0) | income_1.0.0 | 12M trailing window | ticker_dividends DB | Ordinary vs capital-gain split UNAVAILABLE from distributions. Indicated yield is yfinance fallback. | Steph | Read income projections, yield types |
| Tax / Lots / Account | YES | `schwab_cost_basis_lots`, `holdings.json` | `gain_guardian_tax.py`, `cost_basis_transfer.py`, `position_transfer_normalize.py`, `holdings_gain_guardian.py` | N/A (distributed) | Real-time | cost_basis DB, holdings.json | Lot opened_date is NULL on 100% of Schwab rows (UNVERIFIABLE). Bracket/IRMAA from external context only. | Ledger | Read tax annotation, lot honesty, account routing |
| Retirement | PARTIAL | Config + classification rules | `research_intelligence.py` (rule-based classification), `position_transfer_normalize.py` (Roth handling) | N/A | As configured | research_intelligence topics config | No retirement cash-flow model. No RMD calculator. No Social Security optimizer. No retirement projection engine. Topics are classification rules, not computation engines. | Ledger / Steph | Read retirement topic classification, Roth ladder transfer tracking |
| Watch / Re-entry | YES | `reentry_scorecard.py`, `reentry_decision_desk.py` | 8-stage deterministic checklist engine, composite gate engine | N/A | Real-time, operator-driven | mark_quotes, technical_snapshot, ticker_prices | No LLM on decision path. Operator must initiate. Max 2 re-entries per ticker per day. | Steph | Read re-entry readiness, near-trigger status |
| Rotation / Opportunity | YES | `rotation_ladders.py`, `sector_momentum.py` | RS20 rankings, sector momentum state machine | N/A | 300s (5m) max age on RS ladders | market_quotes, ticker_prices | Hermes sector pulse is LLM-assisted (not purely deterministic). Sector momentum requires debounce days to report transitions. | Steph | Read sector momentum, RS rankings, rotation signals |
| Fundamentals | YES | `symbol_profiles` DB, `yahoo_analyst_targets_history` | `symbol_profile.py`, `analyst_detail.py`, `analyst_rollup.py` | N/A | Real-time | symbol_profiles DB, yahoo data | Analyst consensus is Yahoo-sourced (third-party). No proprietary fundamental model. | Steph | Read sector, industry, analyst consensus |
| Catalysts | YES | `catalyst_events` DB | `catalyst_record.py` (confidence >= 0.3 verified) | N/A | 45-day window | catalyst_events DB | Catalyst confidence is LLM-assisted at source. Deterministic verification uses confidence threshold only. | Steph | Read verified catalysts per symbol |
| Technicals | YES | `technical_snapshot.json`, `indicator_confluence_cache` | `portfolio_technical.py` (v2.0), `indicator_snapshot.py` (v1) | N/A | 900s (15m) on indicator snapshot | Finviz API, technical_snapshot.json | Finviz is third-party data. Cookie-based RSI/SMA/ATR/Beta. Graceful degradation on API failure. | Guardian / Steph | Read RSI, SMA positions, MACD, ATR, price levels |
| Macro | PARTIAL | `sector_momentum.json`, classification rules | `research_intelligence.py` (regex-based classification), `sector_momentum_engine.py` | N/A | Nightly (sector momentum) | market_quotes, research_intelligence taxonomy | No yield curve model. No GDP/CPI forecast engine. No Fed funds rate model. Classification is regex-based, not quantitative. | Steph | Read macro classification, sector regime detection |
| Broker Reconciliation | YES | Schwab API, Fidelity manual sync | `broker_stop_reconcile.py`, `schwab_position_sync.py`, `fidelity_stop_sync.py`, `cost_basis_transfer.py` | N/A | Sync-on-demand | Schwab/Fidelity API availability | Read-only at broker — never places/cancels/replaces orders. Schwab lot dates all NULL (UNVERIFIABLE). | System | Read reconciliation status, source health |

---

## 2. Deterministic-First Rules

The following numeric computations must come from deterministic Trade AI services. LLMs may explain, compare, challenge, and summarize — but NEVER become the numeric source of truth:

| Computation | Deterministic Service | LLM Role |
|---|---|---|
| Portfolio weights / drift | `portfolio_snapshot.py` | Explain implications |
| Risk calculations (beta, correlation, heat) | `risk_snapshot.py` | Challenge assumptions, explain meaning |
| Performance / returns | `redeploy_performance.py`, `portfolio_benchmarks.py` | Compare, contextualize |
| Tax lots / wash-sale proximity | `gain_guardian_tax.py` | Explain tax implications |
| Retirement cash-flow | NOT AVAILABLE — report NOT_SUPPORTED | Report gap |
| Income / distributions | `redeploy_income.py` | Project scenarios |
| Allocation / capital book | `redeploy_capital_book.py` | Present tradeoffs |
| Sector momentum / rotation | `rotation_ladders.py`, `sector_momentum_engine.py` | Interpret signals |
| Re-entry readiness | `reentry_scorecard.py` | Flag near-trigger |
| Technical indicators | `indicator_snapshot.py` | Read context |
| Catalyst verification | `catalyst_record.py` | Assess impact |

---

## 3. Evidence Return Types

When a domain cannot provide data, the following typed states are returned:

| State | Meaning | Example |
|-------|---------|---------|
| `DATA_UNAVAILABLE` | Data source not available (API down, DB unreachable) | Finviz API failure → RSI DATA_UNAVAILABLE |
| `MODEL_UNAVAILABLE` | Computational model not implemented | Brinson attribution → MODEL_UNAVAILABLE |
| `STALE` | Data exists but exceeds freshness threshold | Snapshot older than max_age |
| `CONFLICTED` | Multiple sources disagree | Schwab position vs holdings.json mismatch |
| `NOT_SUPPORTED` | Domain not implemented in Trade AI | Retirement cash-flow projections |

These states are used by specialists and Alex to truthfully report what's available — not fabricate or guess.

---

## 4. Specialist ↔ Domain Mapping

| Specialist | Primary Domains | Domain Status |
|---|---|---|
| **Steph** (Wealth Advisor) | Portfolio/Holdings, Allocation, Performance, Income, Watch/Re-entry, Rotation, Fundamentals, Catalysts, Technicals, Macro | All operational |
| **Guardian** (Risk Critic) | Risk, Technicals | All operational |
| **Ledger** (Tax Specialist) | Tax/Lots/Account, Retirement | Tax operational; Retirement PARTIAL |
| **Alex** (CIO) | All domains (synthesis) | Reads all available; truthful about gaps |

---

## 5. Known Gaps Summary

| Gap | Severity | Impact | Mitigation |
|-----|----------|--------|------------|
| No attribution model | Medium | Cannot decompose returns into allocation/selection/interaction effects | Report MODEL_UNAVAILABLE; use excess return metadata from performance module |
| No retirement cash-flow model | Medium | Cannot project retirement income or RMD optimization | Report NOT_SUPPORTED; operator provides external projections |
| No RMD calculator | Medium | Cannot compute required minimum distributions | Report NOT_SUPPORTED |
| No Social Security optimizer | Low | Cannot recommend optimal claiming age | Report NOT_SUPPORTED |
| No VaR engine (approximations only) | Low-Medium | Risk numbers are approximations, not statistical VaR | Report as risk_snapshot approximations, not VaR |
| No yield curve model | Low | No term structure analysis for fixed income | Report NOT_SUPPORTED |
| Lot dates NULL (Schwab) | Medium | Cannot determine short-term vs long-term gain status for all positions | Report UNVERIFIABLE for affected positions |
| Ordinary vs capital-gain split unavailable | Low | Income projections mix distribution types | Report income_type=UNAVAILABLE for splits |

---

## 6. Version and Change Policy

Each deterministic model carries a version tag. Changes to model logic require:
1. Version increment (semantic)
2. Operator review (for material changes)
3. Evidence of correctness (backtest, reconciliation)
4. Documentation of assumptions changed
5. No silent override of prior versions
