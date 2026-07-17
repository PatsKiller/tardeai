# Home v2 — The Command Brain (2026-07-17)

Commits `50fd3de0..b7fc3391`. The operator's stated identity for the page: "the command
center brain — the page that needs all the information on it." Reference composition
(operator-supplied Finviz screenshots) delivered as Row 1: Market Movers · Your Book ·
Major News. Diagnosis + click map + census: `docs/_findings/home_v2_diagnosis_2026-07-17.md`.

## WS-A — Market Movers
`scripts/finviz_market_movers.py`: 10 signal screens (gainers/losers/new-high/new-low/
unusual-vol/most-volatile/most-active/earnings-before+after/insider-buying) through the
PROVEN Elite export path with the GLOBAL `finviz_throttle` — one throttled GET per signal,
top-15 rows → `market_movers` (7-day retention) + 17KB snapshot. Cron `*/12 9-16 weekdays`.
`/api/v2/market-movers`: ETag + memo, held ●/watch ○ flags server-side, ~4KB gz.
Board: signal chips FILTER in place; held→watch-desk routing, unknown→Finviz (noopener);
capture provenance in header; unavailable signals render error chips — never synthesized.
The 10-15min capture cadence IS the design (decision desk, not a streaming feed).

## WS-B — The Book Treemap
`/api/v2/portfolio/book-map`: holdings × sector (symbol_profiles; missing → "Unclassified",
visible never dropped) × stop overlay (same risk pass as the Risk hub), 1.5KB ETag.
`BookTreemap`: dependency-free squarified layout (~40 lines — no new chart lib), area =
Value | Day-$-impact toggle, group = Sector | Account, fill = `heatRamp()` (shared exact
stops in watchTokens: −3% deep red → 0 slate → +3% deep green), red ring = stop TRIGGERED,
amber ring = unprotected ≥$10k, hover card (value/weight/day$/account/stop), click →
holding drill, legend + full-Portfolio link.

## WS-C — Major News
`/api/v2/news/symbol-headlines`: `news_articles` filtered through `news_symbol_guard` ONLY;
guard-rejected count reported; honest empty state ("silence is stated, never padded").
Grid: 24 heat cells ordered by |day %|, big movers get the highlighted border; modal =
source-domain chip · headline · relative time → outbound noopener links + action footer
(security card / watch desk / risk) + ingest freshness line.

## WS-D — Plain English + everything clickable (P0)
`lib/homeLabels.ts`: STATE_LABELS dictionary, `plain()`, `runLabel()` ("0400 2026-07-17" →
"4:00 AM scan · Jul 17"), `count()` (4.0→4, applied in RiskGauge for unit=''), 
`thresholdSentence()` ("Heat 8.9% — above your 5% ceiling"), `plainAlert()` rewrite rules
(journal-sync/repriced/agent-backlog/kill-switch classes) with the raw-chip fallback for
unknown shapes. Raw strings ALWAYS in tooltips. D3: transfer-distorted period %s (the Roth
+101.92% class) render "n/a · transfers" in BOTH perf-cell renderers, raw in tooltip.
D4: complete click map (17 element classes, findings table) — stops→risk?symbol,
winners/weekly→portfolio?symbol, recovery→risk?symbol, movers/treemap/news as above.

## WS-E — Polish
New components 100% watchTokens. Stated debt: 59 legacy hex refs in HomeHub (full
conversion deferred — no half-coats), `/api/v2/portfolio/performance` at 98KB (AT the
100KB poll budget line; split to summary on next growth).

## Self-scored maturity
| Section | Score | One line |
|---|---|---|
| Market Movers | 4 | live, throttled, filtering; cross-wiring to pullback triggers is a rail flash TODO |
| Book Treemap | 4.5 | full reference behavior incl. overlays/toggles; GG dots post-promote |
| Major News | 4 | guarded modal + actions; Stage-idea verb deferred (watch-desk route covers) |
| Plain English | 4.5 | dictionary + alerts + n/a-transfers; unknown states visibly raw |
| Clickability | 5 | click map complete, zero unverified rows |
| House style | 3.5 | new surfaces tokenized; legacy hex debt stated (59) |

## Gotchas
- New quick signals: add to SIGNALS in finviz_market_movers.py — the export URL pattern is
  the only Finviz surface allowed (throttle + Elite cookie; no scraping).
- heatRamp is THE ramp — any new heat surface imports it, never re-derives colors.
- market-movers cron uses cd + flock (cron entries WITHOUT cd broke twice today — check).
