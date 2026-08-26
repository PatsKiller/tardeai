# PHASE 7 — Wire `/v3/advisory` provenance UI

**UTC:** 2026-08-14  
**Authority:** `READ_ONLY_ADVISORY` unchanged  
**Version:** `advisory_provenance_1.1.0`  
**Scope:** Isolated worktree `tradeai-wt-investment-office-convergence`

## Problem

The Advisory Desk expanded row forced the operator to reverse-engineer marks:

| Surface | Failure |
| --- | --- |
| Price action | “From cost basis” with no canonical mark / as-of / source |
| Analyst | `vs current` used a **Yahoo snapshot print** (DXCM historically ~$70) |
| Holdings MV | Could disagree with `shares × current_price` (DXCM 225 × $91.26 ≠ $20,470.50) |
| Opinion synthesis | Empty Maria/Guardian stance was treated as **HOLD** |

## Contract

Every `/api/v3/advisory` row now carries:

- `expand.canonical_financial_facts`
- `expand.advisory_provenance`
- honest `expand.analyst` denominators

### `canonical_financial_facts`

| Field | Operator label |
| --- | --- |
| `current_mark` | Current mark |
| `as_of` | As of |
| `source` | Source |
| `shares` | Shares |
| `market_value` | Market value |
| `total_cost_basis` | Total cost basis |
| `avg_cost_per_share` | Avg cost/share |
| `unrealized_pl` / `unrealized_pl_pct` | Unrealized P/L |
| `quality` | Quality (`VERIFIED_AS_OF` / `CONFLICTED` / `STALE` / `DATA_UNAVAILABLE`) |

Conflicts set `action_suppressed=true` and banner **`DATA CONFLICT — ACTION SUPPRESSED`**.

### Analyst — two upsides, one honest label

| Field | Meaning |
| --- | --- |
| `target` / `target_as_of` | Consensus mean target + snapshot date |
| `target_upside_vs_current` | Target vs **canonical holdings mark** |
| `target_upside_vs_provider_snapshot` | Target vs Yahoo/provider historical print |
| `denominator_price` / `denominator_as_of` | The print actually used for the labeled historical upside |
| `denominator_is_canonical_current` | True only when snapshot ≈ canonical mark |
| `target_vs_current_pct` | **Populated only when** `denominator_is_canonical_current` |

A stale Yahoo `current_price` column is stored as `provider_snapshot_price`. It is never copied onto the holdings mark.

### Opinion synthesis

Missing desk opinion is **not HOLD**.

- Both Maria and Guardian explicitly HOLD + deterministic TRIM → “Fundamental desks remain HOLD…”
- Blank / omitted stances → “missing opinion is not HOLD”
- One explicit HOLD + one missing → name the explicit desk; do not say “desks remain HOLD”

## Wiring

| Layer | Change |
| --- | --- |
| `scripts/lib/cio_advisory_provenance.py` | `build_canonical_financial_facts`, `build_analyst_provenance_fields`, `attach_expand_provenance` |
| `scripts/lib/data_broker/advisory_desk.py` | Preserve dual price fields; rewrite analyst loader; `attach_advisory_row_provenance` on every row |
| `scripts/api_v3_advisory.py` | `_row_view` exposes expand facts + provenance; banner `DATA_CONFLICT` |
| `apps/command-center-v3/src/pages/AdvisoryDeskHub.tsx` | **Current financial facts** block first; no blind “vs current” |

## DXCM-shaped expanded row (how it renders)

Inputs (Phase 0 / Phase 2 shape):

- 225 shares · `current_price` $91.26 · `price` $90.98 · MV $20,470.50 · cost $15,985.13
- Analyst target $119 as of 2025-11-01 vs provider snapshot **$70**

Expanded card:

1. **Banner (red):** `DATA CONFLICT — ACTION SUPPRESSED`  
   `canonical mark (91.26) ≠ implied-from-MV (90.98)` · `shares×price (20533.50) ≠ market_value (20470.50)` · analyst denominator ≠ canonical mark.  
   (`price` $90.98 is the MV-implied print, not a second genuine mark.)
2. **Current financial facts** (first card)  
   Current mark **$91.26** · As of holdings timestamp · Source `holdings.json` / `current_price` · Shares **225** · Market value **$20,470.50** · Implied from MV **$90.98** · Total cost basis **$15,985.13** · Avg cost/share **$71.04** · Unrealized P/L **+$4,485.37 / +28.06%** · Quality **CONFLICTED**
3. **Analyst**  
   Target **$119.00** · Target as of **2025-11-01**  
   Upside vs canonical current **+30.4%** (vs $91.26)  
   Upside vs provider snapshot **+70.0%** (vs $70.00 as of 2025-11-01)  
   Denominator labeled **provider snapshot** — never “vs current”
4. **Price action** still shows “From cost basis” (that metric is vs basis, not vs mark) plus mark / as-of / source when attached
5. **Opinion** — if Maria/Guardian are absent: synthesis says missing opinion is **not HOLD**

Desk table data-quality cell also shows `· DATA CONFLICT` on the row.

## Tests

```
tests/test_cio_advisory_provenance.py
  - clean facts + honest vs-canonical upside
  - DXCM dual-price / MV conflict
  - explicit HOLD synthesis (legacy)
  - missing / blank stance is not HOLD
  - stale $70 snapshot not labeled vs current
  - advisory_desk.attach_advisory_row_provenance mock row
```

UI grep: `AdvisoryDeskHub.tsx` contains `Current mark` / `canonical`; no blind `vs current` label.

## Safety

## REAL TELEGRAM SENDS: 0  
## BROKER CALLS: 0  
## FINANCIAL AUTHORITY CHANGED: NO  

`READ_ONLY_ADVISORY` — no broker, no order, no stop, no 2FA.
