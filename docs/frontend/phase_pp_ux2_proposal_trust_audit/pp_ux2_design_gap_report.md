# PP-UX-2 Design Gap Report

## 1. Screenshot Findings

PP-UX-1 improved the card with sector/industry, strategy description, entry rationale,
approval blockers, and guided workflow. But the operator still cannot verify:
- Quote source and execution eligibility
- Strategy routing evidence
- Technical/backtest evidence completeness

## 2. Quote Trust Gap

The system has a provider hierarchy (Alpaca > Polygon > Finnhub > FMP > yfinance > Finviz)
but the UI does not show which provider was used. Finviz and yfinance are display-only
and never execution-eligible. The operator needs to know:
- Which provider supplied the current quote
- Whether that quote has bid/ask (execution-eligible) or just last_price (display-only)
- Quote age and staleness
- Market session status

## 3. Strategy Fit Gap

multi_setup_router.py evaluates all strategies and stores match evidence in
strategy_setup_matches, but the UI only shows the assigned strategy. The operator
cannot see: why recovery_watch won, which strategies were rejected, what YAML rules
passed/failed, or whether the assignment was a fallback.

## 4. Technical/Backtest Gap

Fib, ORB, EMA, VWAP, and backtest engines exist. But the card only shows TECH_MIXED
and RSI/ATR. It does not show Fib levels, ORB status, EMA alignment pass/fail,
VWAP status, or backtest sample quality.

## 5. Proposed Trust Audit Panel

Each card gets a collapsible Trust Audit section showing:
- Quote Trust: provider, execution eligible, age, session, status
- Strategy Fit: selected strategy, match score, alternatives, YAML rules
- Technical/Backtest: Fib, ORB, EMA, VWAP, backtest quality, missing sections
- Decision Readiness: approval allowed, blockers, evidence gaps

## 6. Rules

- PP-UX-2 is read-only reporting. No execution changes.
- Finviz/yfinance explicitly marked display-only.
- Approval remains blocked until execution readiness passes.
- Missing route audit explicitly flagged, not hidden.
