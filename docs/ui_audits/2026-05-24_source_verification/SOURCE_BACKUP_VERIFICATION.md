# Source Backup Verification (2026-05-24)

Status:      HISTORICAL
as_of:       2026-05-24T10:35:08-04:00
Measured at: efcc51365 / not measured

## Backup File
- **Path:** docs/backups/trade_ai_backup_20260524.zip
- **Size:** 2.9GB (3,053.6 MB)
- **Integrity:** `unzip -t` passed — "No errors detected in compressed data"
- **File count:** 22,460 files
- **Extracted to:** /tmp/trade_ai_backup_20260524_inspect/

## Key Files Present in Backup
| File | Size | Status |
|------|------|--------|
| scripts/api_v2.py | 978,267 bytes | Present |
| scripts/check_data_product_freshness.py | 9,407 bytes | Present |
| scripts/check_command_center_data_consistency.py | 5,999 bytes | Present |
| apps/command-center-v2/src/components/ScalpLiveFeed.tsx | 7,751 bytes | Present |
| docs/ui_audits/2026-05-23_command_center_reliability_fix/ROOT_CAUSE_MATRIX.md | 2,893 bytes | Present |
| docs/ui_audits/2026-05-23_command_center_reliability_fix/FIX_SUMMARY.md | 3,590 bytes | Present |
| docs/ui_audits/2026-05-23_command_center_reliability_fix/DATA_PRODUCT_FRESHNESS_REGISTRY.md | 3,225 bytes | Present |

## Key Directories Present
- apps/command-center-v2/ — frontend source
- scripts/ — all automation scripts
- config/ — strategy YAML configs
- data/ — portfolio state files
- docs/ — all documentation including audit findings
- sql/ — database migrations
- openclaw/ — agent configs and gateway
- database/ — full PostgreSQL dump (trade_ai.sql.gz)

## Drive Upload Status
Backup split into 6 parts (500MB each + 413MB final) uploaded to Trade_AI_Docs_v2 folder.
Operator reports split parts not visible in Drive search. Parts were uploaded successfully per gog CLI output but may need folder-level browse to locate.
