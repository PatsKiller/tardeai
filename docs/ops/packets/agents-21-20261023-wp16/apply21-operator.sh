#!/usr/bin/env bash
# OPERATOR ONLY. Default is preview; --apply creates a distinct operator worktree.
set -euo pipefail
PKG_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
exec python3 "$PKG_DIR/operator21.py" apply "$@"
