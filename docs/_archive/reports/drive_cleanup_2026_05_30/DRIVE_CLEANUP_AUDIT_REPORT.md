# Drive Cleanup Audit Report — 2026-05-30

## Status: PHASE 7 OPERATOR CHECKPOINT

This report summarizes the audit findings. **No files have been moved or deleted.**

## Inventory

| Metric | Count |
|--------|-------|
| Total items scanned | 5909 |
| Total files | 5250 |
| Total folders | 659 |
| Loose root files | 104 |
| TGZ archives | 34 |
| ZIP archives | 1 |

## Duplicates

| Metric | Count |
|--------|-------|
| Duplicate file name groups | 1207 |
| Same-parent true duplicates | 574 |
| Duplicate folder name groups | 178 |
| Root cause | Two `docs/` folders under canonical root |

## Classification

| Action | Count |
|--------|-------|
| KEEP_CURRENT | 5146 |
| MOVE_TO_ARTIFACTS | 16 |
| MOVE_TO_ARCHIVE | 66 |
| MOVE_TO_REVIEW | 22 |
| Requires operator approval | 104 |
| Delete candidates | 0 |

## Key Findings

1. **Two `docs/` folders**: The canonical root has TWO folders named `docs`. Folder A (4,480 files) is actively synced. Folder B (331 files) is stale — all 7 subfolders overlap with A. This is the primary source of 1,200+ duplicate file names.

2. **104 loose root files**: 13 TGZ handoff packages, 6 backup parts, ~30 duplicate MDs, and misc files sit at the Drive root level instead of in organized subfolders.

3. **34 TGZ archives**: Scattered across root and subfolders. Includes 2 duplicate Playwright archives, 3 duplicate UI redesign packages.

4. **No separate duplicate root folder**: The `trade-ai-docs-v2` mentioned in ChatGPT review was not found as a separate root — the visual duplication comes from the two `docs/` subfolders.

## Proposed Actions

| Action | Count | Status |
|--------|-------|--------|
| Archive stale docs folder | 331 files | PENDING APPROVAL |
| Move root TGZ to artifacts | 16 | PENDING APPROVAL |
| Archive root MDs | 66 | PENDING APPROVAL |
| Move to review | 22 | PENDING APPROVAL |
| Actual moves | 0 | ZERO |
| Actual deletes | 0 | ZERO |

## Highest-Risk Files

1. `Trade_AI_v12_Reference_Architecture.docx` (root) — verify repo copy exists
2. `trade_ai_backup_20260524_part_*` (6 parts) — verify backup data exists elsewhere
3. `.env.example` (root) — verify repo copy

## Recommended Next Steps

1. **Approve Phase 1**: Move stale `docs/` folder to archive (biggest impact, lowest risk)
2. **Approve Phase 2**: Move root TGZ packages to organized artifact folder
3. **Approve Phase 3**: Archive root duplicate MDs
4. **Approve Phase 4**: Move unclassified to review
5. **Fix sync script**: Change `gog drive ls` default max from 20 to 1000
6. **Observe**: Let archive sit for a few days before considering deletes

## Safety Confirmation

- Hermes installed: NO
- Hermes executed: NO
- Code changes: NO
- DB writes: NO
- Orders placed: NO
- Broker writes: NO
- Proposal mutations: NO
- paper_trades mutations: NO
- Journal mutations: NO
- Cron changes: NO
- .env changes: NO
- Model routing changes: NO
- LLM calls: NO
- Actual Drive moves: **ZERO**
- Actual Drive deletes: **ZERO**

## Report Files

| File | Purpose |
|------|---------|
| `docs/drive_cleanup_2026_05_30/DRIVE_ROOTS_AUDIT.md` | Root folder analysis |
| `docs/drive_cleanup_2026_05_30/DRIVE_INVENTORY_SUMMARY.md` | Inventory summary |
| `docs/drive_cleanup_2026_05_30/TARGET_DRIVE_STRUCTURE.md` | Proposed folder structure |
| `docs/drive_cleanup_2026_05_30/CLASSIFICATION_RULES.md` | Classification rules |
| `docs/drive_cleanup_2026_05_30/DUPLICATE_ANALYSIS.md` | Duplicate analysis |
| `docs/drive_cleanup_2026_05_30/DRY_RUN_MOVE_PLAN.md` | Dry-run move plan |
| `logs/drive_cleanup_2026_05_30/drive_inventory_full.json` | Full inventory (JSON) |
| `logs/drive_cleanup_2026_05_30/drive_inventory_full.csv` | Full inventory (CSV) |
| `logs/drive_cleanup_2026_05_30/drive_cleanup_manifest.csv` | Classification manifest |
| `logs/drive_cleanup_2026_05_30/duplicate_candidates.csv` | Duplicate candidates |
