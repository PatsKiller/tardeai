#!/usr/bin/env bash
# Starts the coordination gateway from the served release with --expected-sha = the release's own
# GIT_SHA, so an event stamped with another SHA is refused as stale_origin_sha after every promote.
# The HMAC key comes from the unit's EnvironmentFile (Bitwarden-managed), never from this script.
set -euo pipefail
CUR="$(readlink -f "${HOME}/trade-ai-releases/portfolio-server/CURRENT")"
SHA="$(tr -d '[:space:]' < "${CUR}/GIT_SHA")"
PY="${TRADEAI_VENV_PYTHON:-${HOME}/trade-ai-v12-rebuild/trade-ai-v12-rebuild/.venv/bin/python}"
# Extra lane ids beyond the five pilots (e.g. incident-fanin), space-separated; empty = pilots only.
EXTRA=()
for lane in ${TRADEAI_N8N_GATEWAY_EXTRA_LANES:-}; do EXTRA+=(--allow-lane "${lane}"); done
exec "${PY}" "${CUR}/scripts/n8n_coordination_gateway.py" --host 127.0.0.1 --port "${TRADEAI_N8N_GATEWAY_PORT:-18091}" --expected-sha "${SHA}" "${EXTRA[@]}"
