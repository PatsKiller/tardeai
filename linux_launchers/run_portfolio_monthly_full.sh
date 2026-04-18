#!/usr/bin/env bash
set -euo pipefail
cd "/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild"
ENABLE_YAML_ADVISOR=1 bash linux_launchers/run_portfolio_monthly.sh
