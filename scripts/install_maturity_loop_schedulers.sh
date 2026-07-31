#!/usr/bin/env bash
# Install maturity-loop systemd user timers (Watch scheduler, intelligence remediation,
# Hermes research quality remediation, maturity feeds).
# Re-entry resistance refresh is already bundled in watch_alerts_eval (RTH cron).
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PY="$ROOT/.venv/bin/python"
if [ ! -x "$PY" ]; then
  PY="${TRADEAI_PYTHON:-/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild/.venv/bin/python}"
fi
UNIT_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
mkdir -p "$UNIT_DIR"
for f in tradeai-watch-decision-scheduler tradeai-intelligence-remediation \
         tradeai-hermes-research-remediation tradeai-maturity-feeds; do
  sed -e "s|@PROJECT_ROOT@|$ROOT|g" -e "s|@PYTHON@|$PY|g" "$ROOT/config/systemd/user/${f}.service" > "$UNIT_DIR/${f}.service"
  cp "$ROOT/config/systemd/user/${f}.timer" "$UNIT_DIR/"
done
systemctl --user daemon-reload
systemctl --user enable --now tradeai-watch-decision-scheduler.timer
systemctl --user enable --now tradeai-intelligence-remediation.timer
systemctl --user enable --now tradeai-hermes-research-remediation.timer
systemctl --user enable --now tradeai-maturity-feeds.timer
echo "[maturity-loop] timers enabled:"
systemctl --user list-timers 'tradeai-*' --no-pager || true
echo "[maturity-loop] dry-run watch scheduler:"
"$PY" "$ROOT/scripts/watch_decision_scheduler.py" --dry-run | head -n 20
echo "[maturity-loop] dry-run intelligence remediation:"
"$PY" "$ROOT/scripts/intelligence_remediation.py" --dry-run
echo "[maturity-loop] dry-run hermes research quality remediation:"
"$PY" "$ROOT/scripts/hermes_research_quality_remediation.py" --dry-run
echo "[maturity-loop] research_scheduler crons (install manually if missing):"
grep -E 'research_scheduler|hermes_maturity' "$ROOT/crontab_backup.txt" | head -n 8 || true
