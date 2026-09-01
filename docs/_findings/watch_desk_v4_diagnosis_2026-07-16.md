# Watch Desk v4 — Phase 0 Diagnosis (2026-07-16, post-close)

Status:      HISTORICAL
as_of:       2026-07-16T17:06:11-04:00
Measured at: efcc51365 / not measured

Repo tip at session start: `bd8849cf` (prompt said 3adaaf4 — Engine Room v1 shipped in
between; its WS-1 topology item in the prompt's operator list is ALREADY DONE).
DB via trade_ai creds (prompt's `psql -U johnclaw` fails — role doesn't exist; recurring).

## 0.1 Token adoption census (page level, not rendered DOM)
93 raw hexes across the six pages (top: #22c55e×17, #60a5fa×10, #f59e0b×9, #ef4444×9,
#a855f7×8, plus the v2-era one-offs #2dd4bf/#a78bfa/#7dd3fc/#10a37f/#ffa726/#fbbf24).
Sub-10px fontSize: WatchlistHub 5×9px · WatchpoolHub 4×8+6×9 · SectorsHub 3×8+2×9 ·
PullbackMacdHub 2×9 (the prompt's "290×8px" was a rendered-DOM count including Card v4
internals — page-source population is smaller; same direction, saner scope).
ScreenerFindsHub ALREADY imports BB tokens (v3 work); `terminalHubChrome.ts` +
`terminalCardTheme.ts` exist as shared chrome — WS-A extends these, no parallel system.

## 0.2 Directive TTL
watch_directives active: 267 with ttl_days, 91 without. NOTHING enforces it for
directives (ttl_days only used in directive_promotion watchpool items + incubator
lifecycle). → WS-C2 adds expiry to Sunday hygiene (status='expired', visible fold).

## 0.3 Prefs pattern
No server-side prefs anywhere in api_v2. localStorage: used by 5 files
(HealthHub, ManualTosDesk, cardsV4, CentralIntelligencePages) BUT terminalUi.ts
deliberately REMOVED its localStorage override ("terminal density is the only shipped
chrome"). Verdict: not banned, but the operator works across desktop+phone (Tailscale)
— saved views go SERVER-SIDE (new tiny `ui_prefs` key/value endpoint), matching the
prompt's primary instruction.

## 0.4 Converted-α
`watch_candidate_events` already has `staged`/`proposed` booleans + alpha_21d/63d —
converted-α is a straight FILTER aggregate; no reconciler change needed for WS-D1.

## 0.5 Sector RS history
NO ohlcv bars for sector ETFs (market_ohlcv_bars empty for XLK/SPY...).
ticker_snapshot_daily has no close price (pct fields only). market_quotes has intraday
points for ETFs since 2026-05-05 (597 for XLK) → WS-E1 creates `sector_rs_daily`
(date, symbol, close, spy_close, rs) nightly + one-shot backfill from market_quotes
last-quote-of-day (~50 trading days: full 20d RS, honest partial 60d).

## 0.6 Rotation page overlap
RotationIntelligence.tsx = redeploy/rotation STRATEGY engine (pairs, review amounts,
cloud-LLM oversight on request, advisor changes). Sectors tab = passive monitoring
lens. Division of labor is real, not duplicate → E3 verdict: cross-link headers, no merge.

## 0.7 Pullback regime
pullback_macd_screener.py has NO regime read — the v3 chip reads the risk-regime API in
the UI. F1 stays UI-side reading the same endpoint as the WatchRegimeStrip (consistent).

## 0.8 Journal source keys — better than feared
There is no `trade_journal` table. The chain that exists TODAY:
journal_trade_reviews.paper_trade_id → paper_trades.{source_proposal_id, candidate_id,
lineage_source} filled 95/121 (79%) last 60d; `discovery_trace_id` 0/121 (never
populated); paper_trade_logger.py already threads a `_lin` lineage dict at insert.
→ F3 scope: find the writer(s) behind the 26 lineage-less fills (likely
alpaca_paper_adapter direct path), thread source_type/source_id (watch-candidate hop)
into discovery_trace_id at write. The dead historical hop remains dead (v3 canon).

## 0.9 Watchlist payload (post-v3, 1.03MB / 200 rows)
Largest per-row fields: dual_consensus_json 1446B + hermes_score_components 459B
(both LOCKED — Card v4 reads them), catalyst_url 343, trigger_source 312,
synthesis_narrative_snip 282, synthesis_data_i_doubt 273, setup_context 240,
synthesis_conflicts_snip 202. → B4 method: grep WatchlistCardV4 for actual field
usage; only never-rendered-in-card fields move behind ?full=1. <700KB is NOT
promised if Card v4 genuinely renders the bulk — honest census decides.
