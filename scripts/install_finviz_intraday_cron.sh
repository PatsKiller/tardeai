#!/usr/bin/env bash
# Install the Finviz portfolio repricer: every 15 min, 24/7 (operator 2026-11-07: a stored price older than ~30 min
# must be refreshed; the Finviz API works any time of day, weekends included). Replaces the BEGIN/END
# finviz-intraday-repricer block in place; never touches the 16:10 post-close line (holdings_reconcile chain).
# Default = DRY RUN (prints the before/after block). --apply writes: crontab backup first, then one write, then a read-back.
set -euo pipefail
APPLY=0; [ "${1:-}" = "--apply" ] && APPLY=1
PROJ="${TRADEAI_RELEASES_ROOT:-$HOME/trade-ai-releases}/portfolio-server/CURRENT"
BEGIN="# BEGIN finviz-intraday-repricer"; END="# END finviz-intraday-repricer"
LINE='*/15 * * * * cd '"$PROJ"' && bash '"$PROJ"'/scripts/safe_flock.sh /tmp/portfolio_repricer.lock $PY scripts/portfolio_repricer.py >> '"$PROJ"'/logs/portfolio_repricer_intraday.log 2>&1'
CUR=$(crontab -l 2>/dev/null)
grep -qF "$BEGIN" <<<"$CUR" || { echo "REFUSED: no '$BEGIN' block in the crontab; nothing changed" >&2; exit 2; }
NEW=$(awk -v b="$BEGIN" -v e="$END" -v l="$LINE" '
  $0==b {print; print "# 2026-11-07 operator: 30-min stale rule -> every 15 min, 24/7 (was */15 * * * 1-5 + */15 20-23 * * 0)"; print l; skip=1; next}
  $0==e {skip=0; print; next}
  !skip {print}' <<<"$CUR")
echo "--- current block"; awk -v b="$BEGIN" -v e="$END" '$0==b{p=1} p{print} $0==e{p=0}' <<<"$CUR"
echo "--- new block";     awk -v b="$BEGIN" -v e="$END" '$0==b{p=1} p{print} $0==e{p=0}' <<<"$NEW"
echo "--- lines outside the block unchanged: $( [ "$(awk -v b="$BEGIN" -v e="$END" '$0==b{s=1} !s{print} $0==e{s=0}' <<<"$CUR")" = "$(awk -v b="$BEGIN" -v e="$END" '$0==b{s=1} !s{print} $0==e{s=0}' <<<"$NEW")" ] && echo yes || echo NO)"
if [ "$APPLY" = 1 ]; then
  BK="$HOME/trade-ai-releases/persistent-state/data/runtime/crontab_backup_repricer_$(date +%Y%m%d_%H%M%S).txt"
  printf '%s\n' "$CUR" > "$BK"; echo "backup: $BK"
  printf '%s\n' "$NEW" | crontab -
  echo "--- read-back"; crontab -l | awk -v b="$BEGIN" -v e="$END" '$0==b{p=1} p{print} $0==e{p=0}'
else
  echo "DRY RUN — re-run with --apply to write the crontab"
fi
