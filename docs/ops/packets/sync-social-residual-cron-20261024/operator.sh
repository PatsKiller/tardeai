#!/usr/bin/env bash
# OPERATOR ONLY: even --preview reads the host crontab and requires the applicable cron grant.
# The author tests this wrapper solely with an isolated fake crontab on PATH.
# Exact residual absolute-CURRENT line only; no service, registry, lock, workflow or cron-line deletion.
set -euo pipefail
umask 077

case "${1:-}" in
  --preview|--apply) MODE="$1" ;;
  *) echo "usage: bash operator.sh --preview|--apply (OPERATOR ONLY)" >&2; exit 2 ;;
esac
[[ "$#" == 1 ]] || { echo "REFUSED: unexpected arguments" >&2; exit 2; }
[[ "$(hostname)" == ms01-openclaw && "$(id -un)" == johnclaw ]] || {
  echo "REFUSED: expected johnclaw on ms01-openclaw" >&2; exit 3;
}
PACKET=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
EVIDENCE_ROOT="${WP33_EVIDENCE_ROOT:-$HOME/.cache/rtc}"
mkdir -p -- "$EVIDENCE_ROOT"
WORK=$(mktemp -d "$EVIDENCE_ROOT/wp33-sync-social-XXXXXXXX")
echo "PRIVATE_EVIDENCE=$WORK"
if ! crontab -l > "$WORK/crontab.captured"; then
  echo "REFUSED: crontab read failed; no empty replacement" >&2; exit 3
fi
python3 "$PACKET/retire_packet.py" plan --snapshot "$WORK/crontab.captured" --out-dir "$WORK/plan"
cat -- "$WORK/plan/target-only.diff"
python3 "$PACKET/retire_packet.py" verify --snapshot "$WORK/plan/crontab.before" \
  --candidate "$WORK/plan/crontab.candidate" --receipt "$WORK/plan/plan.json"
if [[ "$MODE" == --preview ]]; then
  echo "PREVIEW ONLY: host crontab unchanged; private backup and exact candidate retained."
  exit 0
fi
CHANGED=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["changed_lines"])' "$WORK/plan/plan.json")
if [[ "$CHANGED" == 0 ]]; then
  echo "ALREADY RETIRED IN SNAPSHOT: no install; n8n acceptance remains unmeasured."
  exit 0
fi
read -r -p 'Operator decision: type ACK-RETIRE-SYNC-SOCIAL-RESIDUAL: ' ACK
[[ "$ACK" == ACK-RETIRE-SYNC-SOCIAL-RESIDUAL ]] || { echo "Not confirmed; no install."; exit 4; }
# Capture full output before comparing: no crontab -l | grep -q/head SIGPIPE false failures.
crontab -l > "$WORK/crontab.recheck"
cmp -s "$WORK/crontab.recheck" "$WORK/plan/crontab.before" || {
  echo "REFUSED: crontab changed after preview; no install." >&2; exit 5;
}
python3 "$PACKET/retire_packet.py" verify --snapshot "$WORK/plan/crontab.before" \
  --candidate "$WORK/plan/crontab.candidate" --receipt "$WORK/plan/plan.json"
crontab "$WORK/plan/crontab.candidate"
crontab -l > "$WORK/crontab.installed"
python3 "$PACKET/retire_packet.py" verify --snapshot "$WORK/plan/crontab.before" \
  --candidate "$WORK/plan/crontab.candidate" --receipt "$WORK/plan/plan.json" \
  --installed "$WORK/crontab.installed" --verified-out "$WORK/installed-verification.json"
echo "COMMENT INSTALLED AND READ BACK: only the exact residual line was prefixed."
echo "No n8n/runtime/business-output acceptance claimed. Evidence: $WORK"
# No automatic restore and no crontab <whole-backup> operation. Any reversal needs a fresh scoped operator plan.
