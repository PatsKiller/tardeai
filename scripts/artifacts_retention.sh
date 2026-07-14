#!/bin/bash
# Ephemeral run-artifact retention (Playwright captures etc.) — see docs/runbooks/PLAYWRIGHT_ARTIFACTS_POLICY.md
# Deletes artifacts/<tool>/<run_id>/ directories older than ARTIFACTS_RETENTION_DAYS (default 7).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DAYS="${ARTIFACTS_RETENTION_DAYS:-7}"
DIR="$ROOT/artifacts"

[ -d "$DIR" ] || exit 0
# run dirs are two levels down: artifacts/<tool>/<run_id>
find "$DIR" -mindepth 2 -maxdepth 2 -type d -mtime "+$DAYS" -print -exec rm -rf {} + 2>/dev/null || true
# prune now-empty tool dirs
find "$DIR" -mindepth 1 -maxdepth 1 -type d -empty -delete 2>/dev/null || true
