#!/usr/bin/env bash
# W5B step 1 (config-write + service grants): add this wave's lanes to the relay/gateway live list, restart the relay.
#   bash 01_relay_live_lanes.sh            dry run: prints the new list
#   bash 01_relay_live_lanes.sh --apply    backup, write, read back, restart tradeai-n8n-run-relay
# Run ONLY after `readlink -f ~/trade-ai-releases/portfolio-server/CURRENT` names a release that contains this wave.
set -euo pipefail
F=${LIVE_LANES_ENV:-$HOME/.config/tradeai/n8n-live-lanes.env}
ADD="research-intelligence-queue"
KEYED="research-intelligence-queue"
SERVED=${SERVED:-$(readlink -f "$HOME/trade-ai-releases/portfolio-server/CURRENT")}
PY=${PY:-$HOME/trade-ai-v12-rebuild/trade-ai-v12-rebuild/.venv/bin/python}
# Owner preflight, fail closed. A keyed lane goes live here, but the effect fabric admits its claim only when the lane
# has an n8n owner row. Armed with no owner, every live slot is refused `effect:effect_no_owner` until the owner is
# seeded - the 2026-11-07 agent-watchlist-engine 07:00 ET refusal. Refuse BOTH modes: the dry run is run before --apply.
missing=""
for lane in $KEYED; do
  proc=$("$PY" "$SERVED/scripts/lib/effect_claim.py" lane-spec --lane "$lane" 2>/dev/null | cut -f1 || true)
  [[ -n "$proc" ]] || proc=$lane
  if ! owner=$("$PY" "$SERVED/scripts/lib/effect_claim.py" show --process "$proc" 2>/dev/null \
      | "$PY" -c 'import json,sys; o=json.load(sys.stdin).get("owner"); print(o["owner"] if o else "none")'); then
    owner="unreadable"
  fi
  [[ "$owner" == "n8n" ]] || missing="$missing $lane($owner)"
done
if [[ -n "$missing" ]]; then
  echo "REFUSED: keyed lane(s) with no n8n effect owner:$missing" >&2
  echo "Seed the owners FIRST, then re-run this step:" >&2
  echo "  TRADEAI_FABRIC_GRANT=<cron grant> bash 02_effect_owners.sh --apply" >&2
  echo "Otherwise every live slot of those lanes is refused effect:effect_no_owner (fail closed)." >&2
  exit 1
fi
CUR=$(sed -n 's/^TRADEAI_N8N_RELAY_LIVE_LANES=//p' "$F")
NEW=$(printf '%s\n' $CUR $ADD | awk 'NF && !seen[$0]++' | paste -sd' ')
echo "before: $CUR"; echo "after : $NEW"
[[ "${1:-}" == "--apply" ]] || { echo "DRY RUN — nothing written"; exit 0; }
cp -p "$F" "$F.bak-$(date -u +%Y%m%dT%H%M%SZ)-W5B"
printf 'TRADEAI_N8N_RELAY_LIVE_LANES=%s\n' "$NEW" > "$F.tmp" && chmod 600 "$F.tmp" && mv "$F.tmp" "$F"
grep -c . "$F" >/dev/null; for l in $ADD; do grep -qw -- "$l" "$F" || { echo "READ-BACK FAILED: $l"; exit 1; }; done
systemctl --user restart tradeai-n8n-run-relay.service
sleep 2; systemctl --user is-active tradeai-n8n-run-relay.service
echo "read back OK; relay restarted"
