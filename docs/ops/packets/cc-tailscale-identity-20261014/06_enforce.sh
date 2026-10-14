#!/usr/bin/env bash
# 06 — leave report_only: denials become real (401 on :7777 without the token, 403 on the serve
# socket without an allowed tailnet login). Step-up refusals were already enforced from step 2.
# Dry run by default; --apply writes a drop-in, daemon-reloads and restarts portfolio-server
# (do it outside market hours). Rollback: 06_enforce_rollback.sh --apply (back to report_only).
# Kill switch (all cc_auth off, legacy open behaviour): Environment=TRADEAI_CC_AUTH_ENFORCE=0.
set -euo pipefail
D="$HOME/.config/systemd/user/portfolio-server.service.d"
F="$D/44-cc-auth-enforce.conf"
BODY='# cc_auth enforce (packet cc-tailscale-identity-20261014 step 6). config/cc_auth.yaml ships report_only: true.
# Rollback: 06_enforce_rollback.sh --apply (moves this file aside), daemon-reload, restart.
[Service]
Environment=TRADEAI_CC_AUTH_REPORT_ONLY=0'
if [[ "${1:-}" != "--apply" ]]; then
  echo "[dry-run] would write $F:"; echo "$BODY"
  echo "[dry-run] would: systemctl --user daemon-reload && systemctl --user restart portfolio-server.service"
  exit 0
fi
[[ -f "$HOME/.config/tradeai/cc_service_token" ]] || { echo "ABORT: no service token (step 1)"; exit 1; }
printf '%s\n' "$BODY" > "$F"
systemctl --user daemon-reload
systemctl --user restart portfolio-server.service
sleep 8
systemctl --user show portfolio-server.service -p Environment | tr ' ' '\n' | grep TRADEAI_CC_AUTH || true
echo -n "service listener, no token (expect 401): "
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:7777/api/v2/risk
echo -n "service listener, with token (expect 200): "
"$HOME/trade-ai-releases/portfolio-server/CURRENT/scripts/cc_curl.sh" -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:7777/api/v2/risk
echo -n "serve socket, no identity (expect 403): "
curl -s -o /dev/null -w '%{http_code}\n' --unix-socket /run/user/1000/tradeai-cc/serve.sock http://cc/api/v2/risk
