# CIO Wave 2 Slice 09 — CioHub coverage card

Date: 2026-08-28
Authority: READ_ONLY_ADVISORY
MBI: 0

## What

In `apps/command-center-v3/src/pages/CioHub.tsx`:

- Extended `Home` with optional `coverage?: OfficeCoverage`
- `CoverageCard` after `TrustStrip` in `CioNowSection`
- `data-testid="cio-coverage-card"`
- No Telegram producer / send

## Dry

```bash
rg 'cio-coverage-card|CoverageCard|home.coverage' apps/command-center-v3/src/pages/CioHub.tsx
.venv/bin/pytest -q tests/test_cio_wave2_slice09_coverage_card.py
# optional UI typecheck
cd apps/command-center-v3 && npx tsc --noEmit -p tsconfig.json
```
