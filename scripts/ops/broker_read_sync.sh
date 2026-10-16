#!/usr/bin/env bash
# broker_read_sync.sh — READ-ONLY portfolio sync from every broker (AGENTS.md 14.0.0 §24.11, PROPOSED).
# Repo form of the operator-run ~/n8n-maturity-verification/sync_all_readonly.sh (operator, 2026-10-16:
# "make that bash so agents can run ... not trading just reading").
#
#   scripts/ops/broker_read_sync.sh --plan     preflight + plan; contacts no broker, needs no grant
#   scripts/ops/broker_read_sync.sh            dry run of every step (still a live broker READ; needs the grant)
#   scripts/ops/broker_read_sync.sh --apply    real sync into our own stores (needs the grant)
#
# The step list is closed (scripts/lib/broker_read_sync_policy.py STEPS). This wrapper passes through at most
# ONE of --plan / --apply and nothing else; every refusal is in scripts/ops/broker_read_sync.py.
# It never opens .env: each step's own shell sources it (see the Python entrypoint).
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
case "$#:${1:-}" in
  0:) ;;
  1:--plan|1:--apply) ;;
  *) echo "usage: broker_read_sync.sh [--plan | --apply]   (closed allowlist; no other arguments)" >&2; exit 64;;
esac
PY="$HOME/trade-ai-v12-rebuild/trade-ai-v12-rebuild/.venv/bin/python"
[[ -x "$PY" ]] || PY="$(command -v python3)"
unset PYTHONPATH PYTHONSTARTUP PYTHONHOME PYTHONINSPECT BASH_ENV ENV
exec "$PY" "$HERE/broker_read_sync.py" "$@"
