# Cost Basis + Income Repair from June 5 CSVs (2026-06-05)

Status:      ACTIVE
as_of:       2026-06-05T17:27:45-04:00
Measured at: efcc51365 / not measured

Repaired Schwab/Fidelity cost basis using the latest (June 5) Schwab transaction CSVs, an explicit
owner transfer-basis override for V, the Fidelity Positions PDF basis, and a new income/dividend ledger.

## Source CSVs (selected by latest-file discovery; gitignored private data)
- 2b4d4dde38f00215784970ffec3bc843  data/portfolios/input/Individual_XXX469_Transactions_20260605-164914.csv
- c7002f8114d7517976decd5823dc8241  data/portfolios/input/Rollover_IRA_XXX258_Transactions_20260605-164958.csv
- f7f5ff33ab1098cb198f687683e3d96b  data/portfolios/input/Roth_Contributory_IRA_XXX415_Transactions_20260605-165034.csv

## Previous bug
- `patch_holdings_cost_basis.py` hardcoded the April (20260408) filenames → newest data ignored.
- No transfer-basis override handling → V/FCNTX (transferred-in) had no/​fabricated basis.
- No income ledger → dividends/interest lost.

## Fixes
- **Latest-file discovery** (`latest_csv_for_account`, newest `*_Transactions_*.csv` timestamp per account).
- **schwab_reconstructor**: cost basis = summed actual buy Amounts (avg-cost); internal Journals net-neutral;
  transfer-in shares get basis from explicit overrides else flagged partial. New `transfer_basis_overrides` arg.
- **cost_basis_overrides.json**: V rollover $43/share (operator_provided) + Roth V $43 carry-forward; FCNTX
  candidate $47.66 (needs_confirmation — NOT auto-applied).
- **income_ledger.json**: dividends/qual-div/special/reinvest-div/LT-cap-gain/bank+credit interest, by account+symbol.
- **Open Trades**: trusts explicit cost_basis_source (no false "unverified" on legit big gains like V +613%);
  badges "basis: owner provided" / "basis needs transfer mapping".

## Applied (validated 14/14)
- SCHG rollover: $52,379 (avg $30.8112) — was "no cost basis".
- SCHD rollover: $127,953.70 (avg $31.0368). JEPI $57,550. XLB/XLI/ARKG/BND match anchors.
- V rollover: 301.4412 sh, $13,665.95 (avg $45.34, includes 06/01 reinvest) — operator_provided $43 transfer basis.
- V Roth: 130.2689 sh, $5,677.10 (avg $43.58) — carry-forward.
- FID-CONTRA-F: $133,774 (Fidelity Positions PDF).
- FCNTX: basis None, flagged **basis_needs_transfer_mapping** (Fidelity$47.66 candidate awaiting confirmation).
- Income: grand total **$10,543.13** (rollover $9,326.14, taxable $1,095.40, roth $121.59).
- holdings.json total_value $1,197,268, total_cost_basis $922,573. backup: holdings.json.bak_costbasis.

## Safety
ALPACA_MODE=paper, LLM_DISABLE_LIVE_EXECUTION=true. 0 INSERT/UPDATE/DELETE/submit_order/place_order in
changed scripts. Local portfolio-state repair only. No broker/order/GO-WAIT/strategy/live/Phase-205 changes.

## Remaining
FCNTX transfer (3,852.846 sh) — confirm the Fidelity FID CONTRA $47.66 mapping to apply
($187,995.42 total / $46.59 avg), or it stays flagged. Raw CSVs are gitignored; checksums above.
