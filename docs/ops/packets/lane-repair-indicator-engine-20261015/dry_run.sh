#!/usr/bin/env bash
# Dry run of the indicator-engine cron repair (lane repair 2026-10-15). Writes ONLY under $W.
# No crontab change, no DB write (the --dry-run session is READ ONLY), no provider call, no telemetry.
# Prerequisite: the PR carrying `indicator_engine.py --universe` is merged AND served (CURRENT has it).
set -euo pipefail
set -f   # the cron fields contain `*`: no glob expansion anywhere (memory: shell glob in cron loops, 2026-10-09)

CODE="$HOME/trade-ai-releases/portfolio-server/CURRENT"
PY="$HOME/trade-ai-v12-rebuild/trade-ai-v12-rebuild/.venv/bin/python"   # the crontab's $PY
PK="$(cd "$(dirname "$0")" && pwd)"
W="$HOME/.local/state/lane-repair/indicator-engine-dry-$(date -u +%Y%m%dT%H%M%SZ)"
mkdir -p "$W"

grep -q -- '"--universe" in _sys.argv' "$CODE/scripts/indicator_engine.py" \
  || { echo "NOT SERVED: $CODE/scripts/indicator_engine.py has no --universe mode; promote the release first"; exit 3; }

crontab -l > "$W/crontab.live"
python3 "$PK/edit_line.py" apply "$W/crontab.live" "$W/crontab.candidate"
diff "$W/crontab.live" "$W/crontab.candidate" | tee "$W/crontab.diff.observed" || true
#   expect exactly one `<` line (the AMD test-mode line) and one `>` line (flock + --universe)

cd "$CODE"
"$PY" scripts/indicator_engine.py --universe --dry-run > "$W/dry_run.stdout" 2> "$W/dry_run.stderr"
echo "dry run exit=$?"
cat "$W/dry_run.stdout"
grep '^LANE_OUTPUT ' "$W/dry_run.stderr"
#   expect: {"mode": "dry_run", "universe": ~870, "stale": N, "would_compute": N, ...} and a LANE_OUTPUT line with
#   attempted_count = N, produced_count 0, empty_reason "dry_run" (or "no_stale_symbols" when N = 0)
test ! -e "$HOME/trade-ai-releases/persistent-state/data/runtime/indicator-engine_last.json" \
  && echo "OK: no receipt written by the dry run" \
  || echo "NOTE: a receipt exists from an earlier LIVE run; compare its mtime with $W (a dry run never writes it)"
echo "work dir: $W"
