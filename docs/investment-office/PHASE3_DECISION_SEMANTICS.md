# PHASE 3 CLOSEOUT — Decision Semantics Hygiene

**UTC:** 2026-08-14  
**Branch:** `wt/cio-phase1-notify`  
**Module:** `scripts/lib/cio_decision_semantics.py`  
**Authority:** `READ_ONLY_ADVISORY` unchanged  

## Scope (from hardening program)

> Clean the decision semantics. One canonical decision surface; aggregate
> duplicate symbol/account rows; eliminate `HOLD + TRIM` contradictions;
> convert internal enums to professional prose; reject pseudo-sectors like
> `Iwm−Spy`; require ticker identity proof before CIO output.

## Root causes fixed

| Defect | Cause | Fix |
| --- | --- | --- |
| HOLD + “Advisory TRIM — SCHD” | Queue items often have `verdict=null` with the signal only in `directive_label`; `stance_for` ignored labels | Infer stance from labels; multi-item precedence EXIT>TRIM>RE_ENTER>ADD>HOLD |
| Duplicate V / SCHD rows | Per-account holdings emitted as separate decision rows | `aggregate_position_decisions` — one row per symbol, sum $, recompute weight |
| Pseudo-sector `Iwm−Spy` | `canonical_sector` title-cased unknown pairs into the opportunity surface | Reject spread/pair pseudo-sectors; GICS-only filter for report posture |
| `STAGED_DEPLOYMENT` leaks | Raw enums rendered into report / priorities | `professional_label` / `professional_stance` on operator surfaces |
| Ambiguous tickers (YOU) / CUSIPs | No identity gate | `symbol_identity_status` requires a name for ambiguous/CUSIP symbols |
| Allocation `578107.50%` | USD map formatted with `_pct()` | Renderer converts dollar allocation → weight % + shows USD |

## Live proof (2026-08-14)

Holdings + live opportunity queue + sector synthesis:

**Decisions now (aggregated, coherent stance):**

| Symbol | Stance | Value | Delta | Why |
| --- | --- | ---: | ---: | --- |
| SCHD | **Trim** | $225,922.59 | −$22,592 | Advisory TRIM — SCHD |
| V | **Trim** | $121,133.90 | −$12,113 | Advisory TRIM — V |
| SPCX | **Trim** | $28,302.00 | −$2,830 | Advisory TRIM — SPCX |
| DXCM | **Trim** | $20,574.00 | −$2,057 | Advisory TRIM — DXCM |
| AMANX | **Trim** | $5,165.60 | −$517 | Advisory TRIM — AMANX |

- No HOLD+TRIM contradictions  
- No duplicate symbols  
- Sector posture: Technology / Energy / Communications / Real Estate only — **no `Iwm−Spy`**  
- Recommendations shown as “Staged deployment” / “No deployment” / “Research first”  
- Allocation weights: Cash **45.08%**, Equities **54.92%** (not 578107%)

## Code

| File | Role |
| --- | --- |
| `scripts/lib/cio_decision_semantics.py` | **NEW** pure Phase 3 helpers |
| `scripts/lib/cio_capital_plan.py` | `stance_for` + aggregated position decisions |
| `scripts/lib/cio_sector_opportunity.py` | Pseudo-sector rejection in `canonical_sector` |
| `scripts/lib/cio_report_v2.py` | Decisions / sector posture / priorities sanitized |
| `scripts/lib/cio_command_center.py` | `_action_hint` uses resolve + professional stance |
| `scripts/render_cio_report_files.py` | Allocation USD → weight table |
| `tests/test_cio_decision_semantics.py` | **NEW** |

## Tests

```
tests/test_cio_decision_semantics.py     10 passed
tests/test_cio_capital_plan.py           43 passed
tests/test_cio_sector_opportunity.py     …
tests/test_cio_report_v2.py              …
tests/test_cio_command_center.py         …
────────────────────────────────────────
122 passed (related suite)
```

## Non-goals (later phases)

- Full single report architecture (Phase 4)  
- Institutional visual chart suite (Phase 5)  
- Analytical completeness / TWR (Phase 6)  
- Production pipeline + immutable manifests (Phase 7)  
- Telegram canary (Phase 9)  

## Safety

## REAL TELEGRAM SENDS: 0  
## BROKER CALLS: 0  
## SECRETS PRINTED: 0  
## FINANCIAL AUTHORITY CHANGED: NO  

## Next phase allowed

Phase 4 — one reporting architecture (shared model → HTML/PDF/DOCX/CC).
