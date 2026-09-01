# Held-book thesis coverage (Phase 1) — 2026-08-20

Status:      HISTORICAL
as_of:       2026-08-20T21:01:28-04:00
Measured at: efcc51365 / not measured

**READ_ONLY_ADVISORY.** First Build of the autonomous advisor spine.

## Problem

Host proof: **3/25** held theses CURRENT, **22** RESEARCH_REQUIRED. Sensors exist; living memory for the book does not.

## What shipped

| Piece | Path |
|-------|------|
| Coverage SLA lib | `scripts/lib/cio_held_thesis_coverage.py` |
| CLI | `scripts/cio_held_thesis_coverage.py` |
| Report artifact | `data/cio/held_thesis_coverage_latest.json` |
| Revision ledger | `data/cio/thesis_revision_ledger.jsonl` (catalyst reassess stub; notify **dry**) |

Reuses `run_symbol_thesis_acquisition.run` for acquire/publish — no parallel thesis stack.

## Ops

```bash
cd CURRENT && export PYTHONPATH=.:scripts
# SLA report
python3 scripts/cio_held_thesis_coverage.py --report

# Dry acquisition for up to 5 held gaps
python3 scripts/cio_held_thesis_coverage.py --acquire --limit 5

# Apply (LLM + publish) — off-peak, respect cost caps
python3 scripts/cio_held_thesis_coverage.py --acquire --apply --limit 3 --max-llm 3

# Catalyst medium+ → revision ledger (no Telegram yet)
python3 scripts/cio_held_thesis_coverage.py --reassess-catalysts --limit 20
```

Suggested cron (after promote): weekday off-peak coverage report + bounded apply.

## Next (Phase 2)

Material advisor cards + `CIO_THESIS_CATALYST_NOTIFY_CANARY` for Telegram delivery.
