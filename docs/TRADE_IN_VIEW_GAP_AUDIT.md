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

## Shipped (P5–P6, 2026-06-28)

| Area | Delivery |
|------|----------|
| Multi-leg options | `options-summary` groups legs + book greeks; **OptionsJournalPanel** shows groups/open legs |
| Attachments | `journal_attachments` table + upload in **TradeInViewDetail** (screenshots) |
| Monte Carlo / pivot | **Advanced** tab + `/journal/monte-carlo`, `/journal/pivot` |
| Session recap | **Session** tab + `journal_session_recaps` + daily save API |
| Tilt Morning Brief hook | `journal_tilt_morning_hook.py` → `operator_review_queue` |
| Tax export | `?tax=1` on `/journal/export` (wash-sale flags from `schwab_cost_basis_lots`) |
| v2 deprecation | `/v2/journal*`, `/journal-analytics`, `/paper-journal` → `/v3/trade-in-view` |
| Annotation nudge | Weekday cron `journal_annotation_reminder.py` → Telegram |

## Shipped (Tagging Queue, 2026-06-28)

| Area | Delivery |
|------|----------|
| Tagging Queue tab | **Tagging Queue** — incomplete trades, oldest-first, filters, keyboard nav |
| Reporting audit | `/journal/reporting-audit` — coverage vs TradeZella/TradesViz spec |
| Bulk tag / skip | `/journal/tagging-queue/bulk-tag`, `/skip` |
| Config | `config/trade_in_view_tagging_policy.json` |

## Still open (future)

- Tick-by-tick replay (bar replay only today)
- Voice memo attachments
- Per-leg greeks P&L attribution (book-level greeks only)

## Data hygiene targets

- Annotation coverage: 40% → target **80%** (bulk-suggest + reminder buttons in UI)
- Emotion tags: 4 reviews → tag campaign via unified detail drawer
- Bar MFE: run `scripts/backfill_trade_in_view_mfe.py` after deploy