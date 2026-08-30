# CIO Diligence P1-WS2 — Event lifecycle census baseline

Date: 2026-08-30  
Authority: READ_ONLY_ADVISORY  
MBI_BEHAVIOR: 0  
Rails: no broker write · no notify-on · no history DELETE · do not promote

## Delivered

| Artifact | Path |
|----------|------|
| Census CLI | `scripts/cio_event_lifecycle_census.py` (`--json` / human; fail-soft) |
| Baseline audit | `docs/audits/diligence/P1_WS2_EVENT_LIFECYCLE_BASELINE_2026-08-30.md` |
| Evidence JSON | `docs/audits/diligence/evidence/P1_WS2_event_lifecycle_census_2026-08-30.json` |
| Test | `tests/test_cio_diligence_p1_ws2_lifecycle.py` |

## Headline numbers (pin `852ecd47`)

| Signal | Value |
|--------|-------|
| Event-weighted full lifecycle | **2.17%** (862 / 39752 recoverable) |
| Unweighted mean full lifecycle | **67.16%** |
| Catalyst family full lifecycle | **1.49%** (dominates volume via binder skips) |
| security / sector families | ~100% recoverable on live+rebuild; archive gaps 20% / 7% |
| Lineage overlay | **406 / 752 (53.99%)** complete_to_checkpoint |
| claim_99.99 | **false** |

Top catalyst drops: `symbol_not_registered=35928`, `entity_has_no_issuer=2962`.

## Ops notes

- Census defaults to CURRENT; hermes catalysts may resolve via persistent-state fallback when CURRENT `data/hermes` lacks `momentum_catalysts`.  
- Re-measure anytime with the CLI; refresh evidence JSON on material store changes.  
- Scoreboard marks **P1-WS2 = DONE**; resume cursor remains **P1-WS1** (first non-DONE).  
- G-LOOP-01 / G-PRICE-01 notes updated in gap register — neither closed.

## Next

P1-WS1 architecture as-built · P9 99.99% hardening path (catalyst identity bind).
