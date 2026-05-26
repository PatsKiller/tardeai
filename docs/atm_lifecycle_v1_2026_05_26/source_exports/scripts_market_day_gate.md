# Source Export: scripts/market_day_gate.sh

| Field | Value |
|-------|-------|
| **Original Path** | `scripts/market_day_gate.sh` |
| **Git Branch** | `main` |
| **Git Commit** | `915876f` |
| **Export Timestamp** | `2026-05-26T19:48:00Z` |
| **SHA256** | `2d77ad422195667f5ac36e695b7f017b62027a5a077391c4c4b7953e644e71cf` |
| **File Size** | 622 bytes |

## Full Source

```sh
#!/usr/bin/env bash
# market_day_gate.sh — skip execution on weekends and US market holidays.
# Usage in cron:
#   */15 9-16 * * 1-5 cd $PROJ && bash scripts/market_day_gate.sh $PY scripts/some_script.py --flags >> logs/some.log 2>&1
#
# If today is a holiday or weekend, exits 0 silently.
# Otherwise exec's the remaining arguments.
set -euo pipefail
cd "$(dirname "$0")/.."

if .venv/bin/python -c "
import sys; sys.path.insert(0,'scripts')
from market_session import is_trading_day
sys.exit(0 if is_trading_day() else 1)
" 2>/dev/null; then
    exec "$@"
else
    # Holiday or weekend — skip silently
    exit 0
fi
```
