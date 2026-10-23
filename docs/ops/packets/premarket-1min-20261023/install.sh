#!/usr/bin/env bash
# install.sh — OPERATOR-RUN (prepared 2026-10-23 by an agent; the agent never ran it against the live crontab).
# Premarket 1-minute cadence (operator 2026-10-23: "I agree for every minute, because on manually, I do a 1 minute
# candle check"). Two crontab edits, each matched by its EXACT current text (never by line number):
#
#   1. active-trader-premarket-watch: the */5 one-shot pass becomes a cron-launched 1-minute supervisor
#      (`--loop`: ticks on every closed 1-min candle 06:00-09:29 ET, exits at window end). The */5 schedule and the
#      flock stay: while the loop runs, each */5 relaunch finds the lock held and exits at once; if the loop dies,
#      the next */5 slot restarts it. `timeout` 240 -> 13200 s (the window is 3 h 30 min).
#   2. finviz-momentum-scalp-early-lane: the one */5 6-11 line becomes two — 06:00-09:55 with
#      --refresh-if-older-min 5, 10:00-11:55 unchanged at 15. Same lock, same deadlines, same stages.
#
# What changes on the operator's phone: nothing until active_trader_premarket.cadence_mode is set to live
# (default shadow: the old 5-min heads-up is still the only sender; the 1-min threaded path is journaled beside it).
#
# Usage:
#   bash install.sh --preview   # checks + backup + exact diff; changes nothing
#   bash install.sh             # same, then ONE "APPLY" prompt; installs; reads back and verifies
# Refuses inside 05:55-09:35 ET on weekdays (the premarket window) unless FORCE_IN_WINDOW=1.
# Backup once at start: ~/.cache/crontab.bak-<UTC> (never deleted). Rollback: crontab <backup>.
set -euo pipefail
set -f

PREVIEW=0
case "${1:-}" in
  --preview) PREVIEW=1 ;;
  "") ;;
  *) echo "usage: $0 [--preview]"; exit 2 ;;
esac

CRONTAB_BIN="${CRONTAB_BIN:-crontab}"
EXPECT_HOST="${EXPECT_HOST:-ms01-openclaw}"
EXPECT_USER="${EXPECT_USER:-johnclaw}"
[[ "$(hostname)" == "$EXPECT_HOST" ]] || { echo "REFUSED: wrong host"; exit 3; }
[[ "$(id -un)" == "$EXPECT_USER" ]] || { echo "REFUSED: wrong user"; exit 3; }

STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
mkdir -p "$HOME/.cache"
BACKUP="$HOME/.cache/crontab.bak-$STAMP"
WORK="$HOME/.cache/premarket-1min-$STAMP"; mkdir -p "$WORK"
# Captured to a file, never piped into an early-exit reader (SIGPIPE under pipefail, fixed in PR #1965).
"$CRONTAB_BIN" -l > "$WORK/crontab.live" || { echo "REFUSED: crontab -l failed"; exit 3; }
PROJ="$(grep -E '^PROJ=' "$WORK/crontab.live" | tail -1 | cut -d= -f2- || true)"
PY="$(grep -E '^PY=' "$WORK/crontab.live" | tail -1 | cut -d= -f2- || true)"
PROJ="${PROJ_OVERRIDE:-$PROJ}"
[[ -n "$PROJ" && -f "$PROJ/scripts/active_trader/premarket_watch.py" ]] || { echo "REFUSED: crontab PROJ has no premarket_watch.py"; exit 3; }
grep -qF -- '"--loop"' "$PROJ/scripts/active_trader/premarket_watch.py" \
  || { echo "REFUSED: the served release has no --loop (serve the 1-minute PR first)"; exit 3; }
grep -qF -- 'cadence_mode' "$PROJ/config/scalp_signal_engine.yaml" \
  || { echo "REFUSED: the served config has no cadence_mode (serve the 1-minute PR first)"; exit 3; }
cp -p "$WORK/crontab.live" "$BACKUP"
echo "== backup: $BACKUP (sha256 $(sha256sum "$BACKUP" | cut -c1-16))"
rollback_hint() { echo "ROLLBACK: $CRONTAB_BIN \"$BACKUP\"" >&2; }

# OLD line, then its replacement line(s). Quoted heredoc: no expansion; $PROJ / $PY stay literal as in the crontab.
cat > "$WORK/plan.txt" <<'PLAN'
@@ active-trader-premarket-watch
- */5 6-9 * * 1-5 cd $PROJ && flock -n /tmp/at_premarket.lock timeout 240 $PY scripts/active_trader/premarket_watch.py --apply >> logs/at_premarket_watch.log 2>&1
+ */5 6-9 * * 1-5 cd $PROJ && flock -n /tmp/at_premarket.lock timeout 13200 $PY scripts/active_trader/premarket_watch.py --apply --loop >> logs/at_premarket_watch.log 2>&1
@@ finviz-momentum-scalp-early-lane
- */5 6-11 * * 1-5 cd $PROJ && flock -n /tmp/tradeai_finviz_momentum_scalp.lock timeout 280 env MOMENTUM_SCALP_OUTER_DEADLINE_S=260 $PY scripts/run_finviz_momentum_scalp_scan.py --window early --apply --refresh-if-older-min 15 --sync-signals --generate-proposals --run-validation-fast-path >> logs/finviz_momentum_scalp_scan.log 2>&1
+ */5 6-9 * * 1-5 cd $PROJ && flock -n /tmp/tradeai_finviz_momentum_scalp.lock timeout 280 env MOMENTUM_SCALP_OUTER_DEADLINE_S=260 $PY scripts/run_finviz_momentum_scalp_scan.py --window early --apply --refresh-if-older-min 5 --sync-signals --generate-proposals --run-validation-fast-path >> logs/finviz_momentum_scalp_scan.log 2>&1
+ */5 10-11 * * 1-5 cd $PROJ && flock -n /tmp/tradeai_finviz_momentum_scalp.lock timeout 280 env MOMENTUM_SCALP_OUTER_DEADLINE_S=260 $PY scripts/run_finviz_momentum_scalp_scan.py --window early --apply --refresh-if-older-min 15 --sync-signals --generate-proposals --run-validation-fast-path >> logs/finviz_momentum_scalp_scan.log 2>&1
PLAN

cat > "$WORK/edit.py" <<'PYEOF'
import sys
live, plan, out, newlines_out = sys.argv[1:5]
lines = open(live, newline="").read().split("\n")
steps, cur = [], None
for raw in open(plan).read().splitlines():
    if raw.startswith("@@ "):
        cur = {"lane": raw[3:], "old": None, "new": []}; steps.append(cur)
    elif raw.startswith("- "):
        cur["old"] = raw[2:]
    elif raw.startswith("+ "):
        cur["new"].append(raw[2:])
changed, expect = 0, []
for st in steps:
    expect.extend(st["new"])
    hits = [i for i, l in enumerate(lines) if l == st["old"]]
    if len(hits) == 1:
        if any(l == n for l in lines for n in st["new"] if n != st["old"]):
            sys.exit(f"REFUSED: {st['lane']}: old line AND a new line are both present; fix by hand")
        i = hits[0]
        lines[i:i + 1] = st["new"]
        changed += 1
        print(f"   {st['lane']}: 1 line -> {len(st['new'])} line(s)", file=sys.stderr)
    elif not hits and all(lines.count(n) == 1 for n in st["new"]):
        print(f"   {st['lane']}: already applied", file=sys.stderr)
    else:
        sys.exit(f"REFUSED: {st['lane']}: expected exactly 1 line equal to the current text, found {len(hits)}")
open(out, "w", newline="").write("\n".join(lines))
open(newlines_out, "w").write("\n".join(expect) + "\n")
print(changed)
PYEOF
PYBIN="${PY:-python3}"; [[ -x "$PYBIN" ]] || PYBIN=python3
N="$("$PYBIN" "$WORK/edit.py" "$WORK/crontab.live" "$WORK/plan.txt" "$WORK/candidate" "$WORK/expected-lines")" \
  || { rollback_hint; exit 3; }
echo "== crontab diff ($N edit(s))"
diff "$WORK/crontab.live" "$WORK/candidate" || true
if [[ $PREVIEW == 1 ]]; then echo "PREVIEW ONLY — nothing changed. Backup kept at $BACKUP"; exit 0; fi
[[ "$N" -gt 0 ]] || { echo "Nothing to change (already applied)."; exit 0; }

if [[ "${FORCE_IN_WINDOW:-0}" != 1 ]]; then
  DOW="$(TZ=America/New_York date +%u)"; HM="$(TZ=America/New_York date +%H%M)"
  if [[ "$DOW" -le 5 && "$HM" > "0554" && "$HM" < "0936" ]]; then
    echo "REFUSED: inside the premarket window (05:55-09:35 ET); run after 09:35 or before 05:55"; exit 4
  fi
fi
read -r -p "Type APPLY to install these $N crontab edit(s): " answer
[[ "$answer" == "APPLY" ]] || { echo "Not confirmed — nothing changed."; exit 0; }

"$CRONTAB_BIN" -l > "$WORK/before-install" || { echo "REFUSED: crontab -l failed"; exit 5; }
cmp -s "$WORK/before-install" "$WORK/crontab.live" || { echo "REFUSED: the crontab changed since the preview; re-run."; exit 5; }
"$CRONTAB_BIN" - < "$WORK/candidate" || { echo "FAILED: install"; rollback_hint; exit 5; }
"$CRONTAB_BIN" -l > "$WORK/after-installed" || { echo "FAILED: read-back"; rollback_hint; exit 5; }
cmp -s "$WORK/after-installed" "$WORK/candidate" || { echo "FAILED: read-back differs"; rollback_hint; exit 5; }
while IFS= read -r line; do
  [[ -n "$line" ]] || continue
  [[ "$(grep -cxF -- "$line" "$WORK/after-installed")" == 1 ]] || { echo "FAILED: a new line is not present exactly once"; rollback_hint; exit 5; }
done < "$WORK/expected-lines"
grep -qxF -- '*/5 6-11 * * 1-5 cd $PROJ && flock -n /tmp/tradeai_finviz_momentum_scalp.lock timeout 280 env MOMENTUM_SCALP_OUTER_DEADLINE_S=260 $PY scripts/run_finviz_momentum_scalp_scan.py --window early --apply --refresh-if-older-min 15 --sync-signals --generate-proposals --run-validation-fast-path >> logs/finviz_momentum_scalp_scan.log 2>&1' "$WORK/after-installed" \
  && { echo "FAILED: the old finviz line is still present"; rollback_hint; exit 5; }
echo "VERIFIED: $N edit(s) installed, read back byte for byte (captured file $WORK/after-installed)."
echo "DONE. Backup: $BACKUP   Rollback: $CRONTAB_BIN \"$BACKUP\""
echo "Next: tomorrow 06:00 the loop starts; check logs/at_premarket_watch.log for '[1m]' / '[focus]' lines and"
echo "      python3 scripts/premarket_cadence_compare.py --day <date>. Live switch: docs/implementation/PREMARKET_1MIN_THREADED.md"
