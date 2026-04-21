# Phase 1 — Hardcoded Numbers Audit

**Date:** 2026-04-20
**Investigator:** Claude Opus 4.6
**Scope:** portfolio_ai_analyst.py, portfolio_signals.py, portfolio_stops.py, portfolio_rebalancer.py

---

## Pre-flight

| Check | Result |
|-------|--------|
| Git status | Tasks 1-9 uncommitted (expected) |
| portfolio_ai_analyst.py | 1,056 lines |
| Quick numeric scan | Found via broader search patterns |

---

## CRITICAL CONFIG (Produce Stale Financial Advice)

### 1. Dividend Yields Hardcoded in 3 Files

**portfolio_rebalancer.py lines 161-169: `HOLDING_YIELDS` dict**
- V: 0.83%, SCHD: 3.58%, CSWC: 10.5%, PFLT: 11.2%, ARCC: 9.5%, JEPI: 7.8%, JEPQ: 5.7%, DIV: 6.2%, plus 17 more tickers
- **Impact:** ALL income projections, rebalance recommendations, and dividend gap signals are wrong within 1 quarter

**portfolio_ai_analyst.py lines 589-590, 667, 716, 804, 806:**
- V yield 0.83%, SCHD 3.58%, CSWC 10.5%, PFLT 11.2%, JEPI 7-8% hardcoded directly in AI PROMPT TEXT
- **Impact:** AI gives advice citing specific yields that may be months stale

**portfolio_rebalancer.py lines 292-327: Bond yields**
- VCIT 4.8%, BND 3.4%, SGOV 5.2%, etc. hardcoded in recommendation strings
- **Impact:** Bond strategy advice wrong when rates move

**Risk: CRITICAL.** These values change quarterly. Currently 2+ months could pass before anyone notices.

### 2. Concentration Thresholds (portfolio_signals.py lines 105-107)

```python
EXIT_THRESHOLD = 15    # % of portfolio → EXIT signal
TRIM_THRESHOLD = 12    # % of portfolio → TRIM signal
DEFAULT_TARGET = 10    # % per-position target
```

**Impact:** These trigger BUY/SELL/TRIM action signals. If portfolio composition changes significantly, thresholds may be inappropriate.

**Risk: CRITICAL.** Directly produces user-facing action signals.

### 3. Stop Alert Distances (portfolio_stops.py lines 8, 117, 119)

```python
ALERT_DISTANCE = 3     # % from stop → alert
DANGER_THRESHOLD = 2   # % from stop → DANGER status
WARNING_THRESHOLD = 5  # % from stop → WARNING status
```

**Impact:** Alerts fire at fixed % distances regardless of position size. $500K position at 3% = $15K exposure.

**Risk: HIGH.** Alert timing affects real trading decisions.

---

## HIGH CONFIG (Affects Decision Quality)

### 4. Financial Targets

| Location | Value | Meaning |
|----------|-------|---------|
| portfolio_ai_analyst.py:421 | $25,000 | Roth sweet spot |
| portfolio_ai_analyst.py:422 | $50,000 | Roth upper target |
| portfolio_ai_analyst.py:715 | $28,000 | Annual dividend income target |
| portfolio_signals.py:103 | $28,000 | Dividend income target (duplicate) |
| portfolio_rebalancer.py:349 | 25% | Bond allocation target for IRA |
| portfolio_rebalancer.py:349 | 60/40 | VCIT/BND split |

**Note:** Roth targets ($25K/$50K) are already in `personal_situation.json` as `roth_target_sweet_spot` and `roth_target_upper`. The AI analyst references these dynamically in `_personal_context()` but ALSO has them hardcoded in the V strategy prompt. **Duplication creates drift risk.**

### 5. Technical Thresholds (portfolio_signals.py)

| Line | Value | Meaning |
|------|-------|---------|
| 416 | RSI > 70 | Overbought signal |
| 317 | 7 days | Earnings proximity window |
| 473 | 10% | 52-week low proximity |
| 440 | beta > 1.5 | Beta violation trigger |
| 440 | 3% weight | Minimum position weight for beta trigger |
| 424 | 50% | Non-functional stop distance |
| 432 | 5% | Stop proximity danger |
| 109 | 0.5% | Minimum position size gate |

### 6. Strategic Decisions

| Location | Value | Meaning |
|----------|-------|---------|
| portfolio_ai_analyst.py:779,813 | 30%, 50% | V trim scenario percentages |
| portfolio_rebalancer.py:381 | [10,20,30,50] | V scenario sell options |
| portfolio_rebalancer.py:437 | 25% | V concentration trigger |
| portfolio_rebalancer.py:112 | 5.0% | Rebalance drift trigger |

---

## MEDIUM CONFIG (Freshness Windows, Lookbacks)

| Location | Value | Meaning |
|----------|-------|---------|
| portfolio_ai_analyst.py:262,272 | 30 days | Personal staleness threshold |
| portfolio_ai_analyst.py:298 | 90 days | Historical context lookback |
| portfolio_ai_analyst.py:1008 | 30 days | AI section cache refresh |
| portfolio_rebalancer.py:177-186 | 20+ prices | Suggested ETF prices (stale immediately) |

---

## DATA-DERIVED (Already Correct, Leave Alone)

- portfolio_ai_analyst.py: V payment volume ($14T), net margin (52%), price targets ($325-350) — business facts embedded in prompt context
- Computed fields like `remaining = ceiling - income` 
- Loop counters, list limits (top 15, top 10)
- API parameters (timeouts, max_tokens, num_predict)

---

## Existing Config Patterns (Section E)

### Current config infrastructure:
- `config/manual_beta_overrides.json` — per-ticker real ticker mappings
- `assets/screeners.yaml` — Trade AI screener configuration
- `data/portfolios/state/personal_situation.json` — personal financial fields (Phase 8)
- `data/portfolios/state/stops.json` — stop levels per position
- No centralized `config/thresholds.json` or similar exists yet

### Precedent for runtime config:
- `personal_situation.json` is read at analysis time and injected into prompts
- `stops.json` is read by portfolio_stops.py per run
- `screeners.yaml` is loaded by Trade AI orchestrator

---

## Risk Assessment Summary

| Category | Count | Risk |
|----------|-------|------|
| CRITICAL (stale yields in prompts/calcs) | 30+ values across 3 files | Produces wrong financial advice NOW |
| HIGH (affects action signals/decisions) | 15+ values | Wrong BUY/SELL/TRIM recommendations |
| MEDIUM (freshness/lookback windows) | 5+ values | Suboptimal caching/warnings |
| LOGIC (leave alone) | 40+ values | No action needed |

---

## Architect Questions Answered

### 1. Most dangerous hardcoded values?
**Dividend yields in `HOLDING_YIELDS` dict (portfolio_rebalancer.py) and in AI prompt text (portfolio_ai_analyst.py).** These directly produce WRONG dollar amounts in income projections, rebalance recommendations, and V/SCHD strategy advice. Already stale if any dividend was changed since April 2026.

### 2. True configuration vs embedded business facts?
- **True CONFIG:** Yields, concentration limits, stop distances, RSI thresholds, Roth targets, drift triggers
- **Business facts (leave):** V payment volume, net margin, industry context
- **API constraints (leave):** max_tokens, timeouts, num_predict

### 3. Values already stale from Phase 8?
- Roth targets ($25K/$50K) are in `personal_situation.json` but ALSO hardcoded in `_v_strategy()` prompt — the hardcoded copies are stale if user updated via modal
- Dividend income target ($28K) — duplicated in signals.py AND ai_analyst.py with no single source

### 4. Values that should stay in code?
- API timeouts (120s, 90s)
- max_tokens limits (250, 1400, 1500)
- Format limits (top 15 holdings, top 10 ETFs)
- Position filter ($200 minimum)
- Ollama model parameters (num_ctx, num_predict)

### 5. Smallest safe extraction set?
**First pass (highest impact, lowest risk):**
1. Create `config/investment_thesis.json` with concentration limits, beta target, RSI threshold, stop distances
2. Move `HOLDING_YIELDS` from hardcoded dict to dynamic lookup from `dividend_calendar.json` or enrichment cache (yields already come from Finviz)
3. Remove duplicate Roth targets from prompt text (read from personal_situation.json instead)

### 6. Where should config live?
| Category | Location |
|----------|----------|
| Personal financial targets | `personal_situation.json` (already exists) |
| Investment thesis/thresholds | NEW: `config/investment_thesis.json` |
| Per-ticker yields | Dynamic from `dividend_calendar.json` or Finviz enrichment |
| Technical signal thresholds | `config/investment_thesis.json` |
| Stop distances | `config/investment_thesis.json` |

### 7. Semantic confusion in prompts?
**YES.** The V strategy prompt (lines 779-834) mixes:
- Hardcoded V yield (0.83%) which is the CURRENT dividend, not the gain
- Concentration % which changes every day with price moves
- Trim scenarios (30%, 50%) which are STRATEGIC choices

A user reading "V yields 0.83% vs SCHD yields 3.58%" could confuse dividend yield with total return. The prompt should clarify these are dividend yields only. Similar to the old "V concentration" vs "V gain" confusion noted in handoff docs.

---

## Recommendation: Smallest Safe First Pass

1. **Create `config/investment_thesis.json`** (~15 minutes)
   - concentration_exit_pct: 15
   - concentration_trim_pct: 12
   - default_target_pct: 10
   - beta_violation: 1.5
   - rsi_overbought: 70
   - stop_alert_distance_pct: 3
   - stop_danger_pct: 2
   - stop_warning_pct: 5
   - rebalance_drift_trigger_pct: 5.0
   - size_gate_pct: 0.5

2. **Wire `portfolio_signals.py` to read from thesis.json** (~30 minutes)
   - Replace the 6 hardcoded constants with config reads
   - Fallback to current values if config missing

3. **Wire `portfolio_stops.py` to read from thesis.json** (~15 minutes)
   - Replace 3 hardcoded constants

4. **Remove duplicate Roth targets from AI prompts** (~15 minutes)
   - Already in personal_situation.json; prompts should reference dynamic values

5. **Replace `HOLDING_YIELDS` with live data** (~1 hour)
   - Read from `dividend_calendar.json` or enrichment cache
   - Finviz already provides dividend yield per ticker

**Estimated total: 2-3 hours for first pass, covers all CRITICAL items.**
