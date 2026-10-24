#!/usr/bin/env bash
# OPERATOR ONLY. Pass --pr N --sha FULL_SHA; default is preview; --apply requires the exact operator token and TTY.
set -euo pipefail
P="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
exec python3 "$P/package_operator.py" ratify "$@"
