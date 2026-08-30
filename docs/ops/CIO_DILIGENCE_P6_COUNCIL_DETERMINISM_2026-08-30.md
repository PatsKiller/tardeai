# CIO Diligence P6 — council determinism

Date: 2026-08-30  
Authority: READ_ONLY_ADVISORY  
MBI_BEHAVIOR: 0  

## Delivered

| Artifact | Path |
|----------|------|
| Audit note | `docs/audits/diligence/P6_COUNCIL_DETERMINISM_2026-08-30.md` |
| Property / unit suite | `tests/test_cio_diligence_p6_council_determinism.py` |
| Cited join | `scripts/lib/cio_council_synthesis.py` |
| Cited Wave 3B pins | `tests/test_cio_wave3b_council_policy.py` |

## Proof

Same inputs → same `CIOCouncilSynthesis@v1` fields (clock frozen).  
`DISPUTED` preserved with all specialist ids. Non-VALID specialists appear only
in `excluded_non_valid`. No model call, no plan mint, no financial action.

## Rails

INTERDICT left as found. No Telegram. No notify-on. No promote in this package.

## Scoreboard

Package **P6** → DONE (this PR).
