# Watch Desk v3 Phase 0 — 2026-07-16

Status:      HISTORICAL
as_of:       2026-07-16T15:19:37-04:00
Measured at: efcc51365 / not measured

| # | Item | Actual | Decision |
|---|------|--------|----------|
| 0.1 | Attribution chain | `watch_directive_hits`: directive_id/symbol/surfaced_at/**promoted/promotion_status** (staged hop native). `paper_trade_proposals`: **discovery_source, origin, source_table, source_record_id** (proposal hop linkable). `trade_journal`: **NO source/proposal columns → journal hop UNLINKABLE** | FLAG-BACK honored: score directive→staged and →proposal hops; journal attribution abstains (no fuzzy symbol+date matching) |
| 0.2 | Anchors | first_seen_price on **5,009/12,079** watchlist rows (41%) | anchored events score; others NOT_EVALUABLE — never guessed |
| 0.3 | Alert plumbing | alert_events INSERT w/ alert_uid dedupe (intel-monitor pattern) + telegram_alert router (P2 suppression exists; operator alerts ride a real alert class) | reuse both; batched sends |
| 0.4 | Row enrichment | watchlist_items carries **rsi, rvol, trend, first_seen_price/at** only — no ATR/52w/SMA columns | WS-C context uses available fields; ATR%/52w-distance omitted honestly. REUSE: server-side `_hermes_setup(rsi, trend)` (spec §8) already produces setup type + plain-English why — extraction requirement satisfied by calling it in the feed |
| 0.5 | Screener finds volume | origin_system='trade_ai_screener' nearly dead recently (last weekly counts: 12→19→17→1→0) | D1: widen Finds to screener+discovery+agent_discovery with CIO subset highlighted |
| 0.6 | Regime source | /api/v2/risk-regime/latest (regime_label) — already polled by shell | tab-level chip reads it |
| 0.7 | ToS | table+list endpoint exist; `imports/tos_watchlists/` never created; no ingest script; no CSV samples available | D2: create dir + honest "awaiting first export" copy; no fake instructions |
