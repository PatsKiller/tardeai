# G-IR-01 mitigation — InstrumentRecord wake load

**Date:** 2026-08-30  
**Authority:** READ_ONLY_ADVISORY · MBI_BEHAVIOR=0  
**Gap:** InstrumentRecord not universal wake load

## Fix shipped

1. `load_instrument_record_for_wake(...)` in `scripts/lib/cio_instrument_record.py`  
   Returns explicit `LOADED | IR_MISSING | IR_ERROR | NO_SUBJECT` — never silent empty.
2. S0 `rehydrate()` attaches `instrument_record_wake` and folds tip `last_outcome` /
   `last_artifact_id` into the research gate inputs when present.
3. SpecialistArtifact `append()` success path stamps IR tip `last_artifact_id`
   when subject_key / symbol is known (fail-soft).

## Rails

- No broker writes · no notify-on · MBI stays 0 on tip updates  
- Missing store → `IR_MISSING` / `IR_ERROR`, home/S0 do not crash  

## Tests

`tests/test_cio_gap_ir_01.py`

## Residual

Producers that still side-store without calling wake/append helpers remain a
follow-up inventory; new wake path is wired for S0 + specialist append.
