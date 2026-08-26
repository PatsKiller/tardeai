# PHASE 1 CLOSEOUT — Acceptance harness v4 (fail-closed)

**UTC:** 2026-08-14  
**Authority:** `READ_ONLY_ADVISORY`  
**Version:** `cio_acceptance_v4.0.0`

## Why

The v3 scorecard awarded **97/100 PASS** while the book was `CONFLICTED`, PDF was absent, strategy facts were unverified, and `p0_p1_open` was non-empty. That is not acceptance.

## Forbidden behaviors removed

| Old behavior | v4 |
| --- | --- |
| Points because FinancialTruthGate *ran* | G4 FAIL unless book is VERIFIED_* and invariants hold |
| Gate PASS when quality=CONFLICTED | Impossible |
| HTML-only report PASS | G11/G12 FAIL if PDF/DOCX missing |
| Synthetic $100k report | `report_synthetic=True` fails G10–G12 |
| `or True` Telegram credit | Static AST test forbids `or True`; G14 FAIL unless general-sends **measured** |
| `general_not_used: True` written | Unproven → FAIL |
| Strategy 10/10 for 3 seed facts | G20 is honesty only; Almanac/research categories stay FAIL |
| Offline union with live | `evaluate_live_snapshot` has no offline fill |
| PASS while P0/P1 open | G19 + finalize_verdict force FAIL |

## Hard gates (all required)

G1 exact live SHA · G2 committed manifest parity · G3 Drive parity · G4 book reconciliation · G5 zero material price conflicts · G6 freshness (no `evaluated_now`) · G7 capital-plan invariants · G8 decision parity · G9 Advisory+CIO UI live · G10–G12 live HTML/PDF/DOCX · G13 visual QA · G14 Telegram isolation (measured) · G15 exact-release canary · G16 zero duplicate · G17 READ_ONLY_ADVISORY · G18 cio-hardening green · G19 no P0/P1 · G20 strategy grades honest.

`NOT_RUN` / unproven is **FAIL**, not PASS.

## How to run

```bash
python3 scripts/run_cio_acceptance.py
# exit 1 unless PRODUCTION_ACCEPTANCE=PASS
```

Evidence: `data/audit/cio_acceptance_YYYYMMDD/ACCEPTANCE_SCORECARD.json`

`STOCK_ALMANAC_INTEGRATION` and `BROADER_RESEARCH_BRAIN` remain **FAIL** until later phases prove reproduction — even if G20 (honesty) passes.

## Tests

`tests/test_cio_acceptance_v4.py` — wired into `run_cio_hardening_ci.py`.
