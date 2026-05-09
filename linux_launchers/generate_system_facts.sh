#!/bin/bash
# Generate system facts manifest
PROJ="/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild"
cd "$PROJ" || exit 1
source .venv/bin/activate 2>/dev/null
exec .venv/bin/python scripts/generate_system_facts.py
