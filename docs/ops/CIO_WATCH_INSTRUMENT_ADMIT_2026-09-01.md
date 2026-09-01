Status:      ACTIVE  
as_of:       2026-09-01T17:30:00-04:00  
Measured at: origin/main tip at branch open (contains #834 / `433511415`)  
Canonical repo path: docs/ops/CIO_WATCH_INSTRUMENT_ADMIT_2026-09-01.md  
Authority:   ops record for WATCH InstrumentRecord admission  
See also:    docs/ops/litmus/LITMUS_COVERAGE_2026-09-01.md  
             docs/audits/overnight/CC_WATCH_INTELLIGENCE_WIRING_2026-09-01.md  
             scripts/lib/cio_instrument_record.py · scripts/cio_migrate_instrument_records.py

# Admit WATCH instrument records (cognition only)

## Verdict

**Promote: NO** unless the operator says so.  
#831–#834 out of scope (not redone). No cash_letter / wake persist / lane / #777.

## Problem

Live `cio_instrument_records` had **0 WATCH** rows (HELD 15 · EXIT 24 · SLEEVE 1).
Migration seeded HELD/EXIT/SLEEVE only. Research-budget `reentry_or_watch` and
CIO home watch narratives therefore had no spine to load.

## Change

| piece | what |
|---|---|
| `scripts/lib/cio_watch_instrument_admit.py` | `admit_watch_records` — watchlist.json → `new_record("WATCH")` + `apply_cognition` · **cap 20** · `notify_priority=none` |
| `scripts/cio_admit_watch_instrument_records.py` | CLI, dry-run default, `--apply` to persist |
| `scripts/cio_migrate_instrument_records.py` | calls the same admit path for WATCH |
| tests | cap / skip existing / dry-run / BehaviorWriteRefused / no S7·Maria imports |

## Explicit non-goals

- No Maria / watch-review workers  
- No S7 plan fire / situation detector  
- No Telegram / notify-on  
- No holdings write · no `$PROJ` FF · no promote  

## Operator

```
cd $CURRENT
python3 scripts/cio_admit_watch_instrument_records.py          # dry-run
python3 scripts/cio_admit_watch_instrument_records.py --apply  # persist ≤20
```
