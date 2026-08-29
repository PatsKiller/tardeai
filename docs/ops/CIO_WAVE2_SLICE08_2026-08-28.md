# CIO Wave 2 Slice 08 — coverage object on /v3/cio/home

Date: 2026-08-28
Authority: READ_ONLY_ADVISORY
MBI: 0

## What

`build_office_coverage(...)` in `scripts/lib/cio_command_center.py` returns Class D:

| Key | Source |
|-----|--------|
| held / held_n | holdings_thesis_coverage.held_n |
| with_thesis / thesis_count | holdings_thesis_coverage.current_n |
| with_plan | open injected plans ∩ held symbols |
| with_research | subset of with_plan that have hermes_result_id |
| with_case_summary | case_summaries.count |
| watch_ready | len(watch_block_summary.ready_symbols) |
| watch_block | watch_block_summary.count |
| reentry_near | operator reentry.counts.NEAR |

Wired as `home["coverage"]` from existing op/product keys. Fail-soft zeros. No new route. No Telegram.

## Caveat

`get_cio_home` injects `plans` with `limit=12`, so live `with_plan` / `with_research` are a lower bound from that sample until a fuller plans inject lands.

## Dry

```bash
PYTHONPATH=. .venv/bin/python -c "
from scripts.lib.cio_command_center import build_office_coverage
print(build_office_coverage(
  holdings_thesis_coverage={'held_n':19,'current_n':19,'items':[]},
  watch_block_summary={'count':21,'ready_symbols':[]},
  case_summaries={'count':323},
  reentry={'counts':{'NEAR':0},'count':67},
))
"
.venv/bin/pytest -q tests/test_cio_wave2_slice08_coverage.py
```
