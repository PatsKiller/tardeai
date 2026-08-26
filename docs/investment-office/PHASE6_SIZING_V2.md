# PHASE 6 — Institutional Sizing v2 (Candidate Set)

**UTC:** 2026-08-14  
**Authority:** `READ_ONLY_ADVISORY` unchanged  
**Version:** `institutional_sizing_2.0.0`  
**Module:** `scripts/lib/cio_institutional_sizing.py`

Pure math. No broker. No execution.

## Problem

v1 (`institutional_sizing_1.0.0`) replaced a blind 10% TRIM with fire-clear /
policy staging, but still returned **one number**. ADD / RE_ENTER was a flat
$5k headroom-bounded default that read as if it were an optimized size.

An institutional desk does not emit a single size. It computes a book of
candidates and explains which one was chosen, and at what quality.

## Model

Keep fire-clear / policy staging. Always emit a `candidates` dict (keys
present; missing evidence → `null`):

| Candidate | Meaning | Null when |
| --- | --- | --- |
| `minimum_risk_clear` | $ to the fire line | ADD (n/a); EXIT = full book |
| `fire_safe` | $ to fire − 0.5 pp buffer | ADD (n/a) |
| `policy_normalize` | $ to single-name policy cap (TRIM) or remaining headroom (ADD) | — |
| `tax_aware_lot_size` | Lot-constrained size (loss-first on taxable) | no lots |
| `risk_budget_size` | Inverse-vol notional vs `risk_budget_usd` | no vol |
| `volatility_budget_size` | Inverse-vol vs book vol target (assumes 20% if vol omitted) | no portfolio |
| `liquidity_max` | ADV × participation (default 10%) | no ADV |
| `cash_policy_max` | Raise room to cash-band max (TRIM) or investable / headroom (ADD) | — |
| `replacement_opportunity_size` | Pass-through replacement ticket | not provided |
| `default_fallback` | 10% of position (TRIM) or $5k starter (ADD) | — |

Final selection carries:

- `selected_candidate` — which book entry (or `staged_fire_to_policy`) won
- `selection_rationale` — why, vs the other candidates
- `sizing_quality` — `HEURISTIC` | `OBJECTIVE` | `OPTIMIZED`
- `fallback_candidate_only` — true when the choice *is* the fallback

### Quality (honest, not “optimized”)

| Quality | When |
| --- | --- |
| `OPTIMIZED` | vol **and** risk budget present |
| `OBJECTIVE` | fire or policy binds (concentration math), or full EXIT |
| `HEURISTIC` | everything else — including a flat $5k ADD |

Insufficient evidence is labeled **HEURISTIC**, never optimized.

## TRIM (unchanged staging)

| Method | When | Selection |
| --- | --- | --- |
| `clear_fire_staged` | weight > fire | between fire-safe and full policy |
| `policy_normalize_staged` | fire ≥ weight > policy | staged toward policy (v1 formula) |
| `advisory_fallback_10pct` | within policy + advisory TRIM | `default_fallback` only |

Tax class may **scale** the stage only when lot / unrealized-gain evidence
exists (so SCHD dry tests stay bit-stable without tax inputs):

- **Taxable + large unrealized gain (≥20%)** — prefer a smaller stage
- **IRA / tax-advantaged** — allow a larger stage (no lot/tax drag)
- `tax_aware_lot_size` ranks lots: taxable harvests losses / small gains
  first and skips large-gain lots once any size is on the ticket

## ADD / RE_ENTER (tranches, not a lone $5k)

```
tranches:
  starter      — default $5k, bounded by headroom / cash / liquidity
  target       — ~2× starter, same bounds
  max_policy   — single-name headroom
  risk_budget  — inverse-vol notional (null without vol + budget)
```

- No risk budget → recommend **starter**, `sizing_quality = HEURISTIC`,
  `fallback_candidate_only = true`, method `heuristic_starter_tranche`.
- Vol + risk budget → recommend `risk_budget_size`, quality `OPTIMIZED`,
  method `risk_budgeted_tranche`.

A flat $5k is never presented as optimized.

## Example (SCHD-shaped)

Current **17.6%** · Fire **16.5%** · Policy **12%** · book **$1,284,000**  
Position **$225,984**

| Candidate | $ |
| --- | ---: |
| `minimum_risk_clear` | 14,124 |
| `fire_safe` | 20,544 |
| `policy_normalize` | 71,904 |
| `tax_aware_lot_size` | null (no lots) |
| `risk_budget_size` | null (no vol) |
| `volatility_budget_size` | 97,584 (assumed 20% vol) |
| `liquidity_max` | null (no ADV) |
| `cash_policy_max` | 225,984 |
| `replacement_opportunity_size` | null |
| `default_fallback` | 22,598.40 |

**Selected:** `staged_fire_to_policy` **$43,656** (`clear_fire_staged`)  
Quality: `OBJECTIVE` (fire binds; not optimized — no risk budget).  
Not −10% of $225,984.

## Pass-through

`size_decision` accepts optional evidence (`lots`, `unrealized_gain_pct`,
`annualized_vol`, `risk_budget_usd`, `adv_usd`, cash-band, replacement).

`extract_sizing_inputs()` reads those off a position / decision row.

Hooked (fail-soft) in:

- `cio_capital_plan.build_capital_sources` / `build_position_decisions`
- `cio_decision_semantics.aggregate_position_decisions` / `sanitize_decisions_now`
- `cio_command_center` card merge (`candidates`, `sizing_quality`,
  `selected_candidate`, `selection_rationale`, `tranches`)

## Tests

```
tests/test_cio_institutional_sizing.py
tests/test_cio_capital_plan.py
tests/test_cio_decision_semantics.py
```

Dry gates:

- SCHD-style fire still staged between clear-fire and full policy
- `candidates` dict always present (every key)
- $5k ADD is `HEURISTIC` / `fallback_candidate_only` when no risk budget
- taxable vs IRA changes rationale or `tax_aware_lot_size`

## Safety

## REAL TELEGRAM SENDS: 0
## BROKER CALLS: 0
## FINANCIAL AUTHORITY CHANGED: NO
