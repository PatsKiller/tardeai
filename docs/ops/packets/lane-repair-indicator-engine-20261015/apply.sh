#!/usr/bin/env bash
# APPLY the indicator-engine cron repair (lane repair 2026-10-15). OPERATOR ONLY: needs an active `cron` grant whose
# reason names this packet (guard grants are checked by the operator; agents never edit crontab).
# n8n cutover standard (memory 2026-10-14): fix + dry run + regression + one forced live run; no soak.
set -euo pipefail
set -f

CODE="$HOME/trade-ai-releases/portfolio-server/CURRENT"
PY="$HOME/trade-ai-v12-rebuild/trade-ai-v12-rebuild/.venv/bin/python"
PK="$(cd "$(dirname "$0")" && pwd)"
W="$HOME/.local/state/lane-repair/indicator-engine-apply-$(date -u +%Y%m%dT%H%M%SZ)"
mkdir -p "$W"

# 0. Preconditions (each prints OK or stops)
grep -q -- '"--universe" in _sys.argv' "$CODE/scripts/indicator_engine.py" && echo "P1 OK served" \
  || { echo "P1 FAIL: CURRENT has no --universe"; exit 3; }
guard show | sed 's/\x1b\[[0-9;]*m//g' | grep -i cron || { echo "P2 FAIL: no active cron grant"; exit 3; }

# 1. Candidate from the LIVE crontab (never a candidate generated earlier)
crontab -l > "$W/crontab.live"
cp -p "$W/crontab.live" "$W/crontab.backup"
python3 "$PK/edit_line.py" apply "$W/crontab.live" "$W/crontab.candidate"
test "$(diff "$W/crontab.live" "$W/crontab.candidate" | grep -c '^[<>]')" = 2 || { echo "diff is not one line"; exit 4; }

# 2. Install with `crontab -` and read it back byte-exact
crontab - < "$W/crontab.candidate"
crontab -l | cmp - "$W/crontab.candidate" && echo "installed exactly"

# 3. Forced live run, exactly as cron runs it (same cwd, interpreter, lock, argv)
cd "$CODE"
set +e
flock -n /tmp/indicator_engine.lock "$PY" scripts/indicator_engine.py --universe > "$W/forced.stdout" 2> "$W/forced.stderr"
rc=$?
set -e
echo "forced run exit=$rc"
tail -1 "$W/forced.stdout"
grep '^LANE_OUTPUT ' "$W/forced.stderr" || true

# 4. Proof (exit 0 is not evidence): the receipt advanced and rows landed
R="$HOME/trade-ai-releases/persistent-state/data/runtime/indicator-engine_last.json"
python3 - "$R" <<'EOF'
import json, sys
d = json.load(open(sys.argv[1]))
o = (d.get("summary") or {}).get("output") or {}
print({"status": d.get("status"), "ok_at": d.get("ok_at"), "produced_count": o.get("produced_count"),
       "attempted_count": o.get("attempted_count"), "skipped_reasons": o.get("skipped_reasons"),
       "empty_reason": o.get("empty_reason")})
EOF
echo "then (read-only): SELECT count(*), max(computed_at) FROM indicator_confluence_cache WHERE profile='swing' AND computed_at >= now() - interval '15 minutes';"
echo "work dir: $W   (rollback: bash $PK/rollback.sh)"
