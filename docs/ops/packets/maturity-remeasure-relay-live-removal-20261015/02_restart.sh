#!/usr/bin/env bash
# Unit restart (operator) so both EnvironmentFile readers load the new list. Pick a minute away from the */5 slots.
set -eu
if [ "${APPLY:-0}" != "1" ]; then
  echo "would restart tradeai-n8n-coordination-gateway + tradeai-n8n-run-relay (set APPLY=1)"
  exit 0
fi
for u in tradeai-n8n-coordination-gateway.service tradeai-n8n-run-relay.service; do
  systemctl --user restart "$u"
  sleep 2
  printf '%s: %s\n' "$u" "$(systemctl --user is-active "$u")"
done
