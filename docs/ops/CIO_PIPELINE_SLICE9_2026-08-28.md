# CIO Pipeline Slice 9 — CASE_SUMMARY as lesson supporting context

Date: 2026-08-28
Authority: READ_ONLY_ADVISORY
MBI: 0

## What this slice did

`build_lesson_candidates` now includes CASE_SUMMARY ACTIVE as **supporting context**. Status PROVISIONAL. Promotion cap REVIEW_READY. `cannot_become_policy=True`. Dedup (symbol, plan_id, hermes_result_id). Hermes result taken from `res_*` source_refs (not `rr_*`). MBI=0.

## Live dry

candidates 324 (was ~1 from outcomes); **case_summary_support_added=323**. written=0 (dry). All 323 have `res_*` hermes_result_id.

## After promote

SOURCE *(filled after exact-main promote)*
written *(filled if --apply)*
