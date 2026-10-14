#!/usr/bin/env bash
# 03 — re-point `tailscale serve` 443 from localhost:7777 (service listener, token-only) to the
# identity-trusting serve_proxy listener (0600 unix socket inside portfolio_server).
# Dry run by default; pass --apply. Needs sudo (tailscaled config). Leaves :8443 (DOF) untouched.
# Rollback: 03_serve_rollback.sh --apply
set -euo pipefail
SOCK="${CC_SERVE_SOCKET:-/run/user/1000/tradeai-cc/serve.sock}"
OUT="${CC_PACKET_OUT:-$HOME/n8n-maturity-verification/packets/cc-tailscale-identity-20261014}"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
mkdir -p "$OUT"

tailscale serve status --json > "$OUT/serve_status.before.$STAMP.json"
echo "saved $OUT/serve_status.before.$STAMP.json"
tailscale serve status

# Preconditions: the socket exists, is a socket, mode 0600, and answers as the cc_auth serve_proxy
# listener: a request WITHOUT identity is 200 + a would_deny row (report_only) or 403 (enforce).
[[ -S "$SOCK" ]] || { echo "ABORT: $SOCK is not a socket — is the new release (step 2) serving?"; exit 1; }
mode="$(stat -c '%a' "$SOCK")"
[[ "$mode" == "600" ]] || { echo "ABORT: $SOCK mode $mode (want 600)"; exit 1; }
code="$(curl -s -o /dev/null -w '%{http_code}' --unix-socket "$SOCK" http://cc/api/health || echo 000)"
echo "socket probe /api/health without identity -> HTTP $code (report_only: 200 + would_deny row; enforce: 403)"
[[ "$code" == "200" || "$code" == "403" ]] || { echo "ABORT: unexpected probe status"; exit 1; }

if [[ "${1:-}" != "--apply" ]]; then
  echo "[dry-run] would run: sudo tailscale serve --bg --https=443 unix:$SOCK"
  exit 0
fi
# Replaces the "/" handler on 443. If tailscale refuses because a handler exists, run
#   sudo tailscale serve --https=443 off
# then re-run this script (443 is down for those seconds; :8443 is unaffected).
sudo tailscale serve --bg --https=443 "unix:$SOCK"
tailscale serve status
echo "now open https://ms01-openclaw.tail163d14.ts.net from phone + laptop, then run 04_check_decisions.py"
