#!/usr/bin/env bash
set -euo pipefail
PKG_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
exec python3 "$PKG_DIR/package21.py" rebuild "$@"
