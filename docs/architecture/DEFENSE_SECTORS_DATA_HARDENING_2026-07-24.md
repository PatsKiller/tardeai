# Defense/Sectors Data Hardening — 2026-07-24

Status: draft, SHADOW/advisory only. No deployment, broker, order, approval, 2FA, service or production-config action.

## Implemented

1. Sector breadth now uses exactly 20 distinct daily closes per covered constituent and reports membership/coverage quality.
2. Capped market-mover counts are labeled as a top-movers sample, never comprehensive breadth.
3. Sector, industry, fund and recommendation snapshots carry source/as-of/calculation/quality coverage and SHA-256 snapshot hashes.
4. Industry groups and SPY use Finviz Elite performance view 141 in the same run; missing SPY data fails closed.
5. Sector rows older than the configured calendar-day tolerance are quarantined and cannot drive transitions or recommendations.
6. Industry-to-sector assignment uses a reviewed, versioned exact/rule map; unmapped groups are explicit and quarantined.
7. Rotate-in capacity is tied to an explicit benchmark and account mandate, then scaled by realized volatility and correlation and capped by sector policy.
8. Stock candidates require close-observed industry confirmation plus transparent valuation, growth, ROIC, leverage, profitability, crowding, beta and extension coverage. Missing evidence fails closed; ETF-only is allowed.
9. Fund look-through now exposes provider, factsheet date, refresh due date, mapped coverage, unmapped weight, quality and config hash.
10. The July 18 defensive lean receives a deterministic dated review record. It remains active until operator adjudication and is never auto-revoked.

## Render gate

Playwright intercepts representative payloads transcribed from the operator-provided live endpoint screenshots and renders `/v3/defense` and `/v3/sectors` at 1440px and 390px. The gate asserts truth labels and no horizontal overflow, then uploads four screenshots.

This fixture gate validates the frontend branch deterministically. A final host-side smoke remains required after deployment because GitHub runners cannot reach the private Tailnet host.
