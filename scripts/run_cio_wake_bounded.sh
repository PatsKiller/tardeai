#!/usr/bin/env bash
# run_cio_wake_bounded.sh: operator entry point for the bounded CIO persistent wake (LQ-20261107-2965).
#
#   bash scripts/run_cio_wake_bounded.sh                 # DRY: admission + exact argv; spawns and writes nothing
#   bash scripts/run_cio_wake_bounded.sh --apply         # one bounded wake; receipt with exit code + memory.peak
#
# All logic (flock -n single flight, cron/in-flight admission fence, systemd-run --user --scope with
# MemoryMax=2G MemorySwapMax=0 OOMPolicy=kill CPUWeight=20 IOWeight=20, nice/ionice, timeout --kill-after,
# cgroup memory.peak receipt) lives in scripts/run_cio_wake_bounded.py so the n8n lane runs the same code
# ($PY scripts/*.py is the only command shape config/n8n_run_allowlist.json admits).
set -euo pipefail
cd "$(dirname "$0")/.."
exec "${TRADEAI_VENV_PYTHON:-${PY:-python3}}" scripts/run_cio_wake_bounded.py "$@"
