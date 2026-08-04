#!/bin/bash
"""make_release.sh — Create a SHA-pinned release directory for portfolio_server.

    Usage:  bash scripts/make_release.sh [--label "optional-label"]

    Creates a timestamped release at:
        ~/trade-ai-releases/portfolio-server/<short-sha>-<label>-<YYYYMMDD>-<HHMMSS>/

    Copies the full working tree (including gitignored build artifacts like
    apps/command-center-v3/dist/) while excluding heavy dirs the server doesn't
    need at runtime (.git, .venv, node_modules, __pycache__, .pytest_cache).

    The release is a self-contained directory that can be pointed to by the
    portfolio-server systemd drop-in.

    NOTE: git-archive is NOT suitable for releases — it skips gitignored files
    (dist/, data/state/) that the server requires at runtime. The /v3/ route
    broke on 2026-08-03 when a git-archive release was deployed without dist/.
"""
set -euo pipefail

LABEL="${1:-release}"
if [ "$1" = "--label" ] && [ -n "${2:-}" ]; then
    LABEL="$2"
fi

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJ="$(cd "$SCRIPT_DIR/.." && pwd)"
SHA=$(git -C "$PROJ" rev-parse --short HEAD)
TIMESTAMP=$(date +%Y%m%d-%H%M%S)
RELEASE_NAME="${SHA}-${LABEL}-${TIMESTAMP}"
RELEASE_DIR="${HOME}/trade-ai-releases/portfolio-server/${RELEASE_NAME}"

echo "=== Creating release: ${RELEASE_NAME} ==="
echo "Source: ${PROJ}"
echo "Target: ${RELEASE_DIR}"
echo "SHA:    $(git -C "$PROJ" rev-parse HEAD)"

mkdir -p "$RELEASE_DIR"

# Copy everything except heavy/vcs dirs
rsync -a --delete \
    --exclude='.git' \
    --exclude='.venv' \
    --exclude='venv' \
    --exclude='node_modules' \
    --exclude='__pycache__' \
    --exclude='.pytest_cache' \
    --exclude='.mypy_cache' \
    --exclude='.ruff_cache' \
    --exclude='*.pyc' \
    --exclude='*.pyo' \
    --exclude='dist.old-*' \
    "$PROJ/" "$RELEASE_DIR/"

# Create empty dirs the server expects at runtime
mkdir -p "$RELEASE_DIR/logs"
mkdir -p "$RELEASE_DIR/data/portfolios/state"
mkdir -p "$RELEASE_DIR/state"

echo ""
echo "=== Release created ==="
echo "Files: $(find "$RELEASE_DIR" -type f | wc -l)"
echo "Size:  $(du -sh "$RELEASE_DIR" | cut -f1)"
echo ""
echo "=== Critical paths ==="
for p in "apps/command-center-v3/dist/index.html" "scripts/portfolio_server.py" "scripts/api_v2.py" ".env"; do
    if [ -f "$RELEASE_DIR/$p" ]; then
        echo "  ✅ $p"
    else
        echo "  ❌ MISSING: $p"
    fi
done

echo ""
echo "=== To activate: ==="
echo "  Update ~/.config/systemd/user/portfolio-server.service.d/20-exact-sha-release.conf"
echo "  WorkingDirectory=${RELEASE_DIR}"
echo "  Environment=PYTHONPATH=${RELEASE_DIR}/scripts"
echo "  ExecStart=<venv-python> ${RELEASE_DIR}/scripts/portfolio_server.py"
echo ""
echo "  systemctl --user daemon-reload"
echo "  systemctl --user restart portfolio-server.service"

echo ""
echo "Done: ${RELEASE_NAME}"
