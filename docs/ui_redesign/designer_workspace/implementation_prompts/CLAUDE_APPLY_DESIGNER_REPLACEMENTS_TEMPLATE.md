# Claude Code — Apply Designer Replacement Files

Status:      HISTORICAL
as_of:       2026-05-25T11:54:23-04:00
Measured at: efcc51365 / not measured

## Context
The designer has provided complete replacement TSX/CSS files in:
`docs/ui_redesign/designer_workspace/designed_replacements/`

Each `.REPLACEMENT.md` file contains:
- Target repo path
- Original SHA256 (to verify source hasn't changed)
- Replacement code in a fenced code block

## Steps

1. **Verify source unchanged**
   For each replacement file, compare the Original SHA256 against the current file.
   If mismatched, STOP and report — source was modified since export.

2. **Back up originals**
   ```
   cp {target_file} docs/ui_redesign/designer_workspace/backups/{Component}.tsx.bak.$(date +%Y%m%d_%H%M)
   ```

3. **Extract and apply**
   Extract the code from inside the fenced ```tsx block in each .REPLACEMENT.md.
   Write it to the target repo path.

4. **Build**
   ```
   cd apps/command-center-v2 && npm run build
   ```
   Must succeed with 0 errors.

5. **Screenshot**
   Run `scripts/capture_screenshots.py` for affected routes.
   Compare before/after.

6. **Commit**
   ```
   git add {changed files}
   git commit -m "UI redesign: apply designer replacements for {components}"
   ```

7. **Sync report to Drive**
   Upload before/after screenshots and build results.

8. **Rollback if needed**
   ```
   cp docs/ui_redesign/designer_workspace/backups/{Component}.tsx.bak.{timestamp} {target_path}
   cd apps/command-center-v2 && npm run build
   ```

## Safety Rules
- Do NOT modify backend/API code
- Do NOT change endpoint paths
- Do NOT add trading/approval mutations
- Verify build passes before committing
- Keep backups for every file replaced
