# Watch Desk v2 — Truth & Directive Governance (P0 workstreams, 2026-07-16)

**Shipped this session:** WS-A1 (header truth) + WS-B1/B2/B4 (directive governance). Diagnosis (all 10 items answered): `docs/_findings/watch_desk_v2_diagnosis_2026-07-16.md`.

## WS-A1 — One book value everywhere
The $98,650 header flip was **SPAXX ($96.9K Fidelity MM sweep)** disappearing from a derived sum while unpriced mid-pipeline: `overview()` silently swapped `portfolio_totals.total_value` for the derived Σ(market_value) on >$500 drift. Fixed: canonical total never swaps; drift is exposed as `total_value_drift` (UI may hint "repricing…"). Verified: identical $ on Watch/RI/Portfolio headers. The 4 cash rows (=`total_mv_excluded` $187.8K) are excluded from cost-basis math by design — not a second scope.

## WS-B — Directive governance (regrowth fence)
Root cause pair: creation-time family dedup lived ONLY in think_tank (7 other inserters exact-label at best), and dedup was never scheduled (`pause_cold_trends` already rides the 30-min service).
- **B1 fence:** `scripts/lib/watch_directive_gate.py` — `family_gate()` (canonical_family survivor lookup, hits-ranked) + `attach_alias()` (spec.aliases/keywords/alias_notes enrichment). Wired into claude_challenger_curator, strategy_planner, sector_research_universe, telegram add-topic (soft warning, never blocks operator), api_v2 create (returns `needs_confirm` + merge candidate; `force=true` overrides). Unit-verified: same-family label → alias on #244, 0 new rows.
- **B2 hygiene:** `scripts/watch_directive_hygiene.py`, Sundays 10:30 — auto-applies dedup tiers 1–2 (reversible archives), Telegrams the tier-3 merge plan for operator approval. First run archived 29 dead challengers (317→288 active trend).
- **B4 cap:** `config/watch_directive_governance.json` `active_trend_cap: 150` — at/over cap new trends insert as `status='proposed'` (demonstrated live: novel label → propose while 288 ≥ 150). Actives are never auto-archived to make room.

## Remaining (flagged, not started — next session)
WS-A2 facet honesty (setup_advisory is free text "RSI nn · band x-y", not an enum — vocabulary mismatch, needs server-computed facet counts), A3 enum labels + BATL dup, A4 sector holes (XLRE/Financials/legend), B3 reviewable directive rows + Proposed fold UI, WS-C held badges/conflict strip/TickerLinks/rank transparency ("Top 200 of 5,167 by Hermes rank"), WS-D pullback history/cooldown/provenance, WS-E payload trims (watchlist/items 1.41MB, watch-directives 793KB). ChatGPT quota badge = the 2-hourly top20 cron consuming (lanes restored today), not page views. ToS imports dir never existed — report-only.
