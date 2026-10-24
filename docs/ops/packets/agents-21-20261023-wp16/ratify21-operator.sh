#!/usr/bin/env bash
# OPERATOR ONLY. Reads the real PR's exact operator token; never invents approval.
set -euo pipefail
PKG_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
exec python3 "$PKG_DIR/operator21.py" ratify "$@"
