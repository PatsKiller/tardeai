#!/bin/bash
# ============================================================
#  Portfolio Intelligence Dashboard (Linux)
#  Manual run only - not scheduled
#  Opens: http://localhost:7777/portfolio_live.html
# ============================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

cd "$PROJECT_ROOT" || exit 1
source venv/bin/activate

echo ""
echo "Starting Portfolio Intelligence Dashboard..."
echo ""
echo "  File server:  http://localhost:7777/portfolio_live.html"
echo "  API proxy:    http://localhost:7778  (enables AI buttons)"
echo ""
echo "Press Ctrl+C to stop both servers when done."
echo ""

# Start API proxy in background
python3 scripts/portfolio_proxy.py --root . &
PROXY_PID=$!

# Give proxy a moment to start
sleep 1

# Try to open browser (works on desktop Linux with xdg-open)
if command -v xdg-open &>/dev/null; then
    xdg-open "http://localhost:7777/portfolio_live.html" &>/dev/null &
fi

# Start file server (foreground - Ctrl+C stops everything)
python3 scripts/portfolio_server.py

# Cleanup proxy on exit
kill $PROXY_PID 2>/dev/null
