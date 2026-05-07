#!/bin/bash
# run_scalp_ws.sh — Start the scalp WebSocket server (port 7778/7779)
# Usage: ./run_scalp_ws.sh   (or via systemd)

cd /home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild

# Kill existing if running
pkill -f "scalp_ws_server.py" 2>/dev/null
sleep 1

# Start
nohup .venv/bin/python scripts/scalp_ws_server.py > logs/scalp_ws_server.log 2>&1 &
echo "Scalp WS server started (PID: $!)"
echo "  Clients: ws://0.0.0.0:7778"
echo "  Push:    ws://127.0.0.1:7779"
