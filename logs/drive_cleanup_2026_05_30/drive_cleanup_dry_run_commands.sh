#!/bin/bash
# DRY-RUN ONLY — prints intended actions, does not execute
# Run with: bash drive_cleanup_dry_run_commands.sh
# To execute: uncomment the actual gog commands

set -euo pipefail

GOG_ACCOUNT="john@jwwhiting.com"
CANONICAL_ROOT="1Zxc20B5Xo24RGZ1Pow1-uW6ldASQJHiR"
STALE_DOCS_FOLDER="1VGZYWRIcw6iLomXOnv3S7hkHT3Xbg-uK"

echo "=== DRY RUN: Drive Cleanup Plan ==="
echo ""
echo "Phase 1: Create target folders"
echo "  CREATE: 20_ARTIFACT_PACKAGES/ under $CANONICAL_ROOT"
echo "  CREATE: 20_ARTIFACT_PACKAGES/session_packages/"
echo "  CREATE: 20_ARTIFACT_PACKAGES/playwright_archives/"
echo "  CREATE: 20_ARTIFACT_PACKAGES/backup_archives/"
echo "  CREATE: 40_ARCHIVE/ under $CANONICAL_ROOT"
echo "  CREATE: 40_ARCHIVE/duplicate_docs_folder/"
echo "  CREATE: 40_ARCHIVE/loose_root_files/"
echo "  CREATE: 40_ARCHIVE/superseded_packages/"
echo "  CREATE: 90_REVIEW_BEFORE_DELETE/ under $CANONICAL_ROOT"
echo "  CREATE: 90_REVIEW_BEFORE_DELETE/root_files/"
echo ""

echo "Phase 2: Move stale docs/ folder (331 files, 57 subfolders)"
echo "  MOVE: $STALE_DOCS_FOLDER → 40_ARCHIVE/duplicate_docs_folder/"
echo ""

echo "Phase 3: Move loose root TGZ packages (16 files)"
for tgz_id in \
  1ltTVpOwRPB5UQxA_13YEe6cVBdK27_SQ \
  1uQY6PvT3cvDPGcHf9CzvAu2qryhbrCjj \
  1HqVz_elKG5RXh4OyvSSEki-0x5Kf0ttp \
  1rGumb6WFvvfCFppqzIw20xICzLFJWbvw \
  1FstAp7k2EzNDES7Si1mXeVovRs2rzM23 \
  1QZecaFEbtf1iaSJlqcHIgFHshnjHdEU9 \
  1AOJbkei8usJmihOwlS02j4Nn7CPHDd6b \
  1m3HePQbEaqSU_YY1t9qu3Ae6pvvi2Drc \
  1jKA9Dauuv8AGu3L1Y4w5OGQRtIml9y2s \
  1TGBnIgwKFpjXAjOMoJCedv4R9SwfsRCM \
  1_wl8p0dmJ6QVhhZjvIqDNimigkVFXEzf \
  1NEM-gcccx7HR_GtT0qjH5yrPbtU4tOpQ; do
  echo "  MOVE: $tgz_id → 20_ARTIFACT_PACKAGES/session_packages/"
done
echo ""

echo "Phase 4: Archive loose root MDs and misc (66 files)"
echo "  [See drive_cleanup_manifest.csv for full list]"
echo ""

echo "Phase 5: Move to review (22 files)"
echo "  [See drive_cleanup_manifest.csv for full list]"
echo ""

echo "=== TOTALS ==="
echo "  Files to keep: 5,146"
echo "  Files to move to artifacts: 16"
echo "  Files to archive: 66"
echo "  Files to review: 22"
echo "  Files to delete: 0"
echo "  Stale docs folder items to archive: 331 files + 57 folders"
echo ""
echo "=== NO ACTUAL CHANGES MADE ==="
