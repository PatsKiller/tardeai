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
#   3. Regenerates the integrity manifest via generate_integrity_manifest.py
#   4. Updates the CURRENT symlink to the new release
#   5. Updates the systemd drop-in (20-exact-sha-release.conf)
#   6. Reloads systemd and restarts the portfolio-server service
#   7. Waits for the health endpoint to respond OK
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
    echo "[DRY RUN] Would regenerate integrity manifest"
    echo "[DRY RUN] Would update CURRENT symlink"
    echo "[DRY RUN] Would update systemd drop-in"
    echo "[DRY RUN] Would restart $SERVICE_NAME"
    exit 0
fi

# --- Step 1: Create release directory ---
echo "[1/6] Creating release directory..."
mkdir -p "$RELEASE_DIR"

# --- Step 2: Rsync canonical source ---
echo "[2/6] Copying canonical source to release..."
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

# --- Step 3: Regenerate integrity manifest ---
echo "[3/6] Regenerating integrity manifest..."
cd "$RELEASE_DIR"
if "$VENV_PYTHON" scripts/generate_integrity_manifest.py 2>&1; then
    echo "  Manifest regenerated."
else
    echo "  WARNING: Integrity manifest generation had issues (continuing)"
fi

# --- Step 4: Update CURRENT symlink ---
echo "[4/6] Updating CURRENT symlink..."
ln -sfn "$RELEASE_DIR" "${RELEASES_BASE}/CURRENT"
echo "  CURRENT -> $RELEASE_DIR"

# --- Step 5: Update systemd drop-in ---
echo "[5/6] Updating systemd drop-in..."
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

# --- Step 6: Reload systemd and restart service ---
echo "[6/6] Reloading systemd and restarting service..."
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
