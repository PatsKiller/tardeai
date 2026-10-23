#!/usr/bin/env bash
# double-run-operator.sh — OPERATOR-RUN (prepared 2026-10-22 by an agent; the agent never ran it).
# Item 3 of the 2026-10-22 incident-pause proposal (operator "yes"): lanes on BOTH crontab and the n8n relay live list
# whose cron line has no TRADEAI_EFFECT_CLAIM wrapper. A shared `flock -n` stops the two runs overlapping; it does not
# stop them running one after the other in the same slot. Measured 2026-10-22 from the coordination ledger
# (read-only), receipts and log mtimes (docs/ops/packets/incident-spcx-resume-20261022/README.md §2).
#
# This script fixes the three lanes where n8n is PROVEN live, by commenting their cron line (prefix only; the line is
# kept, never deleted):
#   L875 sync_social_to_intelligence          ran twice in 9 of 9 slots 10-16..10-22 (n8n 9 live RUN_DONE)
#   L219 materialize_watchlist_strategy_cards ran twice in 33 slots (n8n 35 live RUN_DONE)
#   L845 hermes_discovery_scorecard           ran twice on 10-19, 10-21, 10-22 (n8n 4 live RUN_DONE)
# It refuses a lane with fewer than 3 live RUN_DONE since 10-14 (re-read from the ledger at run time).
#
# NOT changed here (see README §2): opening_intelligence (one duplicate jsonl row 10-22; needs a staged effect key
# through the canary effect-key process first), job_coverage_monitor and classify_instruments (overwrite/read-only:
# a duplicate costs time, not data), finviz_enrichment and finviz_sector_research (never ran twice; cron always wins
# the lock), maturity_remeasure (n8n only dry-runs it; take it off the live list with
# docs/ops/packets/maturity-remeasure-relay-live-removal-20261015/).
#
# Usage:
#   bash double-run-operator.sh --preview   # ledger evidence + crontab diff; changes nothing
#   bash double-run-operator.sh             # same, then ONE "APPLY" prompt
# Backup once at start: ~/.cache/crontab.bak-<UTC> (never deleted). Rollback: crontab <backup>.
set -euo pipefail
set -f

PREVIEW=0
case "${1:-}" in
  --preview) PREVIEW=1 ;;
  "") ;;
  *) echo "usage: $0 [--preview]"; exit 2 ;;
esac

[[ "$(hostname)" == "ms01-openclaw" ]] || { echo "REFUSED: wrong host"; exit 3; }
[[ "$(id -un)" == "johnclaw" ]] || { echo "REFUSED: wrong user"; exit 3; }
LEDGER="/home/johnclaw/trade-ai-releases/persistent-state/data/governance/n8n_coordination_ledger.sqlite"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
mkdir -p "$HOME/.cache"
BACKUP="$HOME/.cache/crontab.bak-$STAMP"
WORK="$HOME/.cache/double-run-operator-$STAMP"; mkdir -p "$WORK"
crontab -l > "$WORK/crontab.live"
PY="$(grep -E '^PY=' "$WORK/crontab.live" | tail -1 | cut -d= -f2-)"
[[ -x "$PY" ]] || { echo "REFUSED: crontab PY not executable"; exit 3; }
cp -p "$WORK/crontab.live" "$BACKUP"
echo "== backup: $BACKUP (sha256 $(sha256sum "$BACKUP" | cut -c1-16))"
rollback_hint() { echo "ROLLBACK: crontab \"$BACKUP\"" >&2; }

# LANE<TAB>EXACT CURRENT LINE   (quoted heredoc: no expansion). The new line is PREFIX + the current line.
PREFIX='# N8N-OWNED 2026-10-22 double-run fix (n8n live RUN_DONE proven; cron side retired) '
cat > "$WORK/plan.tsv" <<'PLAN'
sync-social-to-intelligence	30 11,15 * * 1-5 cd $PROJ && flock -n /tmp/sync_social_to_intelligence.lock $PY scripts/sync_social_to_intelligence.py --apply >> logs/sync_social_to_intelligence.log 2>&1
materialize-watchlist-strategy-cards	*/30 6-16 * * 1-5 cd $PROJ && flock -n /tmp/materialize_cards.lock $PY scripts/materialize_watchlist_strategy_cards.py >> logs/watchlist_strategy_cards.log 2>&1
hermes-discovery-scorecard	30 5 * * * cd $PROJ && flock -n /tmp/hermes_discovery_scorecard.lock $PY scripts/hermes_discovery_scorecard.py >> logs/hermes_discovery_scorecard.log 2>&1
PLAN

# ── preview 1: n8n is proven for each lane (coordination ledger, read-only) ──────────────────────────────
echo "== n8n runs since 2026-10-14 (ledger mode=ro, PRAGMA query_only)"
"$PY" - "$LEDGER" "$WORK/plan.tsv" <<'PYEOF'
import sqlite3, sys
ledger, plan = sys.argv[1:3]
c = sqlite3.connect(f"file:{ledger}?mode=ro", uri=True); c.execute("PRAGMA query_only=1")
for row in open(plan).read().splitlines():
    lane = row.split("\t")[0]
    n = {}
    for state, mode, cnt in c.execute("select state, mode, count(*) from runs where lane_id=? and requested_at>='2026-10-14' group by state, mode", (lane,)):
        n[f"{mode}:{state}"] = cnt
    print(f"   {lane:40} {n}")
    if n.get("live:RUN_DONE", 0) < 3:
        sys.exit(f"REFUSED: {lane} has {n.get('live:RUN_DONE', 0)} live RUN_DONE since 10-14; needs >= 3 (n8n not proven)")
PYEOF

# ── preview 2: crontab diff ──────────────────────────────────────────────────────────────────────────────
cat > "$WORK/edit.py" <<'PYEOF'
import sys
live, plan, prefix, out = sys.argv[1:5]
lines = open(live, newline="").read().split("\n")
n = 0
for row in open(plan).read().splitlines():
    lane, old = row.split("\t")
    hits = [i for i, l in enumerate(lines) if l == old]
    if len(hits) != 1:
        if lines.count(prefix + old) == 1:
            print(f"   {lane}: already commented", file=sys.stderr); continue
        sys.exit(f"REFUSED: {lane}: expected exactly 1 line equal to the current text, found {len(hits)}")
    lines[hits[0]] = prefix + old; n += 1
open(out, "w", newline="").write("\n".join(lines)); print(n)
PYEOF
N="$("$PY" "$WORK/edit.py" "$WORK/crontab.live" "$WORK/plan.tsv" "$PREFIX" "$WORK/candidate")" || { rollback_hint; exit 3; }
echo "== crontab diff ($N line(s))"
diff "$WORK/crontab.live" "$WORK/candidate" || true
[[ "$(diff "$WORK/crontab.live" "$WORK/candidate" | grep -c '^[<>]')" == "$((N * 2))" ]] || { echo "REFUSED: diff is not exactly $N line(s)"; exit 3; }
if [[ $PREVIEW == 1 ]]; then echo "PREVIEW ONLY — nothing changed. Backup kept at $BACKUP"; exit 0; fi
[[ "$N" -gt 0 ]] || { echo "Nothing to change."; exit 0; }
read -r -p "Type APPLY to comment these $N cron line(s): " answer
[[ "$answer" == "APPLY" ]] || { echo "Not confirmed — nothing changed."; exit 0; }

# ── apply with read-back ─────────────────────────────────────────────────────────────────────────────────
# Every read-back is captured to a file first. Never `crontab -l | grep -q`: grep -q exits at the first match,
# crontab -l takes SIGPIPE writing the rest of a large crontab, and pipefail turns that 141 into a false FAILED
# (2026-10-22 operator run: the edit applied, the verify printed FAILED).
crontab -l > "$WORK/before-install" || { echo "REFUSED: crontab -l failed"; exit 5; }
cmp -s "$WORK/before-install" "$WORK/crontab.live" || { echo "REFUSED: the crontab changed since the preview; re-run."; exit 5; }
crontab - < "$WORK/candidate" || { echo "FAILED: install"; rollback_hint; exit 5; }
crontab -l > "$WORK/after-installed" || { echo "FAILED: read-back"; rollback_hint; exit 5; }
cmp -s "$WORK/after-installed" "$WORK/candidate" || { echo "FAILED: read-back differs"; rollback_hint; exit 5; }
while IFS=$'\t' read -r lane old; do
  grep -qxF -- "$PREFIX$old" "$WORK/after-installed" || { echo "FAILED: $lane line not as expected after install"; rollback_hint; exit 5; }
  echo "   $lane: cron line commented, verified (crontab -l); n8n remains its scheduler"
done < "$WORK/plan.tsv"
echo "DONE. Backup: $BACKUP   Rollback: crontab \"$BACKUP\""
echo "Next (agent PR): set these 3 registry rows to scheduler stage cutover (n8n owns the slot)."
