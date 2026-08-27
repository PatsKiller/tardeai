# Dry-Run Move Plan — 2026-05-30

## Summary

| Action | File Count |
|--------|-----------|
| KEEP_CURRENT | 5146 |
| MOVE_TO_ARTIFACTS | 16 |
| MOVE_TO_ARCHIVE | 66 |
| MOVE_TO_REVIEW | 22 |
| **Total** | **5250** |

## Phase 1: Consolidate Duplicate `docs/` Folder

**This is the highest-impact single action.**

Move all 331 files + 57 subfolders from stale `docs/` folder (ID: `1VGZYWRIcw6iLomXOnv3S7hkHT3Xbg-uK`) to `40_ARCHIVE/duplicate_docs_folder/`.

- Risk: LOW — all content verified to exist in canonical docs folder
- Eliminates majority of 1,207 duplicate name groups
- Requires: create `40_ARCHIVE/duplicate_docs_folder/` on Drive, move items

## Phase 2: Move Loose Root TGZ to Artifacts (16)

- `final_docs_update_20260529.tgz` → `20_ARTIFACT_PACKAGES/final_docs_update_20260529.tgz`
- `session_final_update_20260529.tgz` → `20_ARTIFACT_PACKAGES/session_final_update_20260529.tgz`
- `playwright_journal_backtest_20260529_1506.tgz` → `20_ARTIFACT_PACKAGES/playwright_journal_backtest_20260529_1506.tgz`
- `playwright_journal_backtest_20260529_1506.tgz` → `20_ARTIFACT_PACKAGES/playwright_journal_backtest_20260529_1506.tgz`
- `prompts_1_2_3_2026_05_29.tgz` → `20_ARTIFACT_PACKAGES/prompts_1_2_3_2026_05_29.tgz`
- `playwright_journal_backtest_20260529_1421.tgz` → `20_ARTIFACT_PACKAGES/playwright_journal_backtest_20260529_1421.tgz`
- `session_2026_05_29_final.tgz` → `20_ARTIFACT_PACKAGES/session_2026_05_29_final.tgz`
- `p1_phase_b_2026_05_29.tgz` → `20_ARTIFACT_PACKAGES/p1_phase_b_2026_05_29.tgz`
- `p1_phase_a_2026_05_29.tgz` → `20_ARTIFACT_PACKAGES/p1_phase_a_2026_05_29.tgz`
- `shfs_860_apply_2026_05_29.tgz` → `20_ARTIFACT_PACKAGES/shfs_860_apply_2026_05_29.tgz`
- `shfs_860_dry_run_2026_05_29.tgz` → `20_ARTIFACT_PACKAGES/shfs_860_dry_run_2026_05_29.tgz`
- `p0_proposal_fixes_2026_05_29.tgz` → `20_ARTIFACT_PACKAGES/p0_proposal_fixes_2026_05_29.tgz`
- `proposal_backtest_enhancements_2026_05_29.tgz` → `20_ARTIFACT_PACKAGES/proposal_backtest_enhancements_2026_05_29.tgz`
- `audit_7777_20260524_1923.tgz` → `20_ARTIFACT_PACKAGES/audit_7777_20260524_1923.tgz`
- `audit_7776_20260524_1225.tgz` → `20_ARTIFACT_PACKAGES/audit_7776_20260524_1225.tgz`
- `trade_ai_docs_active_20260524_post_cleanup.tgz` → `20_ARTIFACT_PACKAGES/trade_ai_docs_active_20260524_post_cleanup.tgz`

## Phase 3: Archive Loose Root Files (66)

- `ROOT_CAUSE_ATM_DEAD_2026_05_26.md` → `40_ARCHIVE/loose_root_files/ROOT_CAUSE_ATM_DEAD_2026_05_26.md` (Loose root markdown, likely duplicate of indexed doc)
- `CURRENT_PROJECT_CONTEXT.md` → `40_ARCHIVE/loose_root_files/CURRENT_PROJECT_CONTEXT.md` (Loose root markdown, likely duplicate of indexed doc)
- `ROOT_CAUSE_ATM_DEAD_2026_05_26.md` → `40_ARCHIVE/loose_root_files/ROOT_CAUSE_ATM_DEAD_2026_05_26.md` (Loose root markdown, likely duplicate of indexed doc)
- `AGENT_ROSTER.md` → `40_ARCHIVE/loose_root_files/AGENT_ROSTER.md` (Loose root markdown, likely duplicate of indexed doc)
- `MONDAY_BURNIN_CHECKLIST.md` → `40_ARCHIVE/loose_root_files/MONDAY_BURNIN_CHECKLIST.md` (Loose root markdown, likely duplicate of indexed doc)
- `DOCS_ROSTER.md` → `40_ARCHIVE/loose_root_files/DOCS_ROSTER.md` (Loose root markdown, likely duplicate of indexed doc)
- `PROJECT_DOC_INDEX.md` → `40_ARCHIVE/loose_root_files/PROJECT_DOC_INDEX.md` (Loose root markdown, likely duplicate of indexed doc)
- `TRADE_SUPERVISION_METHODOLOGY.md` → `40_ARCHIVE/loose_root_files/TRADE_SUPERVISION_METHODOLOGY.md` (Loose root markdown, likely duplicate of indexed doc)
- `SYSTEM_ARCHITECTURE_COMPLETE.md` → `40_ARCHIVE/loose_root_files/SYSTEM_ARCHITECTURE_COMPLETE.md` (Loose root markdown, likely duplicate of indexed doc)
- `ROOT_CAUSE_ATM_DEAD_2026_05_26.md` → `40_ARCHIVE/loose_root_files/ROOT_CAUSE_ATM_DEAD_2026_05_26.md` (Loose root markdown, likely duplicate of indexed doc)
- `trade_ai_backup_20260524_part_af` → `40_ARCHIVE/old_backups/trade_ai_backup_20260524_part_af` (Split backup archive parts at root)
- `trade_ai_backup_20260524_part_ae` → `40_ARCHIVE/old_backups/trade_ai_backup_20260524_part_ae` (Split backup archive parts at root)
- `trade_ai_backup_20260524_part_ad` → `40_ARCHIVE/old_backups/trade_ai_backup_20260524_part_ad` (Split backup archive parts at root)
- `trade_ai_backup_20260524_part_ac` → `40_ARCHIVE/old_backups/trade_ai_backup_20260524_part_ac` (Split backup archive parts at root)
- `trade_ai_backup_20260524_part_ab` → `40_ARCHIVE/old_backups/trade_ai_backup_20260524_part_ab` (Split backup archive parts at root)
- `trade_ai_backup_20260524_part_aa` → `40_ARCHIVE/old_backups/trade_ai_backup_20260524_part_aa` (Split backup archive parts at root)
- `DATA_PRODUCT_FRESHNESS_REGISTRY.md` → `40_ARCHIVE/loose_root_files/DATA_PRODUCT_FRESHNESS_REGISTRY.md` (Loose root markdown, likely duplicate of indexed doc)
- `BACKUP_RETENTION_POLICY.md` → `40_ARCHIVE/loose_root_files/BACKUP_RETENTION_POLICY.md` (Loose root markdown, likely duplicate of indexed doc)
- `DRIVE_INVENTORY_SUMMARY.md` → `40_ARCHIVE/loose_root_files/DRIVE_INVENTORY_SUMMARY.md` (Loose root markdown, likely duplicate of indexed doc)
- `brave_search_api_usage_audit_2026-05.md` → `40_ARCHIVE/loose_root_files/brave_search_api_usage_audit_2026-05.md` (Loose root markdown, likely duplicate of indexed doc)
- `DATA_PRODUCT_FRESHNESS_REGISTRY.md` → `40_ARCHIVE/loose_root_files/DATA_PRODUCT_FRESHNESS_REGISTRY.md` (Loose root markdown, likely duplicate of indexed doc)
- `FIX_SUMMARY.md` → `40_ARCHIVE/loose_root_files/FIX_SUMMARY.md` (Loose root markdown, likely duplicate of indexed doc)
- `ROOT_CAUSE_MATRIX.md` → `40_ARCHIVE/loose_root_files/ROOT_CAUSE_MATRIX.md` (Loose root markdown, likely duplicate of indexed doc)
- `FIX_SUMMARY.md` → `40_ARCHIVE/loose_root_files/FIX_SUMMARY.md` (Loose root markdown, likely duplicate of indexed doc)
- `ROOT_CAUSE_MATRIX.md` → `40_ARCHIVE/loose_root_files/ROOT_CAUSE_MATRIX.md` (Loose root markdown, likely duplicate of indexed doc)
- `monday_morning_state_20260525.md` → `40_ARCHIVE/loose_root_files/monday_morning_state_20260525.md` (Loose root markdown, likely duplicate of indexed doc)
- `triggered_stops_2026-05-24_pre_schwab_check.md` → `40_ARCHIVE/loose_root_files/triggered_stops_2026-05-24_pre_schwab_check.md` (Loose root markdown, likely duplicate of indexed doc)
- `sunday_audit_fixes_2026-05-25.md` → `40_ARCHIVE/loose_root_files/sunday_audit_fixes_2026-05-25.md` (Loose root markdown, likely duplicate of indexed doc)
- `pre_burnin_findings_2026-05-25.md` → `40_ARCHIVE/loose_root_files/pre_burnin_findings_2026-05-25.md` (Loose root markdown, likely duplicate of indexed doc)
- `MONDAY_BURNIN_CHECKLIST.md` → `40_ARCHIVE/loose_root_files/MONDAY_BURNIN_CHECKLIST.md` (Loose root markdown, likely duplicate of indexed doc)
- ... +36 more

## Phase 4: Move to Review (22)

- `Trade_AI_v12_Reference_Architecture.docx` → `90_REVIEW_BEFORE_DELETE/root_files/Trade_AI_v12_Reference_Architecture.docx` (Loose root file, needs manual review)
- `.env.example` → `90_REVIEW_BEFORE_DELETE/root_files/.env.example` (Loose root file, needs manual review)
- `persistent_tickers.txt` → `90_REVIEW_BEFORE_DELETE/root_files/persistent_tickers.txt` (Unclassified loose root file)
- `scan_to_proposal_lag.txt` → `90_REVIEW_BEFORE_DELETE/root_files/scan_to_proposal_lag.txt` (Unclassified loose root file)
- `validate_v7_cio_intelligence.py` → `90_REVIEW_BEFORE_DELETE/root_files/validate_v7_cio_intelligence.py` (Unclassified loose root file)
- `marl_training_simulation.py` → `90_REVIEW_BEFORE_DELETE/root_files/marl_training_simulation.py` (Unclassified loose root file)
- `strategy_rotation_engine.py` → `90_REVIEW_BEFORE_DELETE/root_files/strategy_rotation_engine.py` (Unclassified loose root file)
- `format.ts` → `90_REVIEW_BEFORE_DELETE/root_files/format.ts` (Unclassified loose root file)
- `chat_context.json` → `90_REVIEW_BEFORE_DELETE/root_files/chat_context.json` (Unclassified loose root file)
- `theme.css` → `90_REVIEW_BEFORE_DELETE/root_files/theme.css` (Unclassified loose root file)
- `useFetch.ts` → `90_REVIEW_BEFORE_DELETE/root_files/useFetch.ts` (Unclassified loose root file)
- `DoughnutChart.tsx` → `90_REVIEW_BEFORE_DELETE/root_files/DoughnutChart.tsx` (Unclassified loose root file)
- `PeriodReturnBars.tsx` → `90_REVIEW_BEFORE_DELETE/root_files/PeriodReturnBars.tsx` (Unclassified loose root file)
- `DataGrid.tsx` → `90_REVIEW_BEFORE_DELETE/root_files/DataGrid.tsx` (Unclassified loose root file)
- `news_source_clients.py` → `90_REVIEW_BEFORE_DELETE/root_files/news_source_clients.py` (Unclassified loose root file)
- `build_marl_training_dataset.py` → `90_REVIEW_BEFORE_DELETE/root_files/build_marl_training_dataset.py` (Unclassified loose root file)
- `research_insight_extractor.py` → `90_REVIEW_BEFORE_DELETE/root_files/research_insight_extractor.py` (Unclassified loose root file)
- `youtube_research_ingestion.py` → `90_REVIEW_BEFORE_DELETE/root_files/youtube_research_ingestion.py` (Unclassified loose root file)
- `confidence_calibration.py` → `90_REVIEW_BEFORE_DELETE/root_files/confidence_calibration.py` (Unclassified loose root file)
- `sync_output.txt` → `90_REVIEW_BEFORE_DELETE/root_files/sync_output.txt` (Unclassified loose root file)
- `orchestration_chevrons.mmd` → `90_REVIEW_BEFORE_DELETE/root_files/orchestration_chevrons.mmd` (Unclassified loose root file)
- `trades_baseline.txt` → `90_REVIEW_BEFORE_DELETE/root_files/trades_baseline.txt` (Unclassified loose root file)

## Operator Approval Checklist

- [ ] Review stale `docs/` folder contents — confirm all exist in canonical
- [ ] Review loose root .md files — confirm indexed copy exists
- [ ] Review .tgz packages — confirm latest kept, older archived
- [ ] Review backup parts — confirm no unique data
- [ ] Approve Phase 1 (duplicate docs consolidation)
- [ ] Approve Phase 2 (TGZ move)
- [ ] Approve Phase 3 (archive)
- [ ] Approve Phase 4 (review folder)

## Risky Moves

| File | Risk | Reason |
|------|------|--------|
| `Trade_AI_v12_Reference_Architecture.docx` | MEDIUM | May be only-in-Drive copy. Verify repo has current version. |
| `trade_ai_backup_20260524_part_*` (6 parts) | MEDIUM | Split backup. Verify DB backup exists elsewhere before archiving. |
| `.env.example` | LOW | Should be in repo. Verify. |

## Actual Deletes This Phase

**ZERO.** All actions are moves only. Delete candidates will be identified after archive review.
