# Source Export: scripts/agent_intelligence_cron.sh

| Field | Value |
|-------|-------|
| **Original Path** | `scripts/agent_intelligence_cron.sh` |
| **Git Branch** | `main` |
| **Git Commit** | `915876f` |
| **Export Timestamp** | `2026-05-26T19:48:00Z` |
| **SHA256** | `0eb59c3f780fd17b47176ce8e82b2a58c37a17973b90f1b459272a08a5d6f543` |
| **File Size** | 773 bytes |

## Full Source

```sh
#!/usr/bin/env bash
set -euo pipefail
PROJECT_DIR="${PROJECT_DIR:-/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild}"
MODE="${1:-daily}"
cd "$PROJECT_DIR"
mkdir -p logs
LOG="logs/agent_intelligence_${MODE}_$(date +%Y%m%d_%H%M%S).log"
{
  echo "[agent-intel-cron] mode=$MODE started=$(date -Is)"
  .venv/bin/python scripts/asset_intelligence_pipeline.py --json || true
  .venv/bin/python scripts/proactive_discovery.py --json || true
  .venv/bin/python scripts/watchlist_review.py --json || true
  if [ "$MODE" = "deep" ]; then
    .venv/bin/python scripts/refresh_agent_context.py --mode deep --json || true
  else
    .venv/bin/python scripts/refresh_agent_context.py --mode audit --json || true
  fi
  echo "[agent-intel-cron] finished=$(date -Is)"
} | tee "$LOG"
```
