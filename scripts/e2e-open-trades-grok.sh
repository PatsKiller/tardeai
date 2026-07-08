#!/usr/bin/env bash
# Run from any directory. Requires portfolio-server :7777 + Grok OAuth ready.
#   scripts/e2e-open-trades-grok.sh
#   CC_SYMBOL=ANET scripts/e2e-open-trades-grok.sh
set -euo pipefail
SCRIPT="$(readlink -f "${BASH_SOURCE[0]}")"
ROOT="$(cd "$(dirname "$SCRIPT")/.." && pwd)"
cd "$ROOT"
exec node tests/e2e/open-trades-grok.mjs "$@"