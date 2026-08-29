# CIO Wave 2 Slice 10 — reentry keys not 0 when Surface A has names

Date: 2026-08-28
Authority: READ_ONLY_ADVISORY
MBI: 0

## Problem

Home `opportunities.reentry_total` came only from the **queue** pipe (`build_opportunities`). When the queue had no reentry-labeled rows, `reentry_total` was 0 even though Surface A `reentry_book` / operator `reentry.count` was ~67.

## Fix

`overlay_surface_a_reentry_on_opportunities` in `cio_command_center.py`, called from `build_office_home`:

- Preserves queue chips (`opportunities.reentry`) — **does not merge books**
- Stamps `surface_a_reentry_count` / `_near` / `_reenter`
- Sets `reentry_total` to NEAR+REENTER when Surface A count > 0; falls back to full book count if both actionable buckets are 0 but names/count exist
- Documents dual pipes in `reentry_pipes` (`merged: false`)

Investment product `reentry_book.count` was already non-zero; this slice aligns **home opportunities**.

## Dual pipes

| Pipe | Keys | Meaning |
|------|------|---------|
| Queue | `reentry`, `queue_reentry_total` | Opportunity-queue chips for the home card |
| Surface A | `surface_a_reentry_*`, overlays `reentry_total` | Former-holdings book vs exit trigger |

Wave 1 slice 3: two reentry books labeled, not merged — unchanged.

## Dry

```bash
.venv/bin/pytest -q tests/test_cio_wave2_slice10_reentry_overlay.py
PYTHONPATH=. .venv/bin/python -c "
from scripts.lib.cio_command_center import build_office_home
h = build_office_home(operator_product={'reentry':{'count':67,'counts':{'NEAR':4,'REENTER':0}}})
print(h['opportunities']['reentry_total'], h['opportunities']['surface_a_reentry_count'], h['opportunities']['reentry_pipes'])
"
```
