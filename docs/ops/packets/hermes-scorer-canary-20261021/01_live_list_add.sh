#!/usr/bin/env bash
# hermes-scorer canary step 1 (config-write + service grants): add hermes-watchlist-scorer to the relay/gateway live
# list so the dispatcher's live requests for it stop being demoted to dry_run. Cron L451 keeps running; both fire under
# the one flock /tmp/hermes_scorer.lock (canary, AGENTS.md §23.12).
# Operator 2026-10-21 ~13:05 ET: "push live now".
#   bash 01_live_list_add.sh            dry run (default): served-release check, before/after list, nothing written
#   bash 01_live_list_add.sh --apply    backup, write, read back, restart relay + gateway, check their env
# Refuses --apply unless the SERVED release carries the canary row (registry stage canary, dispatch.mode live,
# allowlist live_arg [] and lock /tmp/hermes_scorer.lock). Touches no crontab, no secret value, no broker.
set -euo pipefail
LANE=hermes-watchlist-scorer
F=${LIVE_LANES_ENV:-$HOME/.config/tradeai/n8n-live-lanes.env}
SERVED=${SERVED:-$(readlink -f "$HOME/trade-ai-releases/portfolio-server/CURRENT")}
SYSTEMCTL_BIN=${SYSTEMCTL_BIN:-systemctl}
PROC_ROOT=${PROC_ROOT:-/proc}
APPLY=0
case "${1:-}" in --apply) APPLY=1 ;; "") ;; *) echo "usage: $0 [--apply]"; exit 2 ;; esac
fail(){ echo "REFUSED: $*"; exit 1; }

served_ok(){
  python3 - "$SERVED" "$LANE" <<'EOF'
import json, os, sys
root, lane = sys.argv[1], sys.argv[2]
j = lambda rel: json.load(open(os.path.join(root, rel)))
row = next(r for r in j("config/lane_registry.json")["lanes"] if r.get("lane_id") == lane)
ent = next(e for e in j("config/n8n_run_allowlist.json")["lanes"] if e["lane_id"] == lane)
checks = {
    "registry stage canary": row["scheduler"].get("stage") == "canary",
    "dispatch.mode live": (row.get("dispatch") or {}).get("mode") == "live",
    "allowlist live_arg []": ent.get("live_arg") == [],
    "allowlist lock = cron flock lock": ent.get("lock") == "/tmp/hermes_scorer.lock" and ent.get("lock_kind") == "flock",
}
for k, v in checks.items():
    print(f"  {'ok ' if v else 'BAD'} served {os.path.basename(root)}: {k}")
sys.exit(0 if all(checks.values()) else 1)
EOF
}

[[ -f "$F" ]] || fail "$F missing"
CUR=$(sed -n 's/^TRADEAI_N8N_RELAY_LIVE_LANES=//p' "$F")
[[ -n "$CUR" ]] || fail "no TRADEAI_N8N_RELAY_LIVE_LANES= line in $F"
NEW=$(printf '%s\n' $CUR "$LANE" | awk 'NF && !seen[$0]++' | paste -sd' ')
echo "live list $F"
echo "  lanes before: $(wc -w <<<"$CUR")  after: $(wc -w <<<"$NEW")"
grep -qw -- "$LANE" <<<"$CUR" && echo "  $LANE already listed" || echo "  adds: $LANE"
SERVED_RC=0; served_ok || SERVED_RC=$?
[[ $APPLY == 1 ]] || { echo "DRY RUN - live list unchanged, nothing restarted"; exit 0; }

[[ $SERVED_RC == 0 ]] || fail "the served release does not carry the canary row: release the canary PR first"
BK="$F.bak-$(date -u +%Y%m%dT%H%M%SZ)-hermes-scorer-canary"
cp -p "$F" "$BK"
printf 'TRADEAI_N8N_RELAY_LIVE_LANES=%s\n' "$NEW" > "$F.tmp" && chmod 600 "$F.tmp" && mv "$F.tmp" "$F"
grep -q "^TRADEAI_N8N_RELAY_LIVE_LANES=.*\b$LANE\b" "$F" || fail "READ-BACK FAILED: $LANE not in $F (backup $BK)"
for l in $CUR; do grep -qw -- "$l" "$F" || fail "READ-BACK FAILED: lost $l (backup $BK)"; done
echo "  backup $BK; read back OK ($(wc -w <<<"$NEW") lanes)"
for u in tradeai-n8n-run-relay tradeai-n8n-coordination-gateway; do
  "$SYSTEMCTL_BIN" --user restart "$u.service"; sleep "${RESTART_SETTLE_S:-2}"
  "$SYSTEMCTL_BIN" --user is-active --quiet "$u.service" || fail "$u not active after restart (rollback: README)"
  pid=$("$SYSTEMCTL_BIN" --user show -p MainPID --value "$u.service")
  # names only: grep -c prints a count, never the environment's values
  n=$(tr '\0' '\n' < "$PROC_ROOT/$pid/environ" | grep '^TRADEAI_N8N_RELAY_LIVE_LANES=' | grep -cw -- "$LANE" || true)
  [[ "$n" == 1 ]] && echo "  $u active, live list carries $LANE" || fail "$u live list lacks $LANE after restart"
done
echo "APPLIED: $LANE is on the live list; next: README step 3 (live RUN_DONE proof)"
