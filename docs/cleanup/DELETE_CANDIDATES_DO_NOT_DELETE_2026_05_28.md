# Delete Candidates -- DO NOT DELETE - 2026-05-28

Files that COULD be cleaned up but MUST NOT be deleted. Treat every entry below as protected until the stated conditions are met.

---

## BLMN/APPS Repair Artifacts

| Path | Reason May Be Obsolete | Replacement File | Risk if Deleted | Recommended Action |
|------|----------------------|-----------------|----------------|-------------------|
| docs/atm_lifecycle_v1_2026_05_26/BLMN_DUPLICATE_REPAIR_2026_05_27.md | BLMN repair completed | None - unique evidence | Lose repair audit trail, cannot prove data integrity if questioned | KEEP until project closeout |
| docs/atm_lifecycle_v1_2026_05_26/BLMN_RECONCILIATION_CHECK_2026_05_27.md | Reconciliation completed | None - unique evidence | Lose proof of BLMN data quality verification | KEEP until project closeout |
| docs/atm_lifecycle_v1_2026_05_26/backups/blmn_duplicate_repair_20260527_191045/blmn_before_rows.txt | Repair completed | None - pre-repair snapshot | Lose ability to verify what was fixed | KEEP until project closeout |
| docs/atm_lifecycle_v1_2026_05_26/stop_trailing_timestop_v3_5_design/row_exports/APPS_REPAIR_ROW.txt | APPS repair completed | None - unique repair data | Lose APPS repair evidence | KEEP until project closeout |

## v3.8 LLM Backtesting (Active Work)

| Path | Reason May Be Obsolete | Replacement File | Risk if Deleted | Recommended Action |
|------|----------------------|-----------------|----------------|-------------------|
| docs/atm_lifecycle_v1_2026_05_26/LLM_BACKTESTING_V3_8_IMPLEMENTATION_REPORT.md | v3.8 Stage 1 is partial | Future v3.8 completion report | Lose implementation tracking | KEEP - active work |
| docs/atm_lifecycle_v1_2026_05_26/LLM_BACKTESTING_V3_8_STAGE1_IMPLEMENTATION_REPORT.md | Stage 1 v1 was partial | V2 report exists | Still needed for comparison with v2 | KEEP - shows evolution |
| docs/atm_lifecycle_v1_2026_05_26/LLM_BACKTESTING_V3_8_STAGE1_PROMPT_PARSER_DIAGNOSIS.md | Diagnosis for v2 fix | None - active diagnosis | Lose context for ongoing prompt/parser fixes | KEEP - actively referenced |
| docs/atm_lifecycle_v1_2026_05_26/LLM_BACKTESTING_V3_8_STAGE1_QUALITY_AUDIT.md | v1 quality issues found | None | Lose quality baseline | KEEP - comparison reference |
| docs/atm_lifecycle_v1_2026_05_26/LLM_BACKTESTING_V3_8_STAGE1_V2_IMPLEMENTATION_REPORT.md | Latest v3.8 Stage 1 | None - this is current | Lose current state of v3.8 | KEEP - source of truth |
| docs/atm_lifecycle_v1_2026_05_26/LLM_BACKTESTING_V3_8_STAGE1_V2_QUALITY_AUDIT.md | Latest quality audit | None - this is current | Lose quality verification | KEEP - source of truth |
| docs/atm_lifecycle_v1_2026_05_26/llm_backtesting_workflow_v3_8_design/ (56 files) | Design docs for v3.8 | None - still active | Lose design context for ongoing v3.8 work | KEEP entire directory |

## v3.9 Delayed Monthly Review (Blocked Work)

| Path | Reason May Be Obsolete | Replacement File | Risk if Deleted | Recommended Action |
|------|----------------------|-----------------|----------------|-------------------|
| docs/atm_lifecycle_v1_2026_05_26/llm_delayed_monthly_v3_9_design/ (17 files) | Blocked until v3.8 produces close_analysis rows | None - will be needed | Lose design work when v3.9 becomes unblocked | KEEP entire directory |

## v4.0 Backtest LLM Coverage (Just Implemented)

| Path | Reason May Be Obsolete | Replacement File | Risk if Deleted | Recommended Action |
|------|----------------------|-----------------|----------------|-------------------|
| docs/atm_lifecycle_v1_2026_05_26/V4_0_RECURRING_BACKTEST_LLM_COVERAGE_IMPLEMENTATION_REPORT.md | Just implemented today | None - source of truth | Lose implementation record | KEEP - just built |
| docs/atm_lifecycle_v1_2026_05_26/backtest_llm_coverage_v4_0_design/ (12 files) | Design completed, implemented | Impl report exists | Design still needed for v4.1 filter fixes | KEEP until v4.1 stable |

## v4.1 Pre-Apply Backup

| Path | Reason May Be Obsolete | Replacement File | Risk if Deleted | Recommended Action |
|------|----------------------|-----------------|----------------|-------------------|
| docs/atm_lifecycle_v1_2026_05_28/backups/backtesting_filters_v4_1_pre_apply_20260528_095513/Backtesting.tsx | v4.1 being applied | Current Backtesting.tsx | Lose rollback capability for v4.1 filters | KEEP until v4.1 verified stable |

## Source Exports

| Path | Reason May Be Obsolete | Replacement File | Risk if Deleted | Recommended Action |
|------|----------------------|-----------------|----------------|-------------------|
| docs/atm_lifecycle_v1_2026_05_26/source_exports/ (200+ files) | Snapshots of code at specific points | Live source code | Lose point-in-time reference for backtesting script design | KEEP until project closeout |

## Screenshots

| Path | Reason May Be Obsolete | Replacement File | Risk if Deleted | Recommended Action |
|------|----------------------|-----------------|----------------|-------------------|
| docs/atm_lifecycle_v1_2026_05_26/screenshots/ (34 files, ~16.5 MB) | Point-in-time visual evidence | None - unique captures | Lose visual proof of UI state at each version | KEEP until project closeout |

## Reference Architecture Backups

| Path | Reason May Be Obsolete | Replacement File | Risk if Deleted | Recommended Action |
|------|----------------------|-----------------|----------------|-------------------|
| docs/project/Trade_AI_v12_Reference_Architecture.docx.bak_session29 | Old backup | Current .docx | Lose ability to diff against session 29 state | Archive after v4.1 stable |
| docs/project/Trade_AI_v12_Reference_Architecture.docx.bak_session30 | Old backup | Current .docx | Lose ability to diff against session 30 state | Archive after v4.1 stable |
| docs/project/Trade_AI_v12_Reference_Architecture.docx.bak_session30b | Old backup | Current .docx | Same as above | Archive after v4.1 stable |
| docs/project/Trade_AI_v12_Reference_Architecture.docx.bak_session30c | Old backup | Current .docx | Same as above | Archive after v4.1 stable |
| docs/project/Trade_AI_v12_Reference_Architecture.docx.bak_session30d | Old backup | Current .docx | Same as above | Archive after v4.1 stable |
| docs/project/Trade_AI_v12_Reference_Architecture.docx.bak_session34 | Old backup | Current .docx | Same as above | Archive after v4.1 stable |
| docs/project/Trade_AI_v12_Reference_Architecture.docx.bak_session37 | Old backup | Current .docx | Same as above | Archive after v4.1 stable |
| docs/project/Trade_AI_v12_Reference_Architecture.docx.bak_atm_supply_20260522_1051 | Old backup | Current .docx | Same as above | Archive after v4.1 stable |

---

## Summary

- **Total protected files:** ~400+
- **Primary reasons for protection:** Active work (v3.8/v3.9/v4.0), repair evidence (BLMN/APPS), rollback capability (backups), visual evidence (screenshots), source reference (exports)
- **Earliest safe cleanup date:** After v4.1 backtesting filters verified stable AND v3.8/v3.9 LLM pipeline producing valid close_analysis rows
