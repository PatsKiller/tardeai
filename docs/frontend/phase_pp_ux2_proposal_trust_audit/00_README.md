# PP-UX-2 — Proposal Trust Audit

**Status:** COMPLETE

## Purpose

Adds quote trust, strategy fit, and technical/backtest audit visibility to paper
proposal decision packets. Proves whether quote source, strategy assignment, and
evidence pipeline are actually working for each proposal.

## New Scripts

- `scripts/proposal_quote_trust.py` — Pure function classifier. Marks Finviz/yfinance
  as display-only, Alpaca/Polygon with bid/ask as execution-eligible, and flags stale quotes.
- `scripts/report_proposal_strategy_fit_audit.py` — Read-only report showing strategy
  routing evidence: which strategies matched, why one was selected, YAML rule pass/fail.
- `scripts/report_proposal_technical_backtest_audit.py` — Read-only report showing
  technical snapshot, Fib, ORB, EMA, VWAP, and backtest evidence status.

## API Changes (scripts/api_v2.py)

Each proposal now includes a `trust_audit` object:
- `quote_trust`: source, execution eligible, age, session, status, display_only_reason
- `strategy_fit`: match score, criteria met/failed, alternatives, mismatch warning, evaluations
- `technical_backtest`: grade, Fib/ORB/EMA/VWAP status, backtest quality, missing sections
- `readiness`: approval allowed, blockers, evidence gaps

Quote trust also adds a blocker when source is display-only or stale.

## Frontend Changes (PaperProposals.tsx)

- Compact trust summary on card: quote source + exec/display, strategy fit status
- Full Trust Audit panel in details drawer with 3 sections and all evaluations
- Strategy evaluation list showing all matched/rejected strategies

## Safety

- All read-only. No mutations, no broker calls, no trade creation.
- Finviz/yfinance explicitly marked display-only.
- Approval blocker added when quote not execution-eligible.
