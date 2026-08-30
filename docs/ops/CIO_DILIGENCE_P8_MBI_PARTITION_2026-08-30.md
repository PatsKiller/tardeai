# CIO Diligence P8 — outcome/lesson MBI partition

Date: 2026-08-30  
Authority: READ_ONLY_ADVISORY  
MBI_BEHAVIOR: 0 immutable  
Gap: G-MBI-01  

## Delivered

| Artifact | Path |
|----------|------|
| Audit note | `docs/audits/diligence/P8_MBI_PARTITION_2026-08-30.md` |
| CI / property suite | `tests/test_cio_diligence_p8_mbi_partition.py` |
| Partition source | `scripts/lib/cio_instrument_record.py` |
| Product stamp | `scripts/lib/cio_operator_product.py` (`MBI = 0`) |

## Proof

- Lessons may move research question, eligibility, notify priority, narrative.
- Behavior fields (`size_usd`, `qty`, `order`, `recommended_delta_usd`, …) raise `BehaviorWriteRefused`.
- Instrument records and operator product module stamp `memory_behavior_influence = 0`.
- AST + grep CI gate: MBI never assigned to a positive integer in stamp modules.

## Rails

No broker write. No notify-on. No Telegram producer. No promote in this package.

## Scoreboard

Package **P8** → DONE (this PR). G-MBI-01: CI gate landed (standing live-env control retained on scoreboard rails).
