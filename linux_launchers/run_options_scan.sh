#!/usr/bin/env bash
# Proposal scan owner only. Position monitoring retains its separate schedule.
set -euo pipefail
exec "${TRADEAI_PYTHON:-/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild/.venv/bin/python}" "$(dirname "$0")/../scripts/run_options_scan.py" --apply
