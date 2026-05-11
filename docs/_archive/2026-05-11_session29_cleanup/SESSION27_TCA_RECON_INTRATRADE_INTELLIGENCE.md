# Session 27 — TCA, Broker Reconciliation, In-Trade Intelligence

**Date:** 2026-05-09
**Status:** Implemented and validated

## What Was Built

An intelligent open-trade management ecosystem for Alpaca PAPER trades covering:

1. **Broker Reconciliation** — Matches local DB paper trades against Alpaca paper positions/orders
2. **TCA / Execution Quality** — Computes slippage, fill quality, R multiples for entries/exits
3. **In-Trade Intelligence** — Due diligence engine evaluating 25+ factors on open trades
4. **Order Modification Proposals** — Admin-approved stop/limit/bracket change workflow
5. **Paper Outcome Analytics** — Strategy-level performance aggregation with low-sample guards
6. **Approval Flow** — Telegram commands + API endpoints for approve/reject/execute
7. **Dashboard** — Paper Trade Intelligence page with 5 tabs

## Safety Model

- Paper only — ALPACA_MODE=paper enforced at code level
- No automatic broker modifications — all changes require admin approval
- Fail-closed on uncertainty — stale quotes, ambiguous mappings, and missing data all block
- Risk gate called before every broker-facing execution
- Live trading gate verified before every execution
- All Alpaca keys redacted in output
- Execution endpoint refuses unapproved, expired, and non-paper proposals

## DB Schema

Migration: `sql/migrations/20260509_session27_tca_recon_intrade_intel.sql`

| Table | Purpose |
|-------|---------|
| `paper_broker_reconciliation_runs` | Reconciliation run metadata |
| `paper_broker_reconciliation_items` | Per-symbol reconciliation detail |
| `paper_execution_quality_events` | TCA events (entry/exit fill quality) |
| `open_trade_intelligence_snapshots` | In-trade intelligence snapshots |
| `open_trade_due_diligence_events` | Due diligence events (stop_near, adverse_news, etc.) |
| `paper_order_modification_proposals` | Stop/limit change proposals with approval flow |
| `paper_trade_outcome_analytics` | Closed trade outcome analysis |

## Scripts

| Script | Purpose |
|--------|---------|
| `paper_broker_reconciler.py` | Reconcile DB vs Alpaca broker state |
| `paper_execution_quality.py` | TCA / fill quality analysis |
| `open_trade_manager.py` | In-trade intelligence + modification proposals |
| `paper_outcome_analytics.py` | Closed trade performance analytics |

## API Endpoints (Session 27)

| Method | Endpoint | Purpose |
|--------|----------|---------|
| GET | `/api/v2/paper-order-modifications` | List modification proposals |
| GET | `/api/v2/paper-order-modifications/<id>` | Proposal detail |
| POST | `/api/v2/paper-order-modifications/<id>/approve` | Approve proposal |
| POST | `/api/v2/paper-order-modifications/<id>/reject` | Reject proposal |
| POST | `/api/v2/paper-order-modifications/<id>/execute` | Execute approved proposal |
| GET | `/api/v2/paper-outcome-analytics` | Closed trade analytics |
| GET | `/api/v2/paper-tca` | TCA events |
| GET | `/api/v2/paper-broker-reconciliation` | Reconciliation runs |
| GET | `/api/v2/open-trade-intelligence` | Open trade intel snapshots |

## Dashboard

Route: `/v2/paper-trade-intelligence`

Tabs: Open Trades, Modifications, TCA, Broker Recon, Outcome Analytics

## Telegram Commands

| Command | Action |
|---------|--------|
| `paper mods` | List pending modification proposals |
| `paper mod <id>` | Show proposal details |
| `approve paper mod <id> [reason]` | Approve a proposal |
| `reject paper mod <id> [reason]` | Reject a proposal |
| `execute approved paper mod <id>` | Execute approved proposal |
| `cancel paper mod <id>` | Cancel a proposal |

## Due Diligence Checks (25 factors)

1. Quote freshness 2. Bid/ask availability 3. Broker reconciliation
4. Price vs entry/stop/target 5. R multiple 6. MAE/MFE 7. ATR expansion
8. RSI extremes 9. VWAP/trend 10. Volume spike/fade 11. Catalyst validity
12. Adverse news 13. Positive catalyst 14. SEC/halt events
15. Market regime 16. Sector movement 17. Original thesis validity
18. Risk/reward ratio 19. Time in trade 20. Strategy exit rules
21. Min stop distance 22. Max risk expansion 23. R threshold
24. Multi-agent review need 25. Admin approval requirement

## Manual Run Commands

```bash
# Broker reconciliation
.venv/bin/python scripts/paper_broker_reconciler.py --dry-run --json

# TCA analysis
.venv/bin/python scripts/paper_execution_quality.py --all-open --dry-run --json

# In-trade intelligence scan
.venv/bin/python scripts/open_trade_manager.py --scan-open --dry-run --json

# Generate modification proposals
.venv/bin/python scripts/open_trade_manager.py --scan-open --create-proposals --dry-run --json

# Outcome analytics
.venv/bin/python scripts/paper_outcome_analytics.py --rebuild --dry-run --json
```

## Validation Results

- Broker reconciler: PASS (0 open trades, 0 issues)
- TCA: PASS (0 open, 3 closed analyzed)
- Open trade manager: PASS (0 open trades, no proposals)
- Outcome analytics: PASS (3 closed trades, all losses, low_sample_warning=true)
- All 9 new API endpoints return 200
- Dashboard route returns 200
- Execute endpoint correctly refuses nonexistent proposals
- Paper gate: BLOCKED/PAPER (6 reasons)
- Holdings: $1,189,457 unchanged

## Rollback Notes

- All tables are CREATE TABLE IF NOT EXISTS — safe to re-run
- Revert commit to undo all changes
- No existing scripts were replaced, only extended (api_v2.py, telegram handler)
- No crontab installed
- No holdings.json changes
