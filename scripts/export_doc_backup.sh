#!/usr/bin/env bash
# export_doc_backup.sh — package current documentation for sharing
#
# Output: timestamped zip with manifest and live system facts.
# Excludes: docs/_archive/, log files, node_modules, .git
#
# Usage:
#   bash scripts/export_doc_backup.sh
#   bash scripts/export_doc_backup.sh --output ~/Downloads

set -euo pipefail

PROJECT_ROOT="/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild"
cd "$PROJECT_ROOT"

OUTPUT_DIR="$PROJECT_ROOT/backups/doc_exports"
while [[ $# -gt 0 ]]; do
    case $1 in
        --output) OUTPUT_DIR="$2"; shift 2 ;;
        *) echo "Unknown arg: $1"; exit 1 ;;
    esac
done

mkdir -p "$OUTPUT_DIR"

# Holdings guard
python3 -c "
import json
d = json.load(open('data/portfolios/state/holdings.json'))
assert d['portfolio_totals']['total_value'] > 1_000_000
print(f'GUARD OK: \${d[\"portfolio_totals\"][\"total_value\"]:,.2f}')
"

TIMESTAMP=$(date +%Y%m%d_%H%M%S)
TEMP_DIR="/tmp/doc_export_${TIMESTAMP}"
ARCHIVE_NAME="trade_ai_docs_${TIMESTAMP}"
ARCHIVE_DIR="${TEMP_DIR}/${ARCHIVE_NAME}"
mkdir -p "$ARCHIVE_DIR"

echo "Copying docs/ (excluding _archive)..."
rsync -av --quiet \
    --exclude='_archive/' \
    --exclude='*.log' \
    --exclude='node_modules/' \
    --exclude='.git/' \
    --exclude='*.tmp' \
    --exclude='__pycache__/' \
    docs/ "$ARCHIVE_DIR/docs/"

# Live counts via targeted grep (not source .env)
DBPW=$(grep '^DB_PASSWORD=' .env | head -1 | cut -d= -f2)
TABLES=$(PGPASSWORD=$DBPW psql -h localhost -U trade_ai -d trade_ai -tAc \
  "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema='public';" 2>/dev/null || echo "?")
SCRIPTS=$(find scripts -name "*.py" -type f | wc -l)
CRONS=$(crontab -l 2>/dev/null | grep -v "^#" | grep -v "^$" | wc -l)
PAGES=$(find apps/command-center-v2/src/pages -name "*.tsx" 2>/dev/null | wc -l)
STRATEGIES=$(ls config/strategies/*.yaml 2>/dev/null | wc -l)
HOLDINGS=$(python3 -c "
import json
d = json.load(open('data/portfolios/state/holdings.json'))
print(f\"\${d['portfolio_totals']['total_value']:,.2f}\")")
GIT_COMMIT=$(git log --oneline -1)
GIT_BRANCH=$(git rev-parse --abbrev-ref HEAD)

cat > "$ARCHIVE_DIR/MANIFEST.txt" << MANIFEST_EOF
# Trade AI v12 — Documentation Backup Manifest

Generated:       $(date +"%Y-%m-%d %H:%M:%S %Z")
Source server:   ms01-openclaw
Git commit:      ${GIT_COMMIT}
Git branch:      ${GIT_BRANCH}

## System Snapshot (live introspection at export time)

| Metric              | Value           |
|---------------------|-----------------|
| Portfolio value     | ${HOLDINGS}     |
| PostgreSQL tables   | ${TABLES}       |
| Python scripts      | ${SCRIPTS}      |
| Active cron entries | ${CRONS}        |
| React pages         | ${PAGES}        |
| Strategy YAMLs      | ${STRATEGIES}   |

## Contents

This archive contains canonical documentation (excluding _archive/).
For complete history, use the git repository.

## File Inventory

MANIFEST_EOF

cd "$ARCHIVE_DIR"
find docs -type f | sort >> "$ARCHIVE_DIR/MANIFEST.txt"
cd "$PROJECT_ROOT"

echo "Creating zip..."
cd "$TEMP_DIR"
zip -r -q "${OUTPUT_DIR}/${ARCHIVE_NAME}.zip" "${ARCHIVE_NAME}/"
cd "$PROJECT_ROOT"
rm -rf "$TEMP_DIR"

ZIP_PATH="${OUTPUT_DIR}/${ARCHIVE_NAME}.zip"
ZIP_SIZE=$(du -h "$ZIP_PATH" | cut -f1)

echo ""
echo "==========================================================="
echo "Documentation backup created"
echo "==========================================================="
echo "Path:  $ZIP_PATH"
echo "Size:  $ZIP_SIZE"
echo ""
