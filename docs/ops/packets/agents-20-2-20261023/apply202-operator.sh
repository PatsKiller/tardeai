#!/usr/bin/env bash
# OPERATOR ONLY. Default is preview; --apply prompts, edits a fresh worktree and publishes the proposal.
set -euo pipefail
P="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
exec python3 "$P/package_operator.py" apply "$@"
