# Drive Inventory Summary — 2026-05-30

## Counts

| Metric | Count |
|--------|-------|
| Total items | 5909 |
| Total files | 5250 |
| Total folders | 659 |
| Canonical root files | 5250 |
| Canonical root folders | 659 |
| Loose root files | 104 |
| TGZ archives | 34 |
| ZIP archives | 1 |
| Duplicate file name groups | 1207 |
| Duplicate folder name groups | 178 |

## Duplicate `docs` Folder

The canonical root contains **two** `docs` folders:
- **Folder A** (canonical): 4,480 files, 584 subfolders — actively synced
- **Folder B** (stale): 331 files, 57 subfolders — all 7 subfolders overlap with A

This is the primary source of the 1,207 duplicate file name groups.

## Loose Root Files (104)

104 files sit directly in `Trade_AI_Docs_v2/` root instead of inside subfolders:
- 13 TGZ handoff packages (session drops from ChatGPT)
- 6 split backup parts (`trade_ai_backup_20260524_part_*`)
- ~30 markdown docs (duplicates of indexed docs)
- Misc: .docx, .example, .csv, .html

## TGZ Archives (34)

34 total .tgz files across the tree:
- 13 at root level (session handoff packages)
- 7 in `docs/atm_lifecycle_v1_2026_05_26/backups/`
- 4 in `docs/` level (handoff packages synced from repo)
- 3 in `docs/playwright/` (Playwright crawl archives)
- 2 duplicate `playwright_journal_backtest_20260529_1506.tgz`
- Other nested backups

## Largest Files

| File | Size |
|------|------|
| `trade_ai_backup_20260524_part_ae` | 500.0MB |
| `trade_ai_backup_20260524_part_ad` | 500.0MB |
| `trade_ai_backup_20260524_part_ac` | 500.0MB |
| `trade_ai_backup_20260524_part_ab` | 500.0MB |
| `trade_ai_backup_20260524_part_aa` | 500.0MB |
| `trade_ai_backup_20260524_part_af` | 416.9MB |
| `audit_7777_20260524_1923.tgz` | 17.9MB |
| `audit_7777_20260524_1923.tgz` | 17.9MB |
| `strategy_fit_data_gaps_results.json` | 7.8MB |
| `ui_redesign_trade_ai_command_center_full_20260525.tgz` | 7.6MB |

## Full Inventory

- JSON: `logs/drive_cleanup_2026_05_30/drive_inventory_full.json`
- CSV: `logs/drive_cleanup_2026_05_30/drive_inventory_full.csv`
