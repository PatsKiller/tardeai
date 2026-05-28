# Archive Candidates - 2026-05-28

Files that should be moved to an archive folder. These are superseded designs, old prompts, and duplicates where implementation reports exist confirming the work was completed.

**Recommended archive location:** `docs/_archived/` or `docs/atm_lifecycle_v1_2026_05_26/_archived/`

---

## ARCHIVE_SUPERSEDED_DESIGN -- Design docs with existing implementation reports

### designed_replacements/ (13 files) -- All Applied

These were ChatGPT-designed replacement templates that Claude Code applied during v1 implementation.

| File | Superseded By |
|------|--------------|
| docs/atm_lifecycle_v1_2026_05_26/designed_replacements/ATMControlRoom.tsx.REPLACEMENT.md | ATM_LIFECYCLE_V1_IMPLEMENTATION_REPORT.md |
| docs/atm_lifecycle_v1_2026_05_26/designed_replacements/AutomatedTradeMode.tsx.REPLACEMENT.md | ATM_LIFECYCLE_V1_IMPLEMENTATION_REPORT.md |
| docs/atm_lifecycle_v1_2026_05_26/designed_replacements/CLAUDE_APPLY_ATM_LIFECYCLE_V1_TEMPLATE.md | ATM_LIFECYCLE_V1_IMPLEMENTATION_REPORT.md |
| docs/atm_lifecycle_v1_2026_05_26/designed_replacements/ExecutionQuality.tsx.REPLACEMENT.md | ATM_LIFECYCLE_V1_IMPLEMENTATION_REPORT.md |
| docs/atm_lifecycle_v1_2026_05_26/designed_replacements/PaperProposals.tsx.REPLACEMENT.md | ATM_LIFECYCLE_V1_IMPLEMENTATION_REPORT.md |
| docs/atm_lifecycle_v1_2026_05_26/designed_replacements/SystemHealth.tsx.REPLACEMENT.md | ATM_LIFECYCLE_V1_IMPLEMENTATION_REPORT.md |
| docs/atm_lifecycle_v1_2026_05_26/designed_replacements/alert_governance_patch.md | Multiple implementation reports |
| docs/atm_lifecycle_v1_2026_05_26/designed_replacements/api_v2_lifecycle_patch.md | Multiple implementation reports |
| docs/atm_lifecycle_v1_2026_05_26/designed_replacements/backtesting_feedback_patch.md | Multiple implementation reports |
| docs/atm_lifecycle_v1_2026_05_26/designed_replacements/lifecycle_event_writer.py.REPLACEMENT.md | Multiple implementation reports |
| docs/atm_lifecycle_v1_2026_05_26/designed_replacements/lifecycle_traceability_schema_patch.md | Multiple implementation reports |
| docs/atm_lifecycle_v1_2026_05_26/designed_replacements/slippage_tca_patch.md | TCA_STOP_PROOF_V3_3_V3_4_IMPLEMENTATION_REPORT.md |
| docs/atm_lifecycle_v1_2026_05_26/designed_replacements/stop_management_policy_patch.md | STOP_TRAILING_TIMESTOP_V3_5_IMPLEMENTATION_REPORT.md |

### full_lifecycle_acceleration_v3_0/ -- Design docs only (7 files)

v3.0 design was superseded by v3.1/v3.2 implementation.

| File | Superseded By |
|------|--------------|
| FULL_LIFECYCLE_ACCELERATION_SUMMARY.md | FULL_LIFECYCLE_V3_1_V3_2_TRACEABILITY_REPORT.md |
| FULL_LIFECYCLE_DATA_FLOW.md | Implementation in api_v2.py |
| FULL_LIFECYCLE_GAP_REGISTER.md | Gaps addressed in v3.1+ |
| FULL_LIFECYCLE_HANDOFF_MANIFEST.md | Applied - handoff complete |
| FULL_LIFECYCLE_IMPLEMENTATION_BACKLOG.md | Backlog items implemented |
| FULL_LIFECYCLE_ROUTE_MAP.md | Routes implemented |
| FULL_LIFECYCLE_SOURCE_OF_TRUTH_MATRIX.md | Updated in live system |

**Note:** The api_payloads/, screenshots/, and schema_exports/ within v3.0 are KEEP_EVIDENCE (not archive).

### stop_trailing_timestop_v3_5_design/ -- Design docs only (9 files)

v3.5 implemented, report exists: STOP_TRAILING_TIMESTOP_V3_5_IMPLEMENTATION_REPORT.md

| File | Status |
|------|--------|
| HANDOFF_MANIFEST.md | Applied |
| STOP_CHANGE_AUDIT_TRAIL_DESIGN.md | Implemented |
| STOP_CHANGE_AUDIT_UI_DESIGN.md | Implemented |
| STOP_TRAILING_API_DESIGN.md | Implemented |
| STOP_TRAILING_SOURCE_OF_TRUTH.md | Implemented |
| STOP_TRAILING_TIMESTOP_V3_5_IMPLEMENTATION_PLAN.md | Implemented |
| STOP_TRAILING_UI_DESIGN.md | Implemented |
| STOP_TRAILING_VALIDATION_AND_ROLLBACK.md | Validated |
| TIME_STOP_REVIEW_WORKFLOW_DESIGN.md | Implemented |

**Note:** row_exports/APPS_REPAIR_ROW.txt is DO_NOT_DELETE.

### journal_learning_backtesting_v3_6_design/ -- Design docs only (8 files)

v3.6 implemented, report exists: JOURNAL_LEARNING_BACKTESTING_V3_6_IMPLEMENTATION_REPORT.md

| File | Status |
|------|--------|
| BACKTEST_INTEGRATION_GAP_ANALYSIS.md | Gaps addressed |
| HANDOFF_MANIFEST.md | Applied |
| JOURNAL_BACKTEST_SOURCE_OF_TRUTH.md | Implemented |
| JOURNAL_LEARNING_API_DESIGN.md | Implemented |
| JOURNAL_LEARNING_BACKTESTING_V3_6_IMPLEMENTATION_PLAN.md | Implemented |
| JOURNAL_LEARNING_UI_DESIGN.md | Implemented |
| JOURNAL_LEARNING_VALIDATION_AND_ROLLBACK.md | Validated |
| PAPER_VS_BACKTEST_COMPARISON_DESIGN.md | Implemented |

### unified_trade_inspector_v3_7_design/ -- Design docs only (8 files)

v3.7 implemented, report exists: UNIFIED_TRADE_INSPECTOR_V3_7_IMPLEMENTATION_REPORT.md

| File | Status |
|------|--------|
| DATA_QUALITY_AND_IDENTITY_RESOLUTION.md | Implemented |
| HANDOFF_MANIFEST.md | Applied |
| INSPECTOR_INTEGRATION_PLAN.md | Implemented |
| UNIFIED_TRADE_INSPECTOR_API_DESIGN.md | Implemented |
| UNIFIED_TRADE_INSPECTOR_SOURCE_OF_TRUTH.md | Implemented |
| UNIFIED_TRADE_INSPECTOR_UI_DESIGN.md | Implemented |
| UNIFIED_TRADE_INSPECTOR_V3_7_IMPLEMENTATION_PLAN.md | Implemented |
| UNIFIED_TRADE_INSPECTOR_VALIDATION_AND_ROLLBACK.md | Validated |

### tca_stop_proof_implementation_v3_3_v3_4/ (9 files)

v3.3/v3.4 implemented, report exists: TCA_STOP_PROOF_V3_3_V3_4_IMPLEMENTATION_REPORT.md

| File | Status |
|------|--------|
| API_DESIGN_V3_3_V3_4.md | Implemented |
| ExecutionTimingPanel.tsx.DESIGN.md | Implemented |
| ORDER_TIMING_CAPTURE_PATCH.md | Applied |
| PAPER_TRADES_SCHEMA_PATCH.sql | Applied |
| STOP_ORDER_PROOF_PATCH.md | Applied |
| STOP_PROOF_RECONCILER_PATCH.md | Applied |
| StopProofPanel.tsx.DESIGN.md | Implemented |
| TCA_STOP_PROOF_IMPLEMENTATION_PLAN.md | Implemented |
| VALIDATION_AND_ROLLBACK_V3_3_V3_4.md | Validated |

### execution_stop_proof_v3_3_v3_4_export/ -- Design docs only (3 files)

| File | Status |
|------|--------|
| HANDOFF_MANIFEST.md | Applied |
| ORDER_LIFECYCLE_SOURCE_OF_TRUTH.md | Implemented |
| V3_3_V3_4_IMPLEMENTATION_OPTIONS.md | Implemented (option selected) |

---

## ARCHIVE_OLD_PROMPT -- Applied context sync prompts

### docs/project/context_sync_2026_05_22/ (5 files)

These were context synchronization prompts created for the 2026-05-22 session. All were applied.

| File | Status |
|------|--------|
| NEXT_PHASE_ATM_SAFE_1_PROMPT.md | Applied |
| context_sync_2026_05_22_timeline.md | Applied |
| context_sync_doc_inventory.md | Applied |
| context_sync_maturity_reclassification.md | Applied |
| context_sync_preflight.md | Applied |
| context_sync_validation.md | Applied |

---

## Archive Summary

| Category | File Count | Estimated Size |
|----------|-----------|---------------|
| designed_replacements/ | 13 | ~9 KB |
| full_lifecycle_acceleration_v3_0/ design .md files | 7 | ~13 KB |
| stop_trailing_timestop_v3_5_design/ design .md files | 9 | ~7 KB |
| journal_learning_backtesting_v3_6_design/ design .md files | 8 | ~6 KB |
| unified_trade_inspector_v3_7_design/ design .md files | 8 | ~8 KB |
| tca_stop_proof_implementation_v3_3_v3_4/ | 9 | ~6 KB |
| execution_stop_proof_v3_3_v3_4_export/ design .md files | 3 | ~3 KB |
| context_sync_2026_05_22/ | 5 | ~14 KB |
| **Total archivable** | **~62 files** | **~66 KB** |

**Important:** Only the .md design/plan/handoff files in these directories should be archived. The api_payloads/, screenshots/, row_exports/, source_exports/, and schema_exports/ subdirectories within them should remain as KEEP_EVIDENCE.
