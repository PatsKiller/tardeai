# P2-WS4 — Identity confidence score

**Date:** 2026-08-30  
**Authority:** READ_ONLY_ADVISORY · MBI_BEHAVIOR=0 · INTERDICT left as found  
**CURRENT pin:** `852ecd47` (#681)  
**Live root:** `/home/johnclaw/trade-ai-releases/portfolio-server/CURRENT` (+ persistent-state overlay for registry/holdings)  
**Harness:** `scripts/cio_identity_confidence_census.py --json`  
**Measured at:** `2026-08-30T04:45:44+00:00`  
**Minted identities:** **0** · **Lots deleted:** **0** · **Do not promote** (this PR is advisory evidence only)

---

## Confidence score definition (`IdentityConfidenceScore@v1`)

Promotion-grade **production records** =

- **HELD material** — equity ticker, ≥1 share, **not** `DUST_RESIDUAL` under holdings `$50` MV policy  
- **ACTIVE watch** — unique symbols on `opportunity_book.top` ∪ `watch_block_summary.top`  
- **EXIT** — former-table row (`collect_previously_traded`)

**Excluded:** CASH, CUSIP/ISIN/`UNKNOWN_INSTRUMENT_ID` held-as-symbol, MV dust residuals.

| Component | Weight | Meaning |
|-----------|-------:|---------|
| `resolvable` | 0.50 | `identity_registry.lookup_symbol` answers today |
| `confirmed` | 0.30 | mean status score: CONFIRMED=1.0 · CANDIDATE=0.6 · UNRESOLVED_WITH_REASON=0.2 · MISSING=0.0 |
| `stamped` | 0.20 | payload row carries `subject_guid` (carriage, not registry) |

```
cohort_score = 0.50 * resolvable_frac + 0.30 * mean(status_score) + 0.20 * stamped_frac
```

**Target:** **100% resolvable** for production records. Stamped carriage is measured separately (Wave 2 slice 13 lesson: one number lies). This package **never mints** and **never auto-stamps**.

**Never:** ticker-as-security-GUID regression · lot DELETE · registry write from this census.

---

## Live numbers (CURRENT / overlay)

Registry: **10,279** entities · **5,277** symbols.

### Product surfaces (slice-13 extended)

| Surface | n | resolvable % | stamped % | confidence_score |
|---------|--:|-------------:|----------:|-----------------:|
| `new_position_if` | 5 | **100.0** | **100.0** | **1.0000** |
| `reentry_book` | 70 | **100.0** | 0.0 | 0.7966 |
| `opportunity_book` | 28 | **100.0** | 0.0 | 0.8000 |
| `watch_block` (top sample) | 2* | **100.0** | 0.0 | 0.8000 |
| **slice-13 total (NPI+reentry+opp+watch top)** | 105 | **100.0** | **4.8** | — |

\* `watch_block_summary.top` is a capped/ready sample and can vary by product build; use **active_watch** below as the durable watch cohort.

### Watch / exit / holdings / production

| Cohort | n | resolvable % | stamped % | confidence_score | notes |
|--------|--:|-------------:|----------:|-----------------:|-------|
| **active_watch** (opp ∪ watch) | 30 | **100.0** | 0.0 | 0.8000 | |
| **exit_former_table** | 49 | **98.0** | 0.0 | 0.7788 | unresolved: **HEALTH** |
| **holdings_equity** (tickers) | 19 | **100.0** | 0.0 | 0.8000 | all CONFIRMED |
| **holdings_held_nondust** | 15 | **100.0** | 0.0 | 0.8000 | all CONFIRMED |
| **production_records** | 89 | **98.9** | 5.6 | **0.7996** | unresolved: **HEALTH**; status mix CONFIRMED 87 / UNRESOLVED_WITH_REASON 1 / MISSING 1 |

### CUSIP vs ticker

| Class | n | Detail |
|-------|--:|--------|
| Equity tickers (held) | 19 | resolvable 100%; stamped 0 on holdings rows |
| HELD nondust ($50 policy) | 15 | AMANX ARKX BAH BND CSWC DIV NOC PFLT RTX SCHD SPCX V XAR XLB XLI |
| DUST_RESIDUAL ($50 MV) | 4 | JEPI · LDOS · SCHG · SRNE |
| **instrument_id (CUSIP)** | **3** | `12507E201` · `543354104` · `628518102` — `is_ticker=false`; **not** in ticker resolvable % |

CUSIP rows stay `instrument_id`, never rendered as ticker, never production ticker records.

---

## Findings

1. **Registry gap is nearly closed for the live book** — HELD nondust and active watch are 100% resolvable / CONFIRMED.  
2. **Carriage gap remains** — only `NEW_POSITION_IF` stamps `subject_guid` (5/5); reentry / opportunity / watch / holdings ship 0% stamped. Same as Wave 2 slice 13.  
3. **Production target 100% resolvable: not met** — **98.9%** (88/89). Sole miss: former-table symbol **HEALTH** (MISSING in registry). Tracked under **G-ID-01**.  
4. **No mint / no stamp / no lot DELETE** in this package.

---

## Rails

| Rail | State |
|------|-------|
| MBI | 0 |
| Identities minted | 0 |
| Registry written | no |
| Rows stamped by this package | 0 |
| Lots deleted | no |
| Broker / notify | none |
| Promote | **Do NOT promote** |

## Proof

- Script: `scripts/cio_identity_confidence_census.py` + `scripts/lib/cio_identity_confidence_census.py`  
- Tests: `tests/test_cio_identity_confidence_census.py`  
- Reuse: `cio_identity_coverage` (slice 13), `identity_registry`, `holdings_universe`
