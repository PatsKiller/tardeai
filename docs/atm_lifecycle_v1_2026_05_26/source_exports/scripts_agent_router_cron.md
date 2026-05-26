# Source Export: scripts/agent_router_cron.sh

| Field | Value |
|-------|-------|
| **Original Path** | `scripts/agent_router_cron.sh` |
| **Git Branch** | `main` |
| **Git Commit** | `915876f` |
| **Export Timestamp** | `2026-05-26T19:48:00Z` |
| **SHA256** | `f979c6a5491503a01911c34bab821db16b47dce987e4fe55151aac1313f6ee54` |
| **File Size** | 252 bytes |

## Full Source

```sh
#!/usr/bin/env bash
set -euo pipefail
cd /home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild
mkdir -p logs
MODE="${1:-light}"
.venv/bin/python scripts/refresh_agent_context.py --mode "$MODE" --json >> "logs/agent_context_${MODE}.log" 2>&1 || true
```
