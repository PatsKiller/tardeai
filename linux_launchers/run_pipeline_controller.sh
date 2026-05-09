#!/bin/bash
# Pipeline Controller launcher
# Usage: ./linux_launchers/run_pipeline_controller.sh [args]
# Example: ./linux_launchers/run_pipeline_controller.sh --pipeline daily --run-label morning --allow-degraded

PROJ="/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild"
cd "$PROJ" || exit 1
source .venv/bin/activate 2>/dev/null
exec .venv/bin/python scripts/pipeline_controller.py "$@"
