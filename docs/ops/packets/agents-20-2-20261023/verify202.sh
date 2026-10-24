#!/usr/bin/env bash
# Unique isolated exports under ~/.cache/rtc; fake ratification stays fixture-only; nothing is deleted.
set -euo pipefail
P="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
exec python3 "$P/verify202.py" "$@"
