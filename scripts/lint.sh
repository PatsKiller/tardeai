#!/usr/bin/env bash
# scripts/lint.sh — Run ruff linting on the project.
#
# Usage:
#   bash scripts/lint.sh              # Full lint (warnings only)
#   bash scripts/lint.sh --strict     # Block on F821 (undefined-name) — use in CI
#   bash scripts/lint.sh --fix        # Auto-fix safe issues
#
# Requires: ruff (installed in .venv)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
RUFF="$PROJECT_ROOT/.venv/bin/ruff"

if [ ! -x "$RUFF" ]; then
    echo "[lint] ruff not found at $RUFF — installing..."
    "$PROJECT_ROOT/.venv/bin/pip" install -q ruff
fi

MODE="${1:-}"

cd "$PROJECT_ROOT"

case "$MODE" in
    --strict)
        echo "[lint] CI mode — blocking on undefined-name (F821) and undefined-local (F823)"
        # F821: undefined-name — the `import re` class of bug
        # F823: undefined-local — variable used before assignment
        # F601: multi-value-repeated-key-literal — dict with duplicate keys
        "$RUFF" check --select F821,F823,F601 scripts/ || {
            echo ""
            echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
            echo "  ❌ LINT FAILED: undefined names found"
            echo "  These are runtime NameError bugs."
            echo "  Fix them before merging."
            echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
            exit 1
        }
        echo "[lint] ✅ No undefined-name or undefined-local errors"
        ;;
    --fix)
        echo "[lint] Auto-fixing safe issues..."
        "$RUFF" check --fix scripts/
        echo "[lint] Done"
        ;;
    *)
        echo "[lint] Advisory mode — reporting all F-rule issues"
        "$RUFF" check scripts/ || {
            echo ""
            echo "[lint] ⚠️  Issues found (advisory only — use --strict for CI gating)"
        }
        ;;
esac
