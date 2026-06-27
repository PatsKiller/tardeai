# TradeInView Gap Audit — 2026-06-27

Baseline audit vs TradeZella/TradesViz-style spec. See `TRADE_IN_VIEW_IMPLEMENTATION_PLAN.md` for delivery status.

## Maturity (post-implementation)

| Area | Before | After this pass |
|------|--------|-----------------|
| Branding / module | Journal (fragmented v2/v3) | **TradeInView** at `/v3/journal` + `/v3/trade-in-view` |
| Exit intelligence | Backend only | **Exit Intel tab** + APIs |
| Behavioral | Tags only | **Behavioral tab** (tilt, streaks, mistake $) |
| Zella score | None | **Composite score** on Analytics |
| Trade detail | Split v2/v3 | **Unified TradeInViewDetail** drawer |
| Table log | Cards only | **Cards + sortable table** (13 cols, expandable) |
| Saved filters | None | **DB-backed saved views** |
| CSV import UI | Manual file drop | **Import tab** + API |
| Manual entry | None | **Manual entry panel** |
| Export | Print only | **CSV export** |
| Options journal | Separate hub | **Options summary lane** + link to Options Hub |
| MFE backfill | 40/132 | `backfill_trade_in_view_mfe.py` |

## Still open (P5–P6)

- Multi-leg options grouping + greeks P&L attribution in journal
- Attachments (screenshots, voice)
- Tick-by-tick replay
- Monte Carlo / pivot-grid custom reports
- Session recap templates (pre-market plan vs actual)
- Morning Brief auto-task on tilt (hook stubbed via reminder API)
- Tax wash-sale export (use Tax hub; journal CSV is realized P&L only)

## Data hygiene targets

- Annotation coverage: 40% → target **80%** (bulk-suggest + reminder buttons in UI)
- Emotion tags: 4 reviews → tag campaign via unified detail drawer
- Bar MFE: run `scripts/backfill_trade_in_view_mfe.py` after deploy