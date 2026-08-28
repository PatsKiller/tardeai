# CIO Pipeline Slice 8 — OutcomeCheckpoint for held researched plans

Date: 2026-08-28
Authority: READ_ONLY_ADVISORY
Branch: `feat/cio-pipeline-slice8-outcome-checkpoints`

## What this slice did

Bind `OutcomeCheckpoint@v1` via existing `bind_material_decision` for **open plans with hermes_result_id whose symbols are currently held equities**. Observational only. Skip CASH sleeve, S5, HOLD_CASH, and the Pathward CASH ticker trap. No invented PnL. Dry CLI default; `--apply` writes 1_session checkpoints.

## Live dry

eligible **152** / held **19**. Skipped: no_hermes 212, not_open 269, not_held 155, s5_cash 16.
Samples: XLI, SCHD, JEPI (held equities). No CASH sleeve.

`--apply` after promote.

## After promote

| Metric | Value |
|---|---|
| SOURCE | *(filled)* |
| eligible | 152 |
| wrote | *(filled)* |
