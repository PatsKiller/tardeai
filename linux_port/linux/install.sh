#!/bin/bash
# ============================================================
#  Trade AI v12 + Portfolio Intelligence - Linux Install Script
#  Tested on Ubuntu 22.04 / 24.04 (Debian-based)
#
#  Usage:
#    chmod +x linux/install.sh
#    ./linux/install.sh
#
#  What this does:
#    1. Installs system dependencies (Python 3.11+, Node.js 20+, pip)
#    2. Creates Python virtual environment
#    3. Installs all Python packages from requirements.txt
#    4. Installs Node.js docx package (for DOCX report generation)
#    5. Makes all launcher scripts executable
#    6. Creates required directories
#    7. Prints cron setup instructions
# ============================================================

set -e  # Exit on any error

# ── Config ────────────────────────────────────────────────────────────────────
INSTALL_DIR="${1:-$HOME/trade-ai}"   # Default: ~/trade-ai. Override: ./install.sh /opt/trade-ai
PYTHON_MIN="3.11"
NODE_MIN="20"

# ── Colors ───────────────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
ok()   { echo -e "${GREEN}  ✓${NC} $1"; }
warn() { echo -e "${YELLOW}  ⚠${NC} $1"; }
err()  { echo -e "${RED}  ✗${NC} $1"; exit 1; }
hdr()  { echo -e "\n${YELLOW}=== $1 ===${NC}"; }

echo ""
echo "============================================================"
echo "  Trade AI v12 + Portfolio Intelligence - Linux Installer"
echo "  Install path: $INSTALL_DIR"
echo "============================================================"
echo ""

# ── Step 1: System dependencies ──────────────────────────────────────────────
hdr "Step 1: System dependencies"

sudo apt-get update -qq

# Python
if command -v python3 &>/dev/null; then
    PYVER=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
    ok "Python $PYVER found"
else
    warn "Python3 not found — installing..."
    sudo apt-get install -y python3 python3-pip python3-venv python3-dev
    ok "Python3 installed"
fi

# pip
if ! command -v pip3 &>/dev/null; then
    sudo apt-get install -y python3-pip
fi
ok "pip3 available"

# venv
sudo apt-get install -y python3-venv -qq
ok "python3-venv available"

# Build tools (needed for some packages)
sudo apt-get install -y build-essential libssl-dev libffi-dev -qq
ok "Build tools available"

# Node.js (for portfolio_report.js DOCX generation)
if command -v node &>/dev/null; then
    NODEVER=$(node --version)
    ok "Node.js $NODEVER found"
else
    warn "Node.js not found — installing via NodeSource..."
    curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
    sudo apt-get install -y nodejs
    ok "Node.js $(node --version) installed"
fi

# ── Step 2: Project directory ─────────────────────────────────────────────────
hdr "Step 2: Project directory"

if [ ! -d "$INSTALL_DIR" ]; then
    warn "Directory $INSTALL_DIR does not exist."
    echo ""
    echo "  This script installs dependencies for an existing project."
    echo "  Copy your Trade AI project files to: $INSTALL_DIR"
    echo "  Then re-run this script."
    echo ""
    echo "  Example:"
    echo "    cp -r /path/to/trade-ai-v12-rebuild $INSTALL_DIR"
    echo "    ./linux/install.sh"
    exit 1
fi

cd "$INSTALL_DIR"
ok "Working in $INSTALL_DIR"

# ── Step 3: Python virtual environment ───────────────────────────────────────
hdr "Step 3: Python virtual environment"

if [ ! -d "venv" ]; then
    python3 -m venv venv
    ok "Virtual environment created at venv/"
else
    ok "Virtual environment already exists"
fi

source venv/bin/activate
ok "Virtual environment activated"

# ── Step 4: Python packages ───────────────────────────────────────────────────
hdr "Step 4: Python packages"

if [ ! -f "requirements.txt" ]; then
    err "requirements.txt not found in $INSTALL_DIR — cannot install packages"
fi

pip install --upgrade pip -q
pip install -r requirements.txt
ok "All Python packages installed"

# ── Step 5: Node.js packages ──────────────────────────────────────────────────
hdr "Step 5: Node.js packages"

npm install -g docx
ok "docx npm package installed"

# ── Step 6: Launcher permissions ─────────────────────────────────────────────
hdr "Step 6: Launcher permissions"

chmod +x launchers/*.sh 2>/dev/null && ok "launchers/*.sh — executable" || warn "No .sh files in launchers/ yet"
chmod +x linux/*.sh 2>/dev/null && ok "linux/*.sh — executable" || true

# ── Step 7: Required directories ─────────────────────────────────────────────
hdr "Step 7: Required directories"

for dir in logs reports data/portfolios/input data/portfolios/state data/portfolios/reports data/portfolios/charts data/portfolios/state/snapshots; do
    mkdir -p "$dir"
    ok "Created $dir"
done

# ── Step 8: Environment file ──────────────────────────────────────────────────
hdr "Step 8: Environment file"

if [ ! -f "assets/.env" ]; then
    if [ -f "assets/.env.template" ]; then
        cp assets/.env.template assets/.env
        warn "Created assets/.env from template — EDIT THIS FILE with your API keys before running"
    else
        warn "No assets/.env found and no template available — create assets/.env manually"
    fi
else
    ok "assets/.env already exists"
fi

# ── Step 9: Cron setup instructions ──────────────────────────────────────────
hdr "Step 9: Cron setup"

# Replace placeholder path in crontab.txt
CRON_FILE="linux/crontab.txt"
if [ -f "$CRON_FILE" ]; then
    sed "s|/home/YOUR_USER/trade-ai|$INSTALL_DIR|g" "$CRON_FILE" > /tmp/trade_ai_cron.txt
    echo ""
    echo "  Cron entries (preview):"
    echo "  ─────────────────────────────────────────────────────────"
    cat /tmp/trade_ai_cron.txt | grep -v "^#" | grep -v "^$"
    echo "  ─────────────────────────────────────────────────────────"
    echo ""
    echo "  To install cron jobs:"
    echo "    crontab -l > /tmp/existing_cron.txt 2>/dev/null"
    echo "    cat /tmp/trade_ai_cron.txt >> /tmp/existing_cron.txt"
    echo "    crontab /tmp/existing_cron.txt"
    echo ""
    echo "  Or edit manually: crontab -e"
fi

# ── Done ──────────────────────────────────────────────────────────────────────
echo ""
echo "============================================================"
echo -e "  ${GREEN}✓ Installation complete${NC}"
echo "  Install path:  $INSTALL_DIR"
echo "  Python:        $(python3 --version)"
echo "  Node.js:       $(node --version)"
echo ""
echo "  NEXT STEPS:"
echo "  1. Edit assets/.env — add all API keys"
echo "  2. Drop Schwab CSVs → data/portfolios/input/"
echo "  3. Run price cache: python3 scripts/portfolio_price_cache.py"
echo "  4. Test: python3 scripts/portfolio_orchestrator.py"
echo "  5. Install cron jobs (see above)"
echo "============================================================"
echo ""
