#!/usr/bin/env bash
# Governed launcher wrapper for the hermetic CC runtime harness.
# Never defaults to production URLs.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

MODE="${1:-hermetic}"
OUT_DIR="${CC_RUNTIME_OUT_DIR:-${ROOT}/evidence/cc_runtime/last_run}"

export PYTHONPATH="${ROOT}${PYTHONPATH:+:${PYTHONPATH}}"

case "${MODE}" in
  hermetic)
    exec python3 -m scripts.cc_runtime_harness --mode hermetic --output-dir "${OUT_DIR}" --json
    ;;
  candidate-preview)
    if [[ -z "${CC_RUNTIME_PREVIEW_BASE_URL:-}" ]]; then
      echo "CC_RUNTIME_PREVIEW_BASE_URL is required for candidate-preview" >&2
      exit 2
    fi
    exec python3 -m scripts.cc_runtime_harness --mode candidate-preview --output-dir "${OUT_DIR}" --json
    ;;
  *)
    echo "usage: $0 [hermetic|candidate-preview]" >&2
    exit 2
    ;;
esac
