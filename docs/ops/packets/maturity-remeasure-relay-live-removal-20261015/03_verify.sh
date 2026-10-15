#!/usr/bin/env bash
# Read-only verify. Prints ONLY the TRADEAI_N8N_RELAY_LIVE_LANES line of each running unit (no other variable).
set -u
F="${LIVE_LANES_FILE:-$HOME/.config/tradeai/n8n-live-lanes.env}"
ok=1
if grep -qw maturity-remeasure "$F"; then echo "FAIL: still in $F"; ok=0; else echo "file: maturity-remeasure absent"; fi
echo "file lanes: $(grep '^TRADEAI_N8N_RELAY_LIVE_LANES=' "$F" | cut -d= -f2- | wc -w) (expect 6)"
for u in tradeai-n8n-run-relay.service tradeai-n8n-coordination-gateway.service; do
  pid="$(systemctl --user show -p MainPID --value "$u")"
  line="$(tr '\0' '\n' < "/proc/$pid/environ" 2>/dev/null | grep '^TRADEAI_N8N_RELAY_LIVE_LANES=' || true)"
  echo "$u pid=$pid: $line"
  case " ${line#*=} " in *" maturity-remeasure "*) echo "FAIL: $u still has it (restart pending?)"; ok=0 ;; esac
  [ -n "$line" ] || { echo "FAIL: $u has no live-lane variable"; ok=0; }
done
if [ "$ok" = 1 ]; then echo "VERIFY OK"; else echo "VERIFY FAILED"; exit 1; fi
