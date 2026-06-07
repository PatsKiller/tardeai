#!/bin/bash
# Phase 206 — Profit-capture evidence refresh (EVIDENCE / SHADOW ONLY).
#
# Re-runs the canonical profit-capture + path-measured rule-backtest chain so that as more
# independent winning trades accumulate, reliable_sample_size climbs toward the evidence floor
# (n>=20). Until the floor is met every rule/family stays DO_NOT_GRAFT — this script NEVER grafts.
#
# NONE of these steps place/modify/cancel orders, move stops, or touch GO/WAIT/strategy/thresholds/
# live trading. yfinance is read-only market data. Paper-only. Safe to run unattended.
set -uo pipefail
PROJ="/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild"
PY="$PROJ/.venv/bin/python"
cd "$PROJ" || exit 1
LOG="$PROJ/logs/profit_capture_refresh.log"
ART="$PROJ/docs/_generated/profit_capture"   # rolling artifact set; git history is the dated trail
STAMP="$(date -u +%Y%m%d_%H%M)"
DAY="$(date -u +%Y%m%d)"
mkdir -p "$PROJ/logs" "$ART"
ts() { date -u '+%Y-%m-%d %H:%M:%S UTC'; }
run() { echo "[$(ts)] >>> $1" >> "$LOG"; eval "$PY scripts/$2" >> "$LOG" 2>&1 \
        || echo "[$(ts)] WARN $1 rc=$?" >> "$LOG"; }

echo "[$(ts)] === profit-capture refresh start ($STAMP) ===" >> "$LOG"

# 1) refresh the canonical all-trades measurable set (picks up newly closed trades + fresh MFE)
run "analyze"  "analyze_profit_capture_all_trades.py --apply --json $ART/pc_refresh.json --markdown $ART/pc_refresh.md"

# 2) ingest real intrabar paths (1m where it fully covers the window, else 5m) for measurable trades
run "ingest"   "ingest_trade_intrabar_bars.py --apply --fine --all-closed"

# 3) re-run the quality-gated, winners-only, path-measured rule backtest (date-stamped snapshot)
run "backtest" "backtest_profit_protection_rules.py --apply --quality-gated --winners-only \
   --min-bars-analyzed 10 --max-mfe-r 20 --require-planned-stop --run-id ppbt_auto_$DAY \
   --json $ART/pc_bt.json --markdown $ART/pc_bt.md"

# 4) refresh shadow threshold recommendations (advisory only; keys off reliable_n)
run "shadow"   "profit_protection_shadow_thresholds.py --apply --run-id ppsr_auto_$DAY \
   --json $ART/pc_shadow.json --markdown $ART/pc_shadow.md"

# 5) validate the enhancement (logs PASS/FAIL; never mutates)
run "validate" "validate_profit_capture_rule_quality.py --json $ART/pc_val.json --markdown $ART/pc_val.md"

# 6) log the headline: max reliable_n this run + floor distance (so the operator can watch it climb)
PGPASSWORD="$(grep '^DB_PASSWORD=' "$PROJ/.env" | cut -d= -f2)" \
  psql -h localhost -U trade_ai -d trade_ai -tAc \
  "SELECT 'reliable_n='||coalesce(max(reliable_sample_size),0)||' / floor 20 ; verdicts='||
          string_agg(DISTINCT graft_verdict,',')
   FROM profit_protection_rule_backtests WHERE run_id='ppbt_auto_$DAY'" \
  >> "$LOG" 2>&1 || echo "[$(ts)] WARN reliable_n query failed" >> "$LOG"

# 7) commit + push ONLY when the SUBSTANTIVE signal changes — the per-rule (reliable_n + graft
#    verdict) signature — not on cosmetic timestamp-only regen. When unchanged, revert the
#    regenerated (rolling) artifacts so git AND the Drive sync stay quiet. Scoped to the artifact
#    path; best-effort (never fails the pipeline).
ART_REL="docs/_generated/profit_capture"
SIG_FILE="$PROJ/logs/profit_capture_last_signature.txt"
CUR_SIG="$(PGPASSWORD="$(grep '^DB_PASSWORD=' "$PROJ/.env" | cut -d= -f2)" \
  psql -h localhost -U trade_ai -d trade_ai -tAc \
  "SELECT md5(coalesce(string_agg(rule_name||':'||coalesce(reliable_sample_size,-1)||':'||graft_verdict,
                                   '|' ORDER BY rule_name), ''))
   FROM profit_protection_rule_backtests WHERE run_id='ppbt_auto_$DAY'" 2>>"$LOG" | tr -d '[:space:]')"
PREV_SIG="$(tr -d '[:space:]' < "$SIG_FILE" 2>/dev/null || true)"

if [ -n "$CUR_SIG" ] && [ "$CUR_SIG" = "$PREV_SIG" ]; then
  # reliable_n + verdicts unchanged -> discard the cosmetic regen; no commit, no Drive churn
  git -C "$PROJ" checkout -- "$ART_REL" >> "$LOG" 2>&1 || true
  echo "[$(ts)] reliable_n/verdicts unchanged (sig ${CUR_SIG:0:12}) — artifacts not committed" >> "$LOG"
else
  git -C "$PROJ" add "$ART_REL" >> "$LOG" 2>&1
  if git -C "$PROJ" diff --cached --quiet -- "$ART_REL" 2>/dev/null; then
    echo "[$(ts)] no artifact changes to commit" >> "$LOG"
  elif git -C "$PROJ" commit -q -m "chore(audit): profit-capture $DAY — reliable_n/verdicts changed" -- "$ART_REL" >> "$LOG" 2>&1; then
    [ -n "$CUR_SIG" ] && echo "$CUR_SIG" > "$SIG_FILE"
    echo "[$(ts)] artifacts committed ($DAY, sig ${CUR_SIG:0:12})" >> "$LOG"
    git -C "$PROJ" push >> "$LOG" 2>&1 \
      && echo "[$(ts)] artifacts pushed ($DAY)" >> "$LOG" \
      || echo "[$(ts)] WARN artifact push failed — committed locally, will push next run" >> "$LOG"
  else
    echo "[$(ts)] WARN artifact commit failed" >> "$LOG"
  fi
fi

echo "[$(ts)] === profit-capture refresh done ($STAMP) ===" >> "$LOG"
