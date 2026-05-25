#!/usr/bin/env bash
set -euo pipefail
cd /home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild
mkdir -p logs
MODE="${1:-light}"
.venv/bin/python scripts/refresh_agent_context.py --mode "$MODE" --json >> "logs/agent_context_${MODE}.log" 2>&1 || true
