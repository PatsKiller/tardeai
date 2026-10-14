#!/usr/bin/env bash
# 03 rollback — point `tailscale serve` 443 back at localhost:7777 (the pre-change state).
# NOTE: once enforce is on (step 6), :7777 requires the service token, so browsers through serve
# would get 401 there. Roll back step 6 FIRST (06_enforce_rollback.sh --apply).
set -euo pipefail
if [[ "${1:-}" != "--apply" ]]; then
  tailscale serve status
  echo "[dry-run] would run: sudo tailscale serve --bg --https=443 http://localhost:7777"
  exit 0
fi
sudo tailscale serve --bg --https=443 http://localhost:7777
tailscale serve status
