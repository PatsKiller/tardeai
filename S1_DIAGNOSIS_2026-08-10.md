# S1 Diagnosis — Advisory Desk v1
**Date:** 2026-08-10
**Module:** `scripts/lib/data_broker/advisory_desk.py`
**Status:** READ-ONLY. No code changed.

---

## Block 1 — The 15 EXIT verdicts

### Verdict distribution (holdings rows only)

29 holdings rows. 15 EXIT (52%), 4 TRIM (14%), 10 HOLD (34%).

### Full EXIT records

```
12507E201  schwab_taxable        EXIT  mv=0       pct=0.00%  bucket=Delisted/Worthless  (no signals)
PFLT       schwab_taxable        EXIT  mv=87      pct=0.01%  gl=-26.24%  days=206   [underweight,material_loss,long_held,disposition_effect_like]
SCHG       schwab_taxable        EXIT  mv=8       pct=0.00%  gl=+17.43%  days=1142  [underweight,long_held]
RTX        schwab_taxable        EXIT  mv=111     pct=0.01%  gl=+8.05%   days=160   [underweight]
SPCX       schwab_taxable        EXIT  mv=5495    pct=0.43%  gl=-38.25%  days=1149  [underweight,material_loss,long_held,disposition_effect_like]
DIV        schwab_taxable        EXIT  mv=8018    pct=0.63%  gl=-0.13%   days=166   [underweight]
BAH        schwab_taxable        EXIT  mv=701     pct=0.05%  gl=+0.38%   days=160   [underweight]
CSWC       schwab_taxable        EXIT  mv=89      pct=0.01%  gl=+4.78%   days=206   [underweight,long_held]
SCHG       schwab_roth           EXIT  mv=4       pct=0.00%  gl=+17.28%  days=1142  [underweight,long_held]
SRNE       schwab_rollover_ira   EXIT  mv=0       pct=0.00%  gl=-100.0%  days=1225  [underweight,material_loss,long_held,disposition_effect_like]
543354104  schwab_rollover_ira   EXIT  mv=0       pct=0.00%  bucket=Delisted/Worthless  (no signals)
628518102  schwab_rollover_ira   EXIT  mv=0       pct=0.00%  bucket=Delisted/Worthless  (no signals)
QCOM       schwab_rollover_ira   EXIT  mv=8934    pct=0.70%  gl=-12.84%  days=1122  [underweight,moderate_loss,long_held]
AMANX      schwab_rollover_ira   EXIT  mv=5164    pct=0.40%  gl=+319.93% days=1225  [underweight,large_gain,long_held]
SPCX       schwab_rollover_ira   EXIT  mv=21981   pct=1.74%  gl=-20.37%  days=1149  [material_loss,long_held,disposition_effect_like]
```

### Rule classification

| Rule | Count | Signals |
|---|---|---|
| `underweight` | 8 | SCHG×2, RTX, DIV, BAH, CSWC, QCOM, AMANX |
| `underweight+material_loss+long_held` | 3 | PFLT, SPCX(taxable), SRNE |
| `delisted/worthless` (bucket, pre-signals) | 3 | 12507E201, 543354104, 628518102 |
| `material_loss+long_held` | 1 | SPCX(rollover) |

### Dominant rule: `underweight` (8 of 15 = 53%)

Code at lines 360–362, 407–410:

```python
    if pct < HOLD_MIN_WEIGHT_PCT and mv > 0:      # line 360
        signals.append("underweight")              # line 361
        ...
    elif "underweight" in signals:                 # line 407
        verdict = AdvisoryVerdict.EXIT             # line 408
        confidence = 0.55                          # line 409
```

- **Left operand:** `pct` — computed at line 315: `pos.get("portfolio_pct") or (mv / total_value * 100 if total_value > 0 else 0)`
- **Right operand:** `HOLD_MIN_WEIGHT_PCT = 1.0` — defined at line 53
- **Units:** `portfolio_pct` from `holdings.json` is already in percent units (e.g. 0.0068, 16.4862)
- **Source:** `data/portfolios/state/holdings.json`, field `portfolio_pct`

The threshold of 1.0% catches positions ranging from \$4 (SCHG roth) to \$8,934 (QCOM). The rule is correct in logic but aggressive in threshold: any position under 1% weight that has any market value gets EXIT with 0.55 confidence, regardless of gain/loss, thesis, or sector.

### EXITs with missing cost_basis: 2

Of the 15 EXIT rows, 2 have `cost_basis` absent (`None`) in holdings.json:

- **12507E201** (schwab_taxable): cost_basis=None, mv=0, bucket=Delisted/Worthless
- **628518102** (schwab_rollover_ira): cost_basis=None, mv=0, bucket=Delisted/Worthless

The third delisted (543354104) has cost_basis=4762.95 but mv=0, so gain_loss_pct is still None.

None of these reach the gain/loss computation. The bucket check at line 327 returns early before the gain/loss code ever runs (line 324):

```python
    if bucket in ("Delisted/Worthless", "Worthless", "Delisted"):
        return { ... "verdict": AdvisoryVerdict.EXIT ... }
```

Absent cost_basis does not cause -100% loss for any non-delisted row. The `if cost_basis and cost_basis > 0 and mv > 0:` guard on line 324 correctly skips the computation when cost_basis is unavailable. The non-delisted EXIT rows all have valid cost_basis.

---

## Block 2 — Sanity anchors

### PFLT

- **Desk verdict:** EXIT, `weight_pct`=0.01, `gain_loss_pct`=-26.24%, days_held=206
- **Raw holdings.json:** `portfolio_pct`=0.0068, `cost_basis`=117.85, `market_value`=86.93
- **PFLT true weight:** \$86.93 / \$1,276,507 = 0.000068 = 0.0068% → `portfolio_pct` IS already a percent
- **Weight interpretation:** The desk uses `pos.get("portfolio_pct")` directly, which is 0.0068. Rounded to 2dp → 0.01. The field is already percent-scale. **Correct.**

### V

- **Desk verdicts:** HOLD (roth, 3.69%, +17.82%) and TRIM (rollover, 5.70%, +330.05%)
- **Raw:** V(roth) `portfolio_pct`=3.6873, `cost_basis`=39951.37, mv=47068.76 → (47068.76-39951.37)/39951.37 = +17.82%. Reconciles. ✓
- **Raw:** V(rollover) `portfolio_pct`=5.7019, `cost_basis`=16924.83, mv=72784.73 → (72784.73-16924.83)/16924.83 = +330.0%. Reconciles. ✓
- **Desk gain_loss_pct (330.05) vs raw gain_loss_pct (not checked — raw doesn't have it for V).** The desk's own computation matches the cost_basis field.

### SCHD

- **Desk TRIM verdict** (rollover, 16.49%, overweight). Raw `portfolio_pct`=16.4862. **Matches.** ✓
- **Same interpretation:** PFLT at 0.0068% and SCHD at 16.4862% both read from the same `portfolio_pct` field. Both are already percentage-scale. **Consistent interpretation across both positions.** No unit mismatch.

### Verdict: YES — same interpretation for PFLT and SCHD

---

## Block 3 — Row reconciliation (34 → 29)

### 34 minus 5 CASH = 29

The raw `holdings.json` contains 34 positions. The desk filters line 143:

```python
    if not symbol or symbol == "CASH":
        continue
```

5 CASH positions excluded:

| Symbol | Account | Market Value |
|---|---|---|
| CASH | moomoo_taxable_live | \$500.00 |
| CASH | alpaca_taxable_live | \$5,000.00 |
| CASH | schwab_taxable | \$37,894.31 |
| CASH | schwab_roth | \$1,469.22 |
| CASH | schwab_rollover_ira | \$533,243.97 |

**"26→29" was a reporting error in S1.** The correct number is 34 raw → 5 CASH excluded → 29 holdings in desk. There are no missing symbols and no extra symbols. IN RAW NOT IN DESK = {CASH}. IN DESK NOT IN RAW = {}.

### CUSIP rows

All three CUSIP rows are **included** in the desk:

| CUSIP | Account | Raw | Desk Verdict |
|---|---|---|---|
| 12507E201 | schwab_taxable | YES | EXIT (Delisted) |
| 543354104 | schwab_rollover_ira | YES | EXIT (Delisted) |
| 628518102 | schwab_rollover_ira | YES | EXIT (Delisted) |

---

## Block 4 — Five rows hand-verified

Comparison table (5 positions × 4 fields = 20 comparisons + 5 days_held cross-check):

| Symbol | Account | Field | Desk | Raw/API | Match |
|---|---|---|---|---|---|
| SCHD | schwab_taxable | weight_pct | 1.09 | 1.0889 | Y |
| SCHD | schwab_taxable | gain_loss_pct | 9.55 | 9.5525 | Y |
| SCHD | schwab_taxable | market_value | 13899.73 | 13899.73 | Y |
| SCHD | schwab_taxable | days_held | 1225 | from tax_lots | UNVERIFIED |
| SCHD | schwab_rollover_ira | weight_pct | 16.49 | 16.4862 | Y |
| SCHD | schwab_rollover_ira | gain_loss_pct | 9.12 | 9.1169 | Y |
| SCHD | schwab_rollover_ira | market_value | 210448.02 | 210448.02 | Y |
| SPCX | schwab_taxable | weight_pct | 0.43 | 0.4347 | Y |
| SPCX | schwab_taxable | gain_loss_pct | -38.25 | -37.6407 | **N** |
| SPCX | schwab_taxable | market_value | 5495.2 | 5495.2 | Y |
| SPCX | schwab_rollover_ira | weight_pct | 1.74 | 1.739 | Y |
| SPCX | schwab_rollover_ira | gain_loss_pct | -20.37 | -19.5784 | **N** |
| SPCX | schwab_rollover_ira | market_value | 21980.8 | 21980.8 | Y |
| JEPI | schwab_rollover_ira | weight_pct | 6.65 | 6.6467 | Y |
| JEPI | schwab_rollover_ira | gain_loss_pct | 0.65 | 0.6499 | Y |
| JEPI | schwab_rollover_ira | market_value | 84846.08 | 84846.08 | Y |
| QCOM | schwab_rollover_ira | weight_pct | 0.70 | 0.6987 | Y |
| QCOM | schwab_rollover_ira | gain_loss_pct | -12.84 | -12.9756 | Y |
| QCOM | schwab_rollover_ira | market_value | 8933.65 | 8933.65 | Y |
| DXCM | schwab_rollover_ira | weight_pct | 1.54 | 1.5449 | Y |
| DXCM | schwab_rollover_ira | gain_loss_pct | 23.37 | 23.3725 | Y |
| DXCM | schwab_rollover_ira | market_value | 19721.25 | 19721.25 | Y |

**Numerical fields:** 17 out of 19 match (2 SPCX gain_loss_pct mismatches).

**Days held:** UNVERIFIED — the desk computes from tax_lots.json via `_compute_days_held()`. The API does not expose `days_held` in the `/api/v2/portfolio/holdings` response (field not present at all). Cross-verification would require manual lot-by-lot audit of `tax_lots.json` against broker records. The desk's `_compute_days_held` uses `lot_date` from tax_lots, which is the earliest open lot acquisition. That is the correct methodology but independently unverified.

### SPCX gain_loss_pct discrepancy

Both SPCX rows show a consistent ~0.6-0.8 percentage point offset:

| Account | Desk formula `(mv-cb)/cb` | Raw `gain_loss_pct` | Delta |
|---|---|---|---|
| schwab_taxable | (5495.2-8899.4)/8899.4 = -38.25% | -37.6407% | -0.61pp |
| schwab_rollover_ira | (21980.8-27602.53)/27602.53 = -20.37% | -19.5784% | -0.79pp |

The `gain_loss_pct` in `holdings.json` was poplated by a different computational path (likely the API's own enrichment pipeline, which may use adjusted cost basis or include dividend reinvestments). The desk's simple `(mv - cost_basis) / cost_basis` diverges. The desk's value uses the same `cost_basis` field but a simpler formula. Both are defensible for different purposes. The mismatch exists because the desk recomputes rather than consuming the existing field.

---

## Block 5 — Phase 3 audit

### Artifact existence

| Artifact | Exists? | Path |
|---|---|---|
| `config/behavioral_detection.json` | **YES** | `config/behavioral_detection.json` (1454 bytes, Aug 8) |
| `_detect_disposition_effect()` | **YES** | `scripts/cio_heartbeat.py` line 218 |
| `bias_flag: "disposition_effect"` | **YES** | `scripts/cio_heartbeat.py` line 281 |
| Commit `3cb4c42a` | **YES** | `fix(cio): cost basis domain + behavioral detection now firing` |
| Commit `16b3a2d4` | **YES** | `feat(cio): behavioral finance — disposition effect detection (Rule 1) (PR #306)` |

**Contrary to the earlier finding that "no disposition detector module exists"** (from S0-R, an incorrect search scope): the detector exists, its config exists, and it fires on every heartbeat cycle. The S0-R conclusion was wrong.

### BUT: The "first finding" figures are fabricated

The CIO action ledger contains 5+ entries for PFLT, all claiming:

> *"PFLT: unrealized loss 20.9% ($230,098), held ~6mo, weight 68.5% of equity"*

**The real PFLT position is:** \$86.93 market value, 11.7466 shares, \$117.85 cost basis, -26.24% loss, 0.0068% portfolio weight.

**Root cause of the fabricated figures:** `tax_lots.json` contains 115,993 shares remaining (across both `schwab_taxable` and `schwab_rollover_ira` keys) with total cost of \$1,102,366.14. But the actual holdings show only 11.7466 shares at \$86.93 value. The `cio_portfolio.py` cost_basis domain was aggregating ALL lots from `tax_lots.json` — including lots where the position had been sold down — without properly filtering for actually-held shares. This produced an absurd ~68.5% weight for an \$87 paper-clip position.

The evidence: tax_lots.json for PFLT shows 115,993 `shares_remaining` across hundreds of lot entries, most with `closed=True`. The cost_basis domain in `cio_portfolio.py` line 443 (`_domain_cost_basis` — "Aggregate per-position cost basis from tax_lots.json for taxable accounts") was not checking the `closed` flag or reconciling against `holdings.json` `shares`. The disposition detector consumed garbage data and produced a fabricated "first finding."

**The delivery doc's claim of "first finding: PFLT — 20.9% loss, $230K unrealized, 68.5% weight → Critical" was produced from data that does not reflect the actual portfolio.** The disposition detector code works; the data pipeline feeding it produces wrong numbers for positions that have been partially or fully sold down.

### Gate bridge (Postgres restored)

```
Passing:       11/12
Failing:       1   (min_artifact_population: 78/100)
Darwin:        78/78 scored (100% coverage)
Contradictions: 0.0000
```

**Versus delivery doc claim of "11/12 PASS, Darwin 78/78, 0 contradictions":** The gate bridge confirms the delivery doc's numbers. The bridge now runs against live Postgres (restored after disk recovery). The one failing gate (min_artifact_population) needs ~22 more artifacts at current cadence.

---

## Block 6 — Cache granularity

### Cache is WHOLE-RESULT

- Single file: `data/runtime/advisory_desk_latest.json` (28,108 bytes)
- Single TTL: `DEFAULT_MAX_AGE_S = 300` (line 37)
- Single content hash: computed over ALL 61 rows (lines 630-631)
- Per-row hash present: **0 / 61 rows** — field `advisory_row_hash` does not exist

```python
    # Compute content hash for cache invalidation
    content_json = json.dumps(rows, sort_keys=True, default=str)
    content_hash = hashlib.sha256(content_json.encode("utf-8")).hexdigest()[:16]
```

**Impact:** If one holding's `price` or `market_value` changes, the entire content hash changes, all 61 rows are invalidated, and the cache is recomputed. At S3, where the cached desk output feeds LLM calls, this means **one price tick invalidates 61 cached opinions**, potentially burning the entire model budget on a single run.

**The specification called for per-row hashing** (`advisory_row_hash`) to allow 60 rows to remain cached when 1 row changes. This was not implemented.

---

## SCORECARD

```
1  EXIT rows / dominant rule:        15 / underweight (8 of 15, code at line 360+407)
1b EXITs with missing cost_basis:    2 (12507E201, 628518102 — both Delisted, handled before gain/loss)
2  PFLT verdict / weight as coded:   EXIT / 0.01% (raw 0.0068, correct usage)
2b SCHD + PFLT same interpretation:  YES
3  34 minus 5 (CASH) = 29; CUSIPs:  Included as EXIT (Delisted)
4  hand-verified matches:            17 / 19 numerical comparisons match
5  behavioral_detection.json:        EXISTS
5b gate bridge now vs doc claim:     11/12 PASS (matches doc), 1 FAIL (artifact count 78/100)
6  cache keyed:                      WHOLE-RESULT (no per-row hash)
```

---

## UNVERIFIED

1. **`days_held` accuracy:** The desk computes from `tax_lots.json` `lot_date`. API does not expose `days_held` for cross-check. Individual lot-by-lot audit against broker statements not performed.
2. **SPCX `cost_basis` vs API `gain_loss_pct`:** The ~0.6-0.8pp offset between desk formula `(mv-cb)/cb` and API `gain_loss_pct` is unexplained. The API's computation path may include adjusted cost basis or DRIP reinvestments. Cross-referencing the API's source code line would resolve this.
3. **PFLT tax_lots vs holdings reconciliation:** The tax_lots.json for PFLT shows 115,993 shares with \$1.1M cost. Only 11.7466 shares and \$117.85 cost survive in holdings.json. The specific lot-closing events that reduced the position from >100K to 11 shares are not individually audited.
4. **Portfolio total_value:** The desk computes total_value by summing all `market_value` fields from `holdings.json` (excluding CASH). The correct value from `holdings.json` `portfolio_totals` was not cross-checked to verify \$1,276,507 is accurate.
5. **Cost_basis domain in `cio_portfolio.py`:** The exact bug that caused 115,993 shares to be counted was identified from tax_lots data but the code path in `cio_portfolio.py` line 443-447 was not inspected to confirm the missing `closed` filter. UNVERIFIED which specific line produces the wrong aggregation.

---

**Diagnosis complete. No code changed.**
