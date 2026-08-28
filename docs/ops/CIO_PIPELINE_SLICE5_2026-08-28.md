# CIO Pipeline Slice 5 — draft-plan warehouse hygiene

Date: 2026-08-28
Authority: READ_ONLY_ADVISORY
Branch: `feat/cio-pipeline-slice5-draft-plan-hygiene`

## What this slice did

Expire **draft** plans that have no `hermes_result_id`, `revisit_at` in the past, and are not S5/S6. Status → `cancelled` via PLAN_STATUS_CHANGED. JSONL history is append-only (never deleted). CLI dry-run default; `--apply` writes.

CLI: `python3 scripts/cio_draft_plan_hygiene.py` / `--apply`.

## What this slice did not do

- No delete of jsonl
- No notify
- No S5/S6 expiry
- No plans with hermes_result_id

## Live dry (pre-apply)

would_expire **263**. Samples: stale S2_STOP_GAP drafts from 2026-08-12 (SPACEX_TEST, AMANX, ARKX, BAH, BND, …).

`--apply` after promote if samples still look right.

## After promote (fill live)

| Metric | Value |
|---|---|
| SOURCE | *(filled)* |
| would_expire | 263 |
| expired | *(filled after --apply)* |
