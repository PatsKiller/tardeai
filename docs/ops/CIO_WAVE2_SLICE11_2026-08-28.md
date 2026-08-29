# CIO Wave 2 Slice 11 — thesis_count vs held_n on home

Date: 2026-08-28
Authority: READ_ONLY_ADVISORY
MBI: 0

## What

Coverage object exposes aliases clearly:

- `thesis_count` ≡ `with_thesis` ≡ `holdings_thesis_coverage.current_n`
- `held_n` ≡ `held` ≡ `holdings_thesis_coverage.held_n`

CioHub coverage card primary stat: **Thesis / held** → `thesis_count/held_n` (expect ~19/19 unless universe moved).

## SCHG dust honesty

`held_equity_symbols` may still include SCHG residual dust. Surface A correctly classifies SCHG as **EXITED** (not HELD). Slice 11 does **not** silently change `held_n` semantics — dust remains in the held-equity list if present. Operator: SCHG is former.

## Dry

```bash
.venv/bin/pytest -q tests/test_cio_wave2_slice11_thesis_held.py
rg 'Thesis / held|thesis_count|held_n|SCHG dust' apps/command-center-v3/src/pages/CioHub.tsx scripts/lib/cio_command_center.py
```
