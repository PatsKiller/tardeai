# Drive Roots Audit — 2026-05-30

## Canonical Root

| Field | Value |
|-------|-------|
| Folder name | `Trade_AI_Docs_v2` |
| Folder ID | `1Zxc20B5Xo24RGZ1Pow1-uW6ldASQJHiR` |
| Total files | 5250 |
| Total folders | 659 |
| Status | **Canonical** — used by sync script, in folder cache |
| Recommendation | KEEP — this is the production Drive root |

## Duplicate Root

No separate duplicate root folder (`trade-ai-docs-v2`) found in Drive root. The user's ChatGPT review may have been observing the TWO `docs` subfolders within the canonical root, which visually appear as duplicates.

## Duplicate `docs` Subfolder

| Field | Value |
|-------|-------|
| Canonical docs folder | ID: `1Rb6qcu_D45ehZ0EKwEqwbzkEg9zKlBcA` |
| Canonical docs files | 4,480 files, 584 subfolders |
| Canonical docs status | In sync cache, actively managed |
| Stale docs folder | ID: `1VGZYWRIcw6iLomXOnv3S7hkHT3Xbg-uK` |
| Stale docs files | 331 files, 57 subfolders |
| Stale docs subfolders | archive, design, diagrams, llm_fleet, maturity_hardening, phase_b1_baseline, sync_drift_2026-05-16 |
| Overlap | All 7 stale subfolders exist in canonical |
| Recommendation | **MOVE stale docs folder contents to `40_ARCHIVE/duplicate_docs_folder/`** then delete empty folder after verification |

## Root Cause

The sync script (`scripts/sync-docs-to-drive.sh`) uses `gog drive ls --max=20` (default). During early syncs before the folder cache was populated, the script likely created a second `docs` folder when the first wasn't returned in the default 20-item page. The folder cache now locks to folder A, so no new files go to folder B.
