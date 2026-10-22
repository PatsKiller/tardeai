#!/usr/bin/env bash
# double-run-operator.sh — OPERATOR-RUN (prepared 2026-10-22 by an agent; the agent never ran it).
# Item 3 of the 2026-10-22 incident-pause proposal (operator "yes"): eight lanes ran on BOTH crontab and the n8n
# dispatcher because their cron line has no TRADEAI_EFFECT_CLAIM wrapper. A shared `flock -n` stops the two runs
# overlapping; it does not stop them running one after the other in the same slot. Measured 2026-10-22 from the
# coordination ledger (read-only), receipts and log mtimes (docs/ops/packets/incident-spcx-resume-20261022/README.md):
#
#   Part A — n8n is PROVEN live, comment the cron line (prefix only; the line is kept, never deleted):
#     L875 sync_social_to_intelligence        ran twice in 9 of 9 slots 10-16..10-22 (n8n 9 live RUN_DONE)
#     L219 materialize_watchlist_strategy_cards ran twice in 33 slots (n8n 34 live RUN_DONE)
#     L845 hermes_discovery_scorecard          ran twice on 10-19, 10-21, 10-22 (n8n 4 live RUN_DONE)
#   Part B — n8n NOT proven, wrap the cron line in the effect claim with owner cron (n8n then skips the slot):
#     L804 opening_intelligence --persist --render   ran twice 10-22 09:15 (jsonl append = a duplicate row)
#     L391 job_coverage_monitor                      ran twice 10-21 20:30
#     L506 classify_instruments                      not twice (lock race decided it)
#     L144 finviz_enrichment                         not twice (n8n always RUN_SKIPPED_LOCK)
#     L526 finviz_sector_research                    not twice (n8n RUN_SKIPPED_LOCK 9 of 9)
#   maturity_remeasure (L1016): NO crontab change — n8n only ever dry-runs it. The stale part is its entry on the relay
#     live list; the existing packet docs/ops/packets/maturity-remeasure-relay-live-removal-20261015/ removes it.
#
# Part B needs the release that carries the five ARMED keys in config/n8n_effect_keys.json (PR "ops(incident-SPCX):
# resume packet, registry truth, double-run fixes, postmortem draft"). Before that release is served, a wrapped line
# would exit 65 and run NOTHING, so Part B refuses unless CURRENT's config has the key with cron_claim true.
# Order inside Part B, per lane: effect_claim.py set-owner --owner cron (the owner row), THEN wrap the cron line.
#
# Usage:
#   bash double-run-operator.sh            # preview (ledger evidence, owner rows, crontab diff) + ONE "APPLY" prompt
#   bash double-run-operator.sh --preview  # preview only; changes nothing
#   bash double-run-operator.sh --part A   # or --part B
# Backup once at start: ~/.cache/crontab.bak-<UTC> (never deleted). Rollback: crontab <backup>; owner rows are moved
# back with effect_claim.py set-owner --process <lane> --owner <previous> --expect-epoch <epoch> (printed below).
set -euo pipefail
set -f

PREVIEW=0; PART="AB"
while [[ $# -gt 0 ]]; do
  case "$1" in
    --preview) PREVIEW=1; shift ;;
    --part) PART="${2:-}"; shift 2 ;;
    *) echo "usage: $0 [--preview] [--part A|B]"; exit 2 ;;
  esac
done
[[ "$PART" == "A" || "$PART" == "B" || "$PART" == "AB" ]] || { echo "--part A or B"; exit 2; }

[[ "$(hostname)" == "ms01-openclaw" ]] || { echo "REFUSED: wrong host"; exit 3; }
[[ "$(id -un)" == "johnclaw" ]] || { echo "REFUSED: wrong user"; exit 3; }
CUR="/home/johnclaw/trade-ai-releases/portfolio-server/CURRENT"
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
rollback_hint() { echo "ROLLBACK (crontab): crontab \"$BACKUP\"" >&2; }

# PART<TAB>LANE<TAB>EXACT CURRENT LINE<TAB>EXACT NEW LINE   (quoted heredoc: no expansion)
cat > "$WORK/plan.tsv" <<'PLAN'
A	sync-social-to-intelligence	30 11,15 * * 1-5 cd $PROJ && flock -n /tmp/sync_social_to_intelligence.lock $PY scripts/sync_social_to_intelligence.py --apply >> logs/sync_social_to_intelligence.log 2>&1	# N8N-OWNED 2026-10-22 double-run fix (n8n live RUN_DONE proven; cron side retired) 30 11,15 * * 1-5 cd $PROJ && flock -n /tmp/sync_social_to_intelligence.lock $PY scripts/sync_social_to_intelligence.py --apply >> logs/sync_social_to_intelligence.log 2>&1
A	materialize-watchlist-strategy-cards	*/30 6-16 * * 1-5 cd $PROJ && flock -n /tmp/materialize_cards.lock $PY scripts/materialize_watchlist_strategy_cards.py >> logs/watchlist_strategy_cards.log 2>&1	# N8N-OWNED 2026-10-22 double-run fix (n8n live RUN_DONE proven; cron side retired) */30 6-16 * * 1-5 cd $PROJ && flock -n /tmp/materialize_cards.lock $PY scripts/materialize_watchlist_strategy_cards.py >> logs/watchlist_strategy_cards.log 2>&1
A	hermes-discovery-scorecard	30 5 * * * cd $PROJ && flock -n /tmp/hermes_discovery_scorecard.lock $PY scripts/hermes_discovery_scorecard.py >> logs/hermes_discovery_scorecard.log 2>&1	# N8N-OWNED 2026-10-22 double-run fix (n8n live RUN_DONE proven; cron side retired) 30 5 * * * cd $PROJ && flock -n /tmp/hermes_discovery_scorecard.lock $PY scripts/hermes_discovery_scorecard.py >> logs/hermes_discovery_scorecard.log 2>&1
B	opening-intelligence-render	15 9 * * 1-5 cd /home/johnclaw/trade-ai-releases/portfolio-server/CURRENT && flock -n /tmp/opening_intel.lock $PY scripts/opening_intelligence.py --persist --render >> logs/opening_intelligence.log 2>&1	15 9 * * 1-5 cd /home/johnclaw/trade-ai-releases/portfolio-server/CURRENT && flock -n /tmp/opening_intel.lock env TRADEAI_EFFECT_CLAIM=opening-intelligence-render bash scripts/effect_claim_cron.sh opening-intelligence-render $PY scripts/opening_intelligence.py --persist --render >> logs/opening_intelligence.log 2>&1
B	job-coverage-monitor	30 8,20 * * * cd $PROJ && flock -n /tmp/tradeai_job_coverage_monitor.lock $PY scripts/job_coverage_monitor.py >> logs/job_coverage_monitor.log 2>&1	30 8,20 * * * cd $PROJ && flock -n /tmp/tradeai_job_coverage_monitor.lock env TRADEAI_EFFECT_CLAIM=job-coverage-monitor bash scripts/effect_claim_cron.sh job-coverage-monitor $PY scripts/job_coverage_monitor.py >> logs/job_coverage_monitor.log 2>&1
B	classify-instruments	30 6 * * 6 cd $PROJ && flock -n /tmp/classify_instr.lock $PY scripts/classify_instruments.py >> logs/classify_instruments.log 2>&1  # weekly: instrument_type + expense ratios	30 6 * * 6 cd $PROJ && flock -n /tmp/classify_instr.lock env TRADEAI_EFFECT_CLAIM=classify-instruments bash scripts/effect_claim_cron.sh classify-instruments $PY scripts/classify_instruments.py >> logs/classify_instruments.log 2>&1  # weekly: instrument_type + expense ratios
B	finviz-enrichment	0 13 * * 1-5 cd $PROJ && flock -n /tmp/finviz_enrichment.lock $PY scripts/finviz_enrichment.py >> logs/finviz_enrichment.log 2>&1	0 13 * * 1-5 cd $PROJ && flock -n /tmp/finviz_enrichment.lock env TRADEAI_EFFECT_CLAIM=finviz-enrichment bash scripts/effect_claim_cron.sh finviz-enrichment $PY scripts/finviz_enrichment.py >> logs/finviz_enrichment.log 2>&1
B	finviz-sector-research	15 10,16 * * 1-5 cd $PROJ && flock -n /tmp/finviz_sector.lock $PY scripts/finviz_sector_research.py >> logs/finviz_sector.log 2>&1	15 10,16 * * 1-5 cd $PROJ && flock -n /tmp/finviz_sector.lock env TRADEAI_EFFECT_CLAIM=finviz-sector-research bash scripts/effect_claim_cron.sh finviz-sector-research $PY scripts/finviz_sector_research.py >> logs/finviz_sector.log 2>&1
PLAN

# ── preview 1: n8n evidence per lane (coordination ledger, read-only) ────────────────────────────────────
echo "== n8n live runs since 2026-10-14 (ledger, mode=ro, query_only)"
"$PY" - "$LEDGER" "$WORK/plan.tsv" "$PART" <<'PYEOF'
import sqlite3, sys
ledger, plan, part = sys.argv[1:4]
c = sqlite3.connect(f"file:{ledger}?mode=ro", uri=True); c.execute("PRAGMA query_only=1")
for row in open(plan).read().splitlines():
    p, lane = row.split("\t")[:2]
    if p not in part: continue
    n = {}
    for state, mode, cnt in c.execute("select state, mode, count(*) from runs where lane_id=? and requested_at>='2026-10-14' group by state, mode", (lane,)):
        n[f"{mode}:{state}"] = cnt
    print(f"   [{p}] {lane:40} {n}")
    if p == "A" and n.get("live:RUN_DONE", 0) < 3:
        sys.exit(f"REFUSED: {lane} has {n.get('live:RUN_DONE', 0)} live RUN_DONE since 10-14; Part A needs >= 3 (n8n not proven)")
PYEOF
echo "   Part A requires live RUN_DONE >= 3 for each lane; Part B lanes keep cron as the owner."

# ── preview 2: Part B preconditions (armed key served) and owner rows ────────────────────────────────────
owner_of(){ "$PY" "$CUR/scripts/lib/effect_claim.py" show --process "$1" \
  | "$PY" -c 'import json,sys; o=json.load(sys.stdin)["owner"]; print("none none" if o is None else "%s %s" % (o["owner"], o["epoch"]))'; }
if [[ "$PART" == *B* ]]; then
  echo "== Part B preconditions: armed key in the SERVED config, and current owner row"
  while IFS=$'\t' read -r p lane _old _new; do
    [[ "$p" == "B" ]] || continue
    "$PY" -c 'import json,sys; k=json.load(open(sys.argv[1]))["lanes"].get(sys.argv[2]) or {}; sys.exit(0 if k.get("cron_claim") is True and k.get("n8n_claim") is True else 1)' \
      "$CUR/config/n8n_effect_keys.json" "$lane" \
      || { echo "REFUSED: $lane has no ARMED key in $CUR/config/n8n_effect_keys.json — serve the release with the PR first (a wrapped line would exit 65 and run nothing)."; exit 3; }
    read -r o ep <<<"$(owner_of "$lane")"
    echo "   $lane: key armed in CURRENT; owner now: $o (epoch $ep)"
    [[ "$o" == "none" || "$o" == "cron" ]] || { echo "REFUSED: $lane owner is '$o', not none/cron — this packet does not move a lane away from n8n."; exit 3; }
  done < "$WORK/plan.tsv"
fi

# ── preview 3: crontab diff ──────────────────────────────────────────────────────────────────────────────
cat > "$WORK/edit.py" <<'PYEOF'
import sys
live, plan, part, out = sys.argv[1:5]
lines = open(live, newline="").read().split("\n")
n = 0
for row in open(plan).read().splitlines():
    p, lane, old, new = row.split("\t")
    if p not in part: continue
    hits = [i for i, l in enumerate(lines) if l == old]
    if len(hits) != 1:
        if lines.count(new) == 1:
            print(f"   {lane}: already done", file=sys.stderr); continue
        sys.exit(f"REFUSED: {lane}: expected exactly 1 line equal to the current text, found {len(hits)}")
    lines[hits[0]] = new; n += 1
open(out, "w", newline="").write("\n".join(lines)); print(n)
PYEOF
N="$("$PY" "$WORK/edit.py" "$WORK/crontab.live" "$WORK/plan.tsv" "$PART" "$WORK/candidate")" || { rollback_hint; exit 3; }
echo "== crontab diff ($N line(s))"
diff "$WORK/crontab.live" "$WORK/candidate" || true
[[ "$(diff "$WORK/crontab.live" "$WORK/candidate" | grep -c '^[<>]')" == "$((N * 2))" ]] || { echo "REFUSED: diff is not exactly $N line(s)"; exit 3; }
if [[ "$PART" == *B* ]]; then
  echo "== owner rows that will be created/kept (Part B), before the lines are wrapped:"
  while IFS=$'\t' read -r p lane _o _n; do [[ "$p" == "B" ]] && echo "   effect_claim.py set-owner --process $lane --owner cron --by operator:double-run-20261022"; done < "$WORK/plan.tsv"
fi
[[ $PREVIEW == 1 ]] && { echo "PREVIEW ONLY — nothing changed. Backup kept at $BACKUP"; exit 0; }
[[ "$N" -gt 0 ]] || { echo "Nothing to change."; exit 0; }
read -r -p "Type APPLY to apply part(s) $PART: " answer
[[ "$answer" == "APPLY" ]] || { echo "Not confirmed — nothing changed."; exit 0; }

# ── apply: owner rows first (Part B), then the crontab, with read-back ───────────────────────────────────
if [[ "$PART" == *B* ]]; then
  while IFS=$'\t' read -r p lane _o _n; do
    [[ "$p" == "B" ]] || continue
    read -r o ep <<<"$(owner_of "$lane")"
    if [[ "$o" == "cron" ]]; then echo "   $lane already owner cron (epoch $ep)"; continue; fi
    ARGS=(set-owner --process "$lane" --owner cron --by "operator:double-run-20261022" --note "double-run fix 2026-10-22: cron owns the slot")
    [[ "$ep" != "none" ]] && ARGS+=(--expect-epoch "$ep")
    "$PY" "$CUR/scripts/lib/effect_claim.py" "${ARGS[@]}" || { echo "FAILED: set-owner $lane — crontab not changed"; exit 5; }
    read -r o2 ep2 <<<"$(owner_of "$lane")"
    [[ "$o2" == "cron" ]] || { echo "FAILED: $lane owner reads '$o2' after set-owner — crontab not changed"; exit 5; }
    echo "   $lane owner cron (epoch $ep2). Undo: effect_claim.py set-owner --process $lane --owner $o --expect-epoch $ep2 (if $o is not none)"
  done < "$WORK/plan.tsv"
fi
crontab -l | cmp -s - "$WORK/crontab.live" || { echo "REFUSED: the crontab changed since the preview; re-run."; exit 5; }
crontab - < "$WORK/candidate" || { echo "FAILED: install"; rollback_hint; exit 5; }
crontab -l | cmp -s - "$WORK/candidate" || { echo "FAILED: read-back differs"; rollback_hint; exit 5; }
while IFS=$'\t' read -r p lane _o new; do
  [[ "$PART" == *"$p"* ]] || continue
  crontab -l | grep -qxF -- "$new" || { echo "FAILED: $lane line not as expected after install"; rollback_hint; exit 5; }
  echo "   [$p] $lane verified (crontab -l)"
done < "$WORK/plan.tsv"
echo "DONE. Backup: $BACKUP   Rollback (crontab): crontab \"$BACKUP\""
echo "Next (agent PR): Part A rows -> scheduler stage cutover with effect_ownership n8n; Part B rows -> scheduler.command_text = the wrapped line."
