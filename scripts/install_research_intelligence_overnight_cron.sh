#!/usr/bin/env bash
# Install / refresh Research Intelligence overnight cron block.
# Idempotent: replaces only the marked RI overnight section.
set -euo pipefail
PROJ="$(cd "$(dirname "$0")/.." && pwd)"
MARKER_BEGIN="# BEGIN research-intelligence-overnight"
MARKER_END="# END research-intelligence-overnight"
PY="$PROJ/.venv/bin/python"
GATE="$PROJ/scripts/non_trading_hours_gate.sh"
OVERNIGHT="$PROJ/scripts/run_research_intelligence_overnight.sh"

chmod +x "$GATE" "$OVERNIGHT" "$0"

BLOCK=$(cat <<EOF
$MARKER_BEGIN
# Research Intelligence — content updates OUTSIDE RTH only (overnight / after close).
# Desk UI still serves GET /api/v2/research-intelligence 24/7 from DB + cache.
# Gate skips regular+premarket so trading CPU/GPU is not stolen mid-session.
30 20 * * 1-5 cd $PROJ && bash $GATE bash $OVERNIGHT --phase full >> $PROJ/logs/ri_overnight.log 2>&1
15 2 * * * cd $PROJ && bash $GATE bash $OVERNIGHT --phase full >> $PROJ/logs/ri_overnight.log 2>&1
15 5 * * * cd $PROJ && bash $GATE bash $OVERNIGHT --phase archive >> $PROJ/logs/ri_overnight.log 2>&1
# Hourly topic synth — gated: no-op during regular/premarket
20 * * * * cd $PROJ && bash $GATE bash -c 'bash $PROJ/scripts/llm_priority_guard.sh && flock -n /tmp/topic_synth.lock $PY scripts/topic_research_synthesizer.py --max 15 --apply' >> $PROJ/logs/topic_research_synth.log 2>&1
# Topic crawl + reground: after-close / overnight only (was 09:00/13:00/14:50 mid-day)
45 20 * * 1-5 cd $PROJ && bash $GATE timeout 30m $PY scripts/topic_ingestion.py --use-llm-queries --max-topics 14 >> $PROJ/logs/topic_ingestion.log 2>&1
45 2 * * * cd $PROJ && bash $GATE timeout 30m $PY scripts/topic_ingestion.py --use-llm-queries --max-topics 14 >> $PROJ/logs/topic_ingestion.log 2>&1
50 21 * * * cd $PROJ && bash $GATE flock -n /tmp/topic_reground.lock $PY scripts/topic_research_synthesizer.py --reground --max 20 --apply >> $PROJ/logs/topic_research_synth.log 2>&1
$MARKER_END
EOF
)

TMP=$(mktemp)
crontab -l 2>/dev/null | sed "/$MARKER_BEGIN/,/$MARKER_END/d" >"$TMP" || true
# Drop legacy unguarded RI-producing mid-day lines (replaced by gated block above)
grep -vE 'topic_synth\.lock.*topic_research_synthesizer\.py --max 15 --apply' "$TMP" \
  | grep -vE 'topic_ingestion\.py --use-llm-queries --max-topics 14' \
  | grep -vE 'topic_research_synthesizer\.py --reground --max 20 --apply' \
  >"${TMP}.2" || true
mv "${TMP}.2" "$TMP"
echo "" >>"$TMP"
echo "$BLOCK" >>"$TMP"
crontab "$TMP"
rm -f "$TMP"
echo "[install] Research Intelligence overnight cron installed."
crontab -l | sed -n "/$MARKER_BEGIN/,/$MARKER_END/p"
