# Fundamentals design parity repair

Scope: /wealth/portfolio/fundamentals, implemented with the existing served holdings read. The approved local HTML is a visual reference only; none of its portfolio examples or records is embedded in source.

[CODE] Source trace: existing broker/CIO/enrichment producers and stored holdings/basis/profile/stop observations → scripts/lib/cio_truth.py::holdings_payload → the existing GET /api/v2/portfolio/holdings → portfolio/adapter.ts::adaptHoldings → FundamentalsLive → FundamentalsPage → fundamentals/modelV2.ts. The same book and account scope are published to the shell. No new provider, paid model, scheduled task, live broker or financial advice is invoked.

[CODE] Covered positive equity P/E uses the matched-universe weighted harmonic calculation: covered market value divided by sum(value / positive P/E). Trailing and forward universes remain separate. Cash/funds are excluded; unknowns remain missing; account-row, distinct-security and known-value coverage are labeled separately. Largest equity sector excludes cash/funds while retaining unknown equity classification in the denominator. Sector graphics and weighted chips reuse the Holdings allocation model.

[CODE] The existing /api/v2/dividends read and portfolio/income/incomeAdapter.ts serve forecast calendar legs and household/account estimates; they do not establish received income or a comparable full-book yield. This workspace preserves every published row schedule yield and links to the existing Income reader. It does not divide static forecasts by a differently timed holdings denominator or fabricate beta, expenses, earnings events, quality or peer/history metrics.

[CODE] Six table field groups retain all facts across Valuation, Income and Risk & ownership lenses. Filtered cards, account/type/data/sector/search/real sort controls, URL state, grouping and raw-row CSV use the same selection. Security totals derive summed value, unrealized dollars and remaining basis; child/single-account return preserves the served percentage. Tiny positions collapse with an explicit material-loss exception; cash has an actual expansion control. Unknown instrument types remain visible. Drawers retain original producer fields with the canonical protection summary above them.

Acceptance checklist (production AFTER pending activation):
- [x] Three functional lenses; deterministic null-last sort; all filters combine with AND; reset preserves unrelated URL state.
- [x] Grouped account totals/children, small/cash controls and pinned material losses; precise scoped CSV.
- [x] Covered P/E, largest equity sector, account/security/value coverage and schedule-yield counts follow filters.
- [x] Shared protection applicability/status with Holdings and raw drawer evidence; missing security protection remains UNKNOWN.
- [x] Stacked field-labeled layout at <=760 in source, neutral ratios, semantic signed arrows, shared icons and keyboard tooltips.
- [x] Local27-case adapter regressions and required frontend build passed.
- [ ] Measured clean-bundle browser acceptance and reference comparison at390/412/760/1280/1440; final private receipt records evidence.
- [ ] Actual live AFTER, displayed build and independently served full SHA. Production packaging was rejected by automatic approval review even after the user's renewed exact approval. No deployment claimed.

Concrete producer gaps: issuer-match evidence and actual news-ingestion completion time; approved full-book beta/yield; earnings/declared events; received income and realized return. All require the established producers and contracts rather than page-load advice or duplicate schedulers.
