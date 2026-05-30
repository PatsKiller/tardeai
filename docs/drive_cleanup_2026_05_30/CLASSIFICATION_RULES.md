# Classification Rules — 2026-05-30

## Allowed Actions

| Action | Description |
|--------|-------------|
| `KEEP_CURRENT` | File stays where it is |
| `MOVE_TO_ARTIFACTS` | Move to `20_ARTIFACT_PACKAGES/` |
| `MOVE_TO_ARCHIVE` | Move to `40_ARCHIVE/` |
| `MOVE_TO_REVIEW` | Move to `90_REVIEW_BEFORE_DELETE/` |
| `DO_NOT_TOUCH` | Explicitly protected |

## Rules (in priority order)

1. **Indexed docs**: Any file referenced in `PROJECT_DOC_INDEX.md` → `KEEP_CURRENT`
2. **Hermes v4**: Files under `docs/hermes/` → `KEEP_CURRENT`
3. **Synced repo tree**: Files under canonical `docs/` or `config/` at depth > 0 → `KEEP_CURRENT`
4. **Archive content**: Files already in `_archive/` or `archive/` → `KEEP_CURRENT`
5. **Generated content**: Files in `_generated/` → `KEEP_CURRENT`
6. **Loose root TGZ**: `.tgz` files at root → `MOVE_TO_ARTIFACTS`
7. **Loose root MD**: `.md` files at root that duplicate indexed docs → `MOVE_TO_ARCHIVE`
8. **Backup parts**: Split backup files at root → `MOVE_TO_ARCHIVE`
9. **Superseded archives**: Older playwright `1421` superseded by `1506` → `MOVE_TO_ARCHIVE`
10. **Unknown root files**: Other files at root → `MOVE_TO_REVIEW`
11. **Never delete**: If no canonical replacement identified, do not mark as delete candidate

## Safety Rules

- Files only in Drive (not in repo) must go to REVIEW, never DELETE
- Canonical replacement must be verified before any DELETE_CANDIDATE marking
- All moves require operator approval
- Sync script managed files are never moved manually
