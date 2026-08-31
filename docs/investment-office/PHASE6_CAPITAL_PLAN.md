# Phase 6 — Capital plan and portfolio decision engine

Status:      HISTORICAL
as_of:       2026-08-13T21:48:42-04:00
Measured at: efcc51365 / not measured

> Goal (from the convergence prompt): make Alex capable of answering "what should
> I do with my money?" in explicit dollars while staying advisory-only. Everything
> here is `READ_ONLY_ADVISORY` — no execution authority.

## 1. Scope

Phase 6 composes canonical state that already exists elsewhere into one
deterministic **Capital Plan projection** (sources and uses of funds shown
together) plus a **Position Decision table** for every material holding:

```
cash_total = settled holdings cash (includes earmarked redeploy proceeds)

sources of funds:
  trims / exits     = prospective raise (not yet cash)  → total_raise_usd
  maturities        = open redeploy remaining_usd       → EARMARK label only
                      (already in cash_total; capped to cash; NOT in total_raise)

uses of funds (deploy):
  adds / new_positions / reentry / sector_rotation
  reserve = cash policy floor (held back)

deployable                 = investable_cash + total_prospective_raise
net_recommended_deploy_usd = min(total_uses, deployable)
net_recommended_raise_usd  = total_prospective_raise   (trims+exits only)
post_plan_cash_usd         = cash + prospective_raise - deploy
```

**Phase 2 (`capital_plan_1.1.0`):** earmarked redeploy is never double-counted as
raise. See `PHASE2_CASH_CAPITAL_LEDGER.md`.

Cash is **never force-deployed**: with no uses (no add/new/reentry/rotation
signal), `net_recommended_deploy_usd` is 0 even when investable cash exists.

## 2. Inputs composed (all fail-soft, no new writers)

| Input | Source | Shape consumed |
| --- | --- | --- |
| Portfolio value / cash / positions / account tax | `holdings.json` | `portfolio_value`, `cash_total` (sum of `is_cash` rows — the audit-corrected live figure, matching `api_v2` cash-live), `positions`, `accounts[].taxable/type` |
| Sale proceeds awaiting redeploy | `redeploy_capital_book.build_opportunity_set` | `open_events[].remaining_usd` → `maturities_distributions` |
| Desk verdicts | `cio_opportunity_queue.build_queue_from_executor` | `items[].symbol/verdict/state/source` → trims/exits/adds/reentry |
| Sector rotation | `cio_sector_opportunity.build_synthesis_from_executor` | `opportunities[]` (underweight LEADING/IMPROVING) → `sector_rotation` |
| Risk posture | desk thesis `risk_posture_structured` | `cash_band_min_pct`, `max_single_name_weight_pct`, `concentration_fire_pct` |

## 3. Delivered

### 3a. Pure engine (`scripts/lib/cio_capital_plan.py`, no I/O at import)

- **Policy helpers** — `cash_policy_band` (dollar floor/ceiling), `cash_posture`
  (ABOVE_BAND / IN_BAND / BELOW_BAND / NO_PORTFOLIO; splits cash into
  `reserve_usd` vs `investable_usd`), `classify_account_tax` (TAXABLE /
  TAX_ADVANTAGED / UNKNOWN; config `taxable`/`type` first, then account-name
  `ira`/`roth`/`401k` inference; unknown fails toward TAXABLE so a tax/lot
  constraint is never silently waived).
- **Normalization** — `normalize_position` (idempotent: accepts raw `market_value`
  or normalized `market_value_usd`), `stance_for` (verdict → reentry state →
  HOLD, precedence EXIT > TRIM > RE_ENTER > ADD > state).
- **Sources of funds** — `build_capital_sources`: TRIM → `trim_fraction` (10%) of
  position value; EXIT → full value (**prospective raise**); open redeploy events →
  `maturities` / `earmarked_redeploy_usd` (**label on cash**, excluded from
  `total_raise_usd`, capped to `cash_total`).
- **Cash ledger** — `build_cash_ledger` + `account_cash_breakdown` with double-count
  invariants (`earmark_le_cash`, `investable_eq_cash_minus_reserve`,
  `post_cash_identity`, `deploy_le_investable_plus_prospective`).
- **Uses of funds** — `build_capital_uses`: ADD/RE_ENTER/new-position are bounded
  by single-name headroom (`max_single_name_weight_pct` cap); sector rotation is
  bounded by the sector's underweight gap and requires a STAGED/RESEARCH
  recommendation; reserve is the cash floor held back.
- **Plan composition** — `build_capital_plan` (`capital_plan_1.1.0`): full envelope
  including `cash_earmarked_redeploy_usd`, `deployable_usd`, `cash_ledger`,
  `ledger_invariants`, sources/uses, net deploy/raise, post-plan cash, alternatives,
  position decisions, hash-pinned `digest`.
- **Alternatives** — `do_nothing` always present; `half_sized` when a deployment is
  recommended; `await_confluence` when uncertainty is high (no multi-desk/sector
  signal).
- **Position Decision table** — `build_position_decisions`: symbol, current value,
  current weight, CIO stance, target range, recommended `$` delta, funding
  destination/source, why-now, risk, tax/account constraint, counter-thesis
  (divergence), next review; ordered by activity (largest `|delta|` first).
- **Composition** — `load_holdings_snapshot` + `build_capital_plan_from_sources`
  (fail-soft; derives portfolio value from holdings when totals are absent).

### 3b. Read surface (`scripts/api_v2.py`)

- New endpoint `GET /api/v2/cio/capital-plan` (READ_ONLY_ADVISORY) — full plan +
  digest, composed from live holdings / redeploy / queue / sector / thesis state.
- `_capital_plan_compact()` — compact block added to `_two_way_curation_health`
  (digest / value / cash / reserve / investable / posture / deploy / raise /
  post-plan cash / top decisions).
- `_risk_posture()` — fail-soft read of the desk thesis `risk_posture_structured`
  (falls back to policy defaults).

Canaries (`tests/test_cio_capital_plan.py`, 37 tests): cash band/posture truth
table, account-tax classification (config + name inference + unknown→taxable),
position normalization idempotency, stance precedence, source arithmetic
(trim/exit/maturity), use bounds (headroom / reentry / sector gap / reserve),
full-plan required fields + arithmetic sums, never-force-deploy, deploy-bounded-by-
deployable, digest determinism, alternatives (do-nothing / half-sized /
await-confluence), position-decision delta sign + tax + counter-thesis + ordering,
and the fail-soft snapshot/composition reader.

```bash
python3 -m pytest tests/test_cio_capital_plan.py -q
```

## 4. Checkpoint 6

> Generate a full-book capital plan from current canonical state and verify
> arithmetic sums to the portfolio within tolerance.

The live endpoint was exercised against `holdings.json`:

```
portfolio_value_usd   1,282,425.99   (holdings portfolio_totals.total_value)
cash_total_usd          578,107.50   (sum of is_cash rows — audit-corrected live figure)
cash_reserved_usd       256,485.20   (20% policy floor)
cash_investable_usd     321,622.30   (cash above floor)
posture                ABOVE_BAND    (45.1% cash vs 20% floor)
net_recommended_raise   623,009.02   (open redeploy proceeds + trims/exits)
net_recommended_deploy  603,114.70   (bounded by investable + raise)
post_plan_cash_usd      598,001.82
post_plan_cash_pct       46.63%
position_decisions            26
```

The plan reconciles: `post_plan_cash = cash + raise - deploy` =
`578,107.50 + 623,009.02 - 603,114.70 = 598,001.82` ✓, and
`deploy ≤ investable + raise` = `321,622.30 + 623,009.02 = 944,631.32` ✓.

## 5. Known gaps (honest, not hidden)

- **Sector rotation sizing is a top-up, not a full rebalance.** The rotate-in `$`
  equals the sector's underweight gap × portfolio value, capped by the sector gap;
  a target-weight optimizer (mean-variance / min-tracking-error) is explicitly
  out of scope for this advisory projection.
- **Maturities/distributions rely on `redeploy_capital_book` open-event truth.**
  If no open deploy events exist, this leg is empty — the plan does not fabricate
  income distributions.
- **Thesis risk posture is file-backed** (`cio_theses_projection.json`); if the
  desk thesis has not published a `risk_posture_structured`, the plan uses policy
  defaults (cash band 20–25%, single-name 12%, concentration 16.5%).
- **Position decisions are per-holding-row** (account-scoped); two lots of the
  same symbol in different accounts appear as two rows, which is correct for
  tax/lot constraints but is not symbol-aggregated.
- **Checkpoint 6 arithmetic was verified against the live holdings snapshot**; a
  DB-end-to-end run (redeploy + queue + sector momentum populated) is the
  remaining live-data validation, matching the cross-phase organic-loop gap noted
  in the Phase 5 doc.
