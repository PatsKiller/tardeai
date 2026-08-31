# Cost Basis Feed Correction (2026-06-05)

Status:      HISTORICAL
as_of:       2026-06-05T16:33:29-04:00
Measured at: efcc51365 / not measured

Fixed fabricated cost basis / gains in holdings.json (e.g. V +4932%, FCNTX +2321%, SCHD +705%).
The source data WAS present — the import logic was wrong. No live broker API exists; sources are the
Schwab transaction CSVs + Fidelity PDFs in `data/portfolios/input/`.

## Root cause
- **Schwab** (`schwab_reconstructor.py`): computed `cost = shares × last_txn_price` (a guess) instead of
  summing the actual `Amount` column. Also never counted `Security Transfer`/`Internal Transfer`/
  `Journaled Shares` (no-cost inflows) → understated basis + impossible gains.
- **Fidelity** (`portfolio_loader.parse_fidelity_pdf_text`): hardcoded `cost_basis=None` even though the
  real basis is in `Portfolio Positions.pdf` (Cost basis column, e.g. FID CONTRA $133,784.08 / $47.66/sh).
- holdings.json is the source of truth for shares and is only *repriced* on load — so the bad basis was
  frozen until a re-import.

## Fix
- **schwab_reconstructor**: cost basis = **summed actual buy Amounts (average-cost; reduced proportionally
  on sells)**. Any no-cost transfer/journal inflow → `basis_partial=True` → cost basis reported `None`
  (never a fabricated number). Durable through future re-imports.
- **portfolio_loader**: Fidelity cost basis now read from `data/portfolios/input/fidelity_cost_basis.json`
  (per-share, sourced from the Positions PDF) instead of `None`.
- **patch_holdings_cost_basis.py**: reusable, idempotent script that recomputes holdings.json cost basis
  from both sources, applying basis only when reliable AND share-consistent (≤2% vs reconstructed),
  else `None` (basis_partial). Backs up holdings.json first.

## Result (validated end-to-end)
- applied=37, partial/unverified=7 (down from 15). total_cost_basis $850,258. portfolio total unchanged ($1.196M).
- SCHD avg $31.04 (+4.3%), FID-CONTRA $47.66 (+26.2%), SCHG matched accts +8–10% — all sane.
- V (both), FCNTX, SCHG-rollover → `None` (transferred-in / share-mismatch — honest, not fabricated).
- v3 Open Trades cards show real avg cost + P&L for reliable positions; "basis unverified" for the rest.

## Remaining (genuinely needs operator data)
The transferred-in lots (V, FCNTX, SCHG-rollover) have **no cost in the transaction CSVs**. To value
them, export a **Schwab Positions statement with a Cost Basis column** (like the Fidelity one) and add a
`schwab_cost_basis.json` per-share map; the patch/loader will then pick it up. Until then they stay
honestly flagged. No live broker API exists, so this cannot be auto-pulled.
