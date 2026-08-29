# CIO Wave 2 — slice 12 / 12a / 12b / 12c: holdings truth

Authority: **READ_ONLY_ADVISORY** · MBI **0** · INTERDICT **0** (left as found)
CURRENT pin at dry: `d53fde4c` (#620) · `/api/v2/health` 200 · `/v3/cio` 200 · `/api/v3/cio/home` 200

No broker write. No notify. No ROTATE. No book merge. No plan minted to move a number.
**No lot is deleted anywhere in this slice — dust is a label.**

---

## 12a — DUST policy (documented, then applied)

`scripts/lib/holdings_universe.DUST_POLICY`

| Field | Value |
|---|---|
| `policy_id` | `dust_residual@v1` |
| rule | aggregate `market_value` across accounts **< $50.00** per ticker |
| basis | `market_value` (absolute dollars) |
| aggregation | per ticker, across accounts |
| unknown market value | **HELD**, never dust |
| rejected alternative | portfolio weight < 0.5% |
| deletes lots | **false** |
| fixture | SCHG |

**Why $50 and not weight < 0.5%.** On a $1.29M book, "weight < 0.5%" labels
AMANX ($5,164 · 0.40%) and the taxable SPCX sleeve ($5,458 · 0.42%) as dust.
Those are deliberate positions. A flat $50 floor separates a residual share
left behind by a sale — SCHG $8.09, SRNE $0.90 — from a small real holding.

Two guards keep the rule honest:

* **Aggregated per ticker.** A name held tiny in one account and large in
  another is never dust (SPCX: $5,458 taxable + $21,834 IRA = $27,292 HELD).
* **Unknown market value is not dust.** A position is never dropped from
  coverage because a price is missing. Fail open to HELD.

### Dry table — CURRENT, persist=False

| Ticker | Aggregate MV | Status |
|---|---:|---|
| SCHD | 365,694.75 | HELD |
| V | 126,995.21 | HELD |
| XLI | 36,268.37 | HELD |
| ARKX | 32,410.00 | HELD |
| SPCX | 27,292.00 | HELD |
| XLB | 27,177.37 | HELD |
| XAR | 26,770.00 | HELD |
| DIV | 8,239.60 | HELD |
| AMANX | 5,164.33 | HELD |
| BAH | 673.83 | HELD |
| NOC | 127.82 | HELD |
| RTX | 104.68 | HELD |
| CSWC | 89.68 | HELD |
| PFLT | 88.50 | HELD |
| BND | 55.91 | HELD |
| **JEPI** | **22.66** | **DUST_RESIDUAL** |
| **LDOS** | **31.16** | **DUST_RESIDUAL** |
| **SCHG** | **8.09** | **DUST_RESIDUAL** |
| **SRNE** | **0.90** | **DUST_RESIDUAL** |

### held_n recalc

| Measure | Before | After |
|---|---:|---:|
| `held_n` (thesis coverage denominator) | 19 | **15** |
| `held_n_including_dust` (kept visible) | — | 19 |
| `dust_n` | — | 4 |
| `current_n` / `unavailable_n` | 19 / 0 | **15 / 0** |

No thesis was invented to keep `unavailable_n` at 0 — the four names that left
are dust, and every one of the 15 survivors already had a CURRENT symbol thesis.

BND at $55.91 sits just above the floor and stays HELD. The threshold is
applied mechanically; it is not tuned per name.

---

## 12 — CUSIP-only held rows are `instrument_id`, not ticker

The holdings feed puts a CUSIP in the `symbol` column, so every consumer that
reads `symbol` as a ticker is wrong for these three rows. They are now reported
under `instrument_id` with `id_type` and `is_ticker: false`.

| instrument_id | id_type | account | shares | MV | name |
|---|---|---|---:|---:|---|
| 12507E201 | CUSIP | schwab_taxable | 7 | 0.00 | DELISTED — CUSIP 12507E201 |
| 543354104 | CUSIP | schwab_rollover_ira | 3000 | 0.00 | DELISTED — CUSIP 543354104 |
| 628518102 | CUSIP | schwab_rollover_ira | 125 | 0.00 | DELISTED — CUSIP 628518102 |

They stay out of `held_equity_symbols`, out of thesis coverage, and out of the
dust table (they are not tickers, so they are not dust either). No thesis is
minted for them and no surface renders them in a ticker field.

---

## 12b — `home.coverage.with_plan` = 1 against 575 open plans

**Diagnosis: the counter's input, not the plan warehouse.**

`scripts/api_v3_cio.py` builds the home payload with
`plans = get_cio_plans(limit=12)` — the 12-row CIO NOW window. `build_office_coverage`
intersected held symbols with *that window*, so `with_plan` could never exceed 12
and in practice reported **1**. The plan store holds **575** open plans.

**Fix (counter only).**

* New `_coverage_plan_index()` reads the open-plan store read-only through a
  four-field projection (`situation_type`, `symbols`, `status`, `hermes_result_id`).
  `_public_plan` drops `hermes_result_id`, which is why `with_research` was
  also stuck at 0 — the projection keeps it.
* `build_office_coverage(coverage_plans=…)` counts against that; `plans` stays
  the 12-row window for CIO NOW and is the fail-soft fallback.
* Counted situation types: **S1 / S3 / S5 / S6**. `S0_OPERATOR_CONVERSE` and
  `S7_WATCH_PROMOTION` are not position coverage.
* Dust symbols are subtracted from the held set first (12a).

**Definition now printed on the payload:** `with_plan` = distinct **non-dust
held tickers** carrying at least one **open S1/S3/S5/S6** plan, counted over the
**whole open-plan store**. `with_plan_symbols`, `with_plan_source` and
`open_plans_considered` are exposed so the number can be audited without a shell.

### Dry — CURRENT

```
open plans in store                         : 575
plans passed to home (CIO NOW window)       : 12      <-- root cause
non-dust held with open S1/S3/S5/S6         : 11
  AMANX  S6            NOC   S1
  ARKX   S1            PFLT  S1
  BND    S1, S6        RTX   S1
  DIV    S1, S6        SCHD  S1, S6 (+S0, not counted)
  SPCX   S1, S6        XLB   S1
  XLI    S1
held with NO open plan (12c input)          : BAH, CSWC, V, XAR, AMANX*
```

`with_plan` 1 → **11**. Zero plans were created to move it.
(*AMANX has an S6 but no S1; it is an S1 candidate below.)

---

## 12c — observational S1 for the leftover real holds

`collect_held_without_open_s1` now skips DUST_RESIDUAL as well as CASH, CUSIP
and symbols that already carry an open S1. A residual share is not a coverage
hole and must not mint a plan — SCHG's slice-03 S1 had to be cancelled by hand
for exactly this reason.

### Dry — CURRENT, persist=False

```
held_n (non-dust)     : 15
held_n_including_dust : 19
skipped_dust          : ['JEPI', 'LDOS', 'SCHG', 'SRNE']
open_s1_n             : 14
skipped_open_s1       : PFLT NOC RTX SCHD SPCX DIV XLB ARKX XLI BND
would_n               : 5   (cap 5)
would_symbols         : ['BAH', 'CSWC', 'V', 'XAR', 'AMANX']
notify                : False
financial_action      : False
```

`would_symbols` matches the operator's leftover list exactly. Apply is a
separate step run on CURRENT after promote.

---

## Rails

| Rail | State |
|---|---|
| Authority | READ_ONLY_ADVISORY |
| MBI | 0 |
| INTERDICT | 0 (left as found) |
| Broker write | none |
| Telegram | no producer added; `telegram_sent` false |
| Lots deleted | **none** — dust is a label |
| Plans minted | none in this PR (12c apply is a separate, dry-first step) |
| ThesisDecisionGate | untouched |
| Reentry books | still two, still unmerged |
| Stop-management / quote-time / 2FA | untouched |
| ticker_prices history | untouched |
| SCHG | DUST_RESIDUAL → EXITED on Surface A, not a hold |
| FANG | still UNAVAILABLE |

## Tests

`tests/test_cio_wave2_slice12_dust_coverage.py` — 24 behavioral assertions:
threshold and boundary, cross-account aggregation, unknown-price fail-open,
SCHG dust vs SCHD hold, CUSIP → instrument_id (never ticker), coverage counts,
window-vs-store `with_plan`, S0/S7 exclusion, closed-plan exclusion, dust never
counted as covered, `with_research` requires `hermes_result_id`, home threading,
and observational S1 dust skip.

`tests/test_cio_wave2_slice08_coverage.py` fixtures gained an explicit
`situation_type` (assertions unchanged) — slice 12b tightened `with_plan` to
S1/S3/S5/S6 and the fixtures predate that contract.
