# P2-WS5 — Position state matrix (HELD / EXIT / WATCH / CASH / DUST)

**Date:** 2026-08-30  
**Authority:** READ_ONLY_ADVISORY · MBI_BEHAVIOR=0 · INTERDICT left as found  
**CURRENT pin:** `852ecd47` (#681)  
**Live root:** `/home/johnclaw/trade-ai-releases/portfolio-server/CURRENT`  
**Harness:** `scripts/cio_identity_confidence_census.py --json` → `position_state`  
**Measured at:** `2026-08-30T04:45:44+00:00`  
**Lots deleted:** **0** · **Do not promote**

---

## States

| State | Rule (source of truth) |
|-------|------------------------|
| **HELD** | Material equity: shares ≥ **1.0** (Surface A) **and** not `$50` MV `DUST_RESIDUAL` for holdings-truth coverage |
| **EXIT** | Former-table row **or** Surface A residual dust (`0 < shares < 1` → `EXITED`) |
| **WATCH** | Active watch cohort = `opportunity_book.top` ∪ `watch_block_summary.top` |
| **CASH** | Cash sleeve rows (`is_cash` / CASH symbols) — **never** a security |
| **DUST** | Two labels (both **labels only** — lots untouched): share-rule `<1` · MV-rule `<$50` |

### Dual dust policies (do not collapse)

| Policy | Threshold | Effect | Fixture |
|--------|-----------|--------|---------|
| **Surface A share rule** | `shares < 1` | status **EXITED** (`residual_dust_not_material_held`) | **SCHG** 0.2294 sh |
| **Holdings truth MV** (`DUST_POLICY`) | aggregate MV **< $50** | label **DUST_RESIDUAL**; excluded from `held_n` | SCHG $8.10 · SRNE $0.90 |

SRNE shows why both exist: **1000 shares** / **$0.90** → Surface A **HELD** (share rule), holdings **DUST_RESIDUAL** (MV rule).

---

## Live counts (CURRENT)

| Bucket | n | Notes |
|--------|--:|-------|
| HELD nondust (MV policy) | **15** | thesis / coverage denominator |
| EXIT former table | **49** | previously traded |
| WATCH active | **30** | unique opp ∪ watch |
| CASH rows | **5** | aggregate MV **$630,784.82** |
| DUST share `<1` | **6** | BND JEPI LDOS NOC RTX SCHG |
| DUST MV `<$50` | **4** | JEPI LDOS SCHG SRNE |
| instrument_id CUSIP | **3** | never ticker |

HELD nondust symbols: AMANX · ARKX · BAH · BND · CSWC · DIV · NOC · PFLT · RTX · SCHD · SPCX · V · XAR · XLB · XLI  

*(Note: BND / NOC / RTX remain in the MV-policy HELD set because aggregate MV ≥ $50, but Surface A classifies each as EXITED under the share `<1` rule — see dust table.)*

---

## Dust table (live)

| Symbol | shares | MV $ | share `<1` | MV `<$50` | Surface A | label |
|--------|-------:|-----:|:----------:|:---------:|-----------|-------|
| SCHG | 0.2294 | 8.10 | ✓ | ✓ | **EXITED** | DUST_RESIDUAL |
| JEPI | 0.3892 | 22.41 | ✓ | ✓ | **EXITED** | DUST_RESIDUAL |
| LDOS | 0.2266 | 31.17 | ✓ | ✓ | **EXITED** | DUST_RESIDUAL |
| SRNE | 1000.0 | 0.90 | | ✓ | HELD | DUST_RESIDUAL |
| BND | 0.7707 | 55.80 | ✓ | | **EXITED** | EXITED_SHARE_DUST |
| NOC | 0.2317 | 127.67 | ✓ | | **EXITED** | EXITED_SHARE_DUST |
| RTX | 0.4934 | 103.57 | ✓ | | **EXITED** | EXITED_SHARE_DUST |

---

## Surface A default probe (SCHG-class regression)

`collect_surface_a_status` canonical probe:

| Symbol | status | reason | residual_shares |
|--------|--------|--------|----------------:|
| **SCHG** | **EXITED** | residual_dust_not_material_held | 0.2294 |
| AXTI | EXITED | previously_traded | — |
| FATN | EXITED | previously_traded | — |
| FANG | UNAVAILABLE | not_in_holdings_or_former_table | — |

**Invariant:** SCHG-class residual is **EXITED**, never HELD. No invented prices.

---

## Reentry pipes (not merged)

| Pipe | Live | Merged? |
|------|-----:|:-------:|
| Surface A `reentry_book.names` | 70 | **no** |
| Queue `opportunities.reentry_total` | null / separate | **no** |

Dual pipes stay labeled (Wave 2 slice 10 · G-DUAL-01). Exit→watch transitions remain distinct surfaces.

---

## Invariants verified

| Invariant | Result |
|-----------|--------|
| Dust never active position (Surface A `<1` → EXITED) | **pass** (SCHG EXITED) |
| Cash never security | **pass** (5 cash rows; excluded from equity) |
| CUSIP never ticker | **pass** (3 instrument_ids) |
| Reentry Surface A/B not merged | **pass** (`merged: false`) |
| Lots deleted | **false** |

---

## Rails

| Rail | State |
|------|-------|
| MBI | 0 |
| Lot DELETE | **none** |
| Broker / notify | none |
| Promote | **Do NOT promote** |

## Proof

- `collect_surface_a_status` · `holdings_universe.DUST_POLICY` · census `position_state`  
- Tests: `tests/test_cio_identity_confidence_census.py` (SCHG EXITED + dust table)  
- Existing: `tests/test_cio_wave2_slice04_surface_a_status.py`
