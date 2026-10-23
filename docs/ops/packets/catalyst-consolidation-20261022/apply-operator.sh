#!/usr/bin/env bash
# apply-operator.sh — OPERATOR-RUN. Applies the cron side of the 2026-10-11 B8 consolidation (lane
# catalyst-momentum-engine) that was never installed. Prepared 2026-10-22 by an agent; the agent never runs it.
#
# Why: config/lane_registry.json declares catalyst-momentum-engine ACTIVE (run_family_slot.py, B8) and the two legacy
# lines (-premarket, -market) RETIRED, but the crontab still runs the legacy lines and has no family line, so
# check_registry_runtime_truth reports ACTIVE_CRON_LINE_ABSENT + 2x DECLARED_OFF_CRON_LINE_ACTIVE and the Ops →
# Controls Jobs page lists all three under "Needs attention".
#
# What it does (exact text, never line numbers):
#   1. comments the two legacy lines as "# RETIRED 2026-10-22 b-family B8/catalyst-momentum-engine <line>"
#   2. inserts the two family lines right after the first retired one (scripts/run_family_slot.py --print-crontab)
#   The overnight line (--band overnight) is NOT touched (its own D3 shadow lane).
#
# Preconditions (refuses otherwise): the served CURRENT has run_family_slot.py with the catalyst family AND its
# proposal modes carry `env ALPACA_MODE=paper` (the legacy lines do; installing without it would drop the paper guard).
#
# Usage:
#   bash apply-operator.sh            # preconditions, backup, diff preview, ONE "APPLY" prompt, install, verify
#   bash apply-operator.sh --preview  # preconditions + diff; changes nothing
# Rollback at any point: crontab "$BACKUP"   (the backup is never deleted)
set -euo pipefail
PREVIEW=0
case "${1:-}" in --preview) PREVIEW=1 ;; "") ;; *) echo "usage: $0 [--preview]"; exit 2 ;; esac
CUR="${TRADEAI_CURRENT:-$HOME/trade-ai-releases/portfolio-server/CURRENT}"
PY="${TRADEAI_PY:-$HOME/trade-ai-v12-rebuild/trade-ai-v12-rebuild/.venv/bin/python}"
TS="$(date -u +%Y%m%dT%H%M%SZ)"
WORK="${TRADEAI_PACKET_WORK:-$HOME/.cache/catalyst-consolidation-$TS}"
mkdir -p "$WORK"
BACKUP="$WORK/crontab.bak"

LEGACY_PRE='*/30 4-9 * * 1-5 cd $PROJ && env ALPACA_MODE=paper bash $PROJ/scripts/safe_flock.sh /tmp/catalyst_premarket.lock $PY scripts/catalyst_momentum_engine.py --band premarket_scalp --apply --generate-proposals >> logs/catalyst_momentum_engine.log 2>&1'
LEGACY_MKT='30 9-15 * * 1-5 cd $PROJ && env ALPACA_MODE=paper bash $PROJ/scripts/safe_flock.sh /tmp/catalyst_swing.lock $PY scripts/catalyst_momentum_engine.py --band market_swing --apply --generate-proposals >> logs/catalyst_momentum_engine.log 2>&1'
RETIRE_PFX='# RETIRED 2026-10-22 b-family B8/catalyst-momentum-engine '

echo "== preconditions"
[[ -f "$CUR/scripts/run_family_slot.py" ]] || { echo "REFUSED: $CUR does not serve scripts/run_family_slot.py"; exit 3; }
"$PY" "$CUR/scripts/run_family_slot.py" --family catalyst-momentum-engine --print-crontab > "$WORK/family.lines"
[[ "$(grep -c . "$WORK/family.lines")" == 2 ]] || { echo "REFUSED: expected 2 family crontab lines"; cat "$WORK/family.lines"; exit 3; }
for m in premarket_scalp market_swing; do
  (cd "$CUR" && "$PY" scripts/run_family_slot.py --family catalyst-momentum-engine --mode "$m" --dry-run --project-root "$CUR") > "$WORK/dry.$m" 2>&1
  grep -qF "env ALPACA_MODE=paper" "$WORK/dry.$m" || { echo "REFUSED: served family mode $m lacks env ALPACA_MODE=paper (release the PR first)"; exit 3; }
done
echo "   served family lines:"; sed 's/^/     /' "$WORK/family.lines"

crontab -l > "$BACKUP"
echo "== backup: $BACKUP ($(wc -l < "$BACKUP") lines)"

"$PY" - "$BACKUP" "$WORK/family.lines" "$WORK/crontab.new" "$LEGACY_PRE" "$LEGACY_MKT" "$RETIRE_PFX" <<'PYEOF'
import sys
live, fam, out, pre, mkt, pfx = sys.argv[1:7]
lines = open(live, newline="").read().split("\n")
family = [l for l in open(fam).read().split("\n") if l.strip()]
for want in (pre, mkt):
    n = sum(1 for l in lines if l == want)
    if n != 1:
        sys.exit(f"REFUSED: expected exactly 1 active line equal to:\n  {want}\nfound {n}")
for f in family:
    if any(l == f for l in lines):
        sys.exit(f"REFUSED: a family line is already installed:\n  {f}")
i = lines.index(pre)
lines[i] = pfx + pre
lines[i + 1:i + 1] = family
j = lines.index(mkt)
lines[j] = pfx + mkt
open(out, "w", newline="").write("\n".join(lines))
PYEOF
echo "== crontab diff"
diff "$BACKUP" "$WORK/crontab.new" || true
if [[ $PREVIEW == 1 ]]; then echo "PREVIEW ONLY — crontab unchanged. Backup kept at $BACKUP"; exit 0; fi

read -r -p "Type APPLY to install this crontab: " ans
[[ "$ans" == "APPLY" ]] || { echo "Not confirmed — crontab unchanged. Backup kept at $BACKUP"; exit 1; }
crontab - < "$WORK/crontab.new"
# Verify against a CAPTURED file: no `crontab -l | grep -q` under pipefail (SIGPIPE false failures, 2026-10-22).
crontab -l > "$WORK/crontab.installed"
fail=0
cmp -s "$WORK/crontab.installed" "$WORK/crontab.new" || { echo "FAILED: installed crontab differs from the planned one"; fail=1; }
grep -qxF -- "$RETIRE_PFX$LEGACY_PRE" "$WORK/crontab.installed" || { echo "FAILED: premarket line not retired"; fail=1; }
grep -qxF -- "$RETIRE_PFX$LEGACY_MKT" "$WORK/crontab.installed" || { echo "FAILED: market line not retired"; fail=1; }
while IFS= read -r f; do [[ -n "$f" ]] && { grep -qxF -- "$f" "$WORK/crontab.installed" || { echo "FAILED: family line missing: $f"; fail=1; }; }; done < "$WORK/family.lines"
if [[ $fail != 0 ]]; then echo "ROLLBACK: crontab \"$BACKUP\""; exit 5; fi
echo "APPLIED and verified. Rollback: crontab \"$BACKUP\""
