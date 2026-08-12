#!/usr/bin/env bash
#
# deploy_portfolio_server.sh — Deploy the Portfolio Server from canonical source
# to a new timestamped release directory and restart the systemd service.
#
# Usage:
#   bash scripts/deploy_portfolio_server.sh          # Deploy current source
#   bash scripts/deploy_portfolio_server.sh --dry-run  # Show what would happen
#
# The script:
#   1. Creates a timestamped release under trade-ai-releases/portfolio-server/
#   2. Rsyncs the canonical source (excluding .venv, .git, logs, __pycache__)
#   3. Symlinks pipeline-writable data back to canonical source (NEVER stale copies)
#   4. Regenerates the integrity manifest via generate_integrity_manifest.py
#   5. Updates the CURRENT symlink to the new release
#   6. Updates the systemd drop-in (20-exact-sha-release.conf)
#   7. Reloads systemd and restarts the portfolio-server service
#   8. Waits for the health endpoint to respond OK
#

set -euo pipefail

CANONICAL_SOURCE="/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild"
RELEASES_BASE="/home/johnclaw/trade-ai-releases/portfolio-server"
VENV_PYTHON="${CANONICAL_SOURCE}/.venv/bin/python"
SYSTEMD_DROPIN="/home/johnclaw/.config/systemd/user/portfolio-server.service.d/20-exact-sha-release.conf"
SERVICE_NAME="portfolio-server.service"
HEALTH_URL="http://localhost:7777/api/v2/health"

DRY_RUN=false
if [[ "${1:-}" == "--dry-run" ]]; then
    DRY_RUN=true
    echo "[DRY RUN] No changes will be made."
fi

# --- Validate prerequisites ---
if [[ ! -d "$CANONICAL_SOURCE" ]]; then
    echo "ERROR: Canonical source not found at $CANONICAL_SOURCE"
    exit 1
fi

if [[ ! -f "${CANONICAL_SOURCE}/scripts/portfolio_server.py" ]]; then
    echo "ERROR: portfolio_server.py not found in canonical source"
    exit 1
fi

if [[ ! -x "$VENV_PYTHON" ]]; then
    echo "ERROR: Python venv not found at $VENV_PYTHON"
    exit 1
fi

# --- Get git info from canonical source ---
cd "$CANONICAL_SOURCE"
GIT_SHA=$(git rev-parse HEAD 2>/dev/null || echo "unknown")
GIT_SHA_SHORT=$(git rev-parse --short HEAD 2>/dev/null || echo "unknown")
GIT_BRANCH=$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo "unknown")
TIMESTAMP=$(date +%Y%m%d-%H%M%S)
RELEASE_NAME="${TIMESTAMP}"
RELEASE_DIR="${RELEASES_BASE}/${RELEASE_NAME}"

echo "=== Trade AI Portfolio Server Deploy ==="
echo "  Canonical source: $CANONICAL_SOURCE"
echo "  Git SHA:          $GIT_SHA ($GIT_BRANCH)"
echo "  New release:      $RELEASE_DIR"
echo "  Timestamp:        $TIMESTAMP"
echo ""

if $DRY_RUN; then
    echo "[DRY RUN] Would create release at $RELEASE_DIR"
    echo "[DRY RUN] Would rsync canonical source -> $RELEASE_DIR"
    echo "[DRY RUN] Would symlink pipeline data to canonical source"
    echo "[DRY RUN] Would regenerate integrity manifest"
    echo "[DRY RUN] Would update CURRENT symlink"
    echo "[DRY RUN] Would update systemd drop-in"
    echo "[DRY RUN] Would restart $SERVICE_NAME"
    exit 0
fi

# --- Step 1: Create release directory ---
echo "[1/8] Creating release directory..."
mkdir -p "$RELEASE_DIR"

# --- Step 2: Rsync canonical source ---
echo "[2/8] Copying canonical source to release..."
rsync -a --info=progress2 \
    --exclude='.venv' \
    --exclude='.git' \
    --exclude='logs/' \
    --exclude='__pycache__/' \
    --exclude='*.pyc' \
    --exclude='backups/' \
    --exclude='.openclaw' \
    "${CANONICAL_SOURCE}/" \
    "${RELEASE_DIR}/"
echo "  Rsync complete."

# --- Step 3: Symlink pipeline-writable data back to canonical source ---
# The data pipeline (repricer, moomoo sync, portfolio_loader, orchestrator, etc.)
# writes to the CANONICAL source tree, never to the release. If the release keeps
# its own stale copy, the header tiles show days-old values even though the
# pipeline is producing fresh data.
#
# RULE: NEVER deploy pipeline-writable dirs as stale rsync copies.
# These directories are always symlinked to the canonical source so the server
# reads the live pipeline output on every request (not the release snapshot).
#
# - data/portfolios/state  — holdings, finviz quote cache (header tiles)
# - state/data_broker      — broker projection cache
# - data/runtime           — advisory desk, defense, calibration, shadow (1.5G live)
# - data/health            — health agent findings / history
echo "[3/8] Linking pipeline data to canonical source..."
DATA_DIRS_TO_LINK=(
    "data/portfolios/state"
    "state/data_broker"
    "data/runtime"
    "data/health"
)
for rel in "${DATA_DIRS_TO_LINK[@]}"; do
    target="${RELEASE_DIR}/${rel}"
    source="${CANONICAL_SOURCE}/${rel}"
    if [ -d "$target" ] || [ -f "$target" ]; then
        rm -rf "$target"
        ln -s "$source" "$target"
        echo "  [symlink] ${rel} → canonical"
    else
        echo "  [warn] ${rel} not found in release — skipping"
    fi
done

# Verify symlinks are valid
for rel in "${DATA_DIRS_TO_LINK[@]}"; do
    if [ ! -e "${RELEASE_DIR}/${rel}" ]; then
        echo "  ERROR: symlink ${rel} is broken!"
        exit 1
    fi
done
echo "  Data symlinks verified."

# --- Step 4: Regenerate integrity manifest ---
echo "[4/8] Regenerating integrity manifest..."
cd "$RELEASE_DIR"
if "$VENV_PYTHON" scripts/generate_integrity_manifest.py 2>&1; then
    echo "  Manifest regenerated."
else
    echo "  WARNING: Integrity manifest generation had issues (continuing)"
fi

# --- Step 4b: Refresh release manifest (never re-serve a stale FAIL) ---
# docs/project/RELEASE_MANIFEST_LATEST.md carries a Status line the health agent
# mirrors. It is regenerated in the canonical tree by validate_release_readiness.py
# as part of pre-deploy diligence; if that step is skipped the release would carry a
# stale FAIL forever. Copy the canonical (fresh) copy over the rsync snapshot.
echo "[4b/8] Refreshing release manifest..."
if [ -f "${CANONICAL_SOURCE}/docs/project/RELEASE_MANIFEST_LATEST.md" ]; then
    mkdir -p "${RELEASE_DIR}/docs/project"
    cp -f "${CANONICAL_SOURCE}/docs/project/RELEASE_MANIFEST_LATEST.md" \
        "${RELEASE_DIR}/docs/project/RELEASE_MANIFEST_LATEST.md"
    echo "  Copied canonical release manifest (Status: $(grep -m1 '^Status:' "${RELEASE_DIR}/docs/project/RELEASE_MANIFEST_LATEST.md" | cut -d' ' -f2))."
else
    echo "  WARNING: canonical release manifest missing — release will carry the rsync snapshot."
fi

# --- Step 5: Update CURRENT symlink ---
echo "[5/8] Updating CURRENT symlink..."
ln -sfn "$RELEASE_DIR" "${RELEASES_BASE}/CURRENT"
echo "  CURRENT -> $RELEASE_DIR"

# --- Step 6: Update systemd drop-in ---
echo "[6/8] Updating systemd drop-in..."
mkdir -p "$(dirname "$SYSTEMD_DROPIN")"
cat > "$SYSTEMD_DROPIN" << DROPIN
[Service]
WorkingDirectory=${RELEASE_DIR}
Environment=PYTHONPATH=${RELEASE_DIR}/scripts
Environment=LLM_GLOBAL_DAILY_USD_CAP=0.25
Environment=TRADEAI_CC_DEPLOYED_SHA=${GIT_SHA}
Environment=TRADEAI_CC_SOURCE_PR=296
Environment=TRADEAI_WATCH_DEFAULT_WORKSPACE=intelligence
ExecStart=
ExecStart=${VENV_PYTHON} ${RELEASE_DIR}/scripts/portfolio_server.py
DROPIN
echo "  Drop-in written."

# --- Step 7: Reload systemd and restart service ---
echo "[7/8] Reloading systemd and restarting service..."
systemctl --user daemon-reload
systemctl --user restart "$SERVICE_NAME"
echo "  Service restarted."

# --- Wait for startup ---
echo ""
echo "Waiting for server to start..."
for i in $(seq 1 15); do
    sleep 2
    if curl -s "$HEALTH_URL" 2>/dev/null | python3 -c "import sys,json; d=json.load(sys.stdin); sys.exit(0 if d.get('ok') else 1)" 2>/dev/null; then
        echo "  Health check OK after $((i*2))s"
        break
    fi
    echo "  ... waiting ($((i*2))s)"
done

# --- Final status ---
echo ""
echo "=== Deployment Complete ==="
systemctl --user status "$SERVICE_NAME" --no-pager -l 2>&1 | head -10
echo ""
echo "New release: $RELEASE_DIR"
echo "Git SHA:     $GIT_SHA"
echo "CURRENT:     $(readlink -f ${RELEASES_BASE}/CURRENT)"
