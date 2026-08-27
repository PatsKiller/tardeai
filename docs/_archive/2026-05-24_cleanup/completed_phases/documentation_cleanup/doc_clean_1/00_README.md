# DOC-CLEAN-1 — MS01 Source Documentation Cleanup

**Status:** ALL STAGES COMPLETE. 1→inventory, 1B→archive (401), 1C→duplicates (7).

## Summary

767 local docs inventoried:
- **Active keep:** 10 canonical docs
- **Current phase keep:** 113 (Phase 6/7/8/9A/BR-1 etc.)
- **Archive candidates:** 490 (superseded, legacy, backups)
- **Artifacts:** 34 (code/sync files in docs)
- **Review required:** 118
- **Duplicate groups:** 7

## Process

1. **Stage 1 (DONE):** Inventory + classify + dry-run report
2. **Stage 2 (PENDING):** Operator approves → local archive/delete
3. **Stage 3 (AFTER Stage 2):** Drive sync removes obsolete mirrored files

## Rules

- MS01 is source of truth, Drive is mirror
- Clean local first, then sync to Drive
- Never delete canonical active docs
- Archive superseded versions, don't hard-delete
- Only delete byte-identical duplicates after approval
