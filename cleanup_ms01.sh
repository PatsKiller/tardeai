#!/usr/bin/env bash
set -euo pipefail
ROOT="$(pwd)"
LOG="$ROOT/logs/cleanup_$(date +%Y%m%d_%H%M%S).log"
echo "=============================================="
echo " Trade AI v12 — Forensic Cleanup Script"
echo " Root: $ROOT"
echo "=============================================="
echo "[SAFETY] Verifying holdings.json..."
TOTAL=$(python3 -c "import json; d=json.load(open('data/portfolios/state/holdings.json')); print(d.get('portfolio_totals',{}).get('total_value',0))" 2>/dev/null || echo "0")
echo "[SAFETY] Portfolio total: \$$TOTAL"
python3 -c "exit(0 if float('$TOTAL') > 100000 else 1)" || { echo "ABORT — invalid total"; exit 1; }
echo "[SAFETY] ✅ OK"
DRY_RUN=false
[[ "${1:-}" == "--dry-run" ]] && DRY_RUN=true && echo "[DRY RUN MODE]"
rm_safe() { local t="$1"; [[ -e "$t" ]] && { [[ "$DRY_RUN" == "true" ]] && echo "  WOULD DELETE: $t" || { rm -rf "$t"; echo "  DELETED: $t" | tee -a "$LOG"; }; }; }
mkdir -p logs
echo "=== Cleanup started: $(date) ===" | tee -a "$LOG"
echo "[1] Root patch scripts..."
for f in patch_acct_periods.py patch_catalyst_brave.py patch_continuous_runner.py patch_scoring_ollama.py command_center_linux_v2_patch.py portfolio_server_linux_v2_patch.py fix_cash_card.py "portfolio_loader.py" "portfolio_performance_history.py" "portfolio_server.py.REMOVED_DUPE" backfill_acct_periods.py backfill_acct_periods_v2.py audit1.txt audit2.txt SKILL.md trades_sample.csv env_manager.html "data/state.json"; do rm_safe "$f"; done
echo "[2] Script .bak files..."
for f in scripts/portfolio_server.py.bak-20260415-205105 scripts/portfolio_server.py.bak-linux-v2 scripts/portfolio_server.py.bak-reprice scripts/portfolio_server_backup.py scripts/portfolio_server_v2.py scripts/portfolio_loader.py.bak_autodetect scripts/catalyst_enrichment.py.bak_fmp_fix scripts/economic_calendar.py.bak_fmp_fix scripts/market_context.py.bak_fmp_fix "scripts/portfolio_technical.py.bak_finviz_cols" "scripts/portfolio_technical.py.bak_guard" scripts/trade_ai_health.py.bak_fmp scripts/apply_loader_patch.py scripts/tradeai_state_debug.py; do rm_safe "$f"; done
echo "[3] Old CC iterations..."
rm_safe "reports/command_center.html.bak"
find reports/ -name "command_center.html.bak*" -delete 2>/dev/null | true
find reports/ -name "command_center_reset_baseline_fix*.html" -delete 2>/dev/null | true
find reports/ -name "command_center_v2_phase*.html" -delete 2>/dev/null | true
for f in "reports/command_center_redesign_v2.html" "reports/command_center_v41.html" "reports/command_center_v42.html" "reports/command_center_v43.html" "reports/command_center.zip" "reports/HTML pre grok backup.zip" "reports/yaml_advisor_scripts.zip"; do rm_safe "$f"; done
echo "[4] Sandbox cleanup..."
rm_safe "sandbox/old_cc"
rm_safe "sandbox/old_inputs"
rm_safe "sandbox/archive_2026-04-13/root_debug"
rm_safe "sandbox/archive_2026-04-13/root_legacy"
rm_safe "sandbox/archive_2026-04-13/root_zips"
rm_safe "sandbox/archive_2026-04-13/patch_backups"
rm_safe "sandbox/deploy_zips"
echo "[5] file_backups/..."
rm_safe "file_backups"
echo "[6] Raw snapshots (regeneratable)..."
rm_safe "data/portfolios/state/raw_snapshots"
rm_safe "data/portfolios/state/ticker_snapshot_history"
rm_safe "data/portfolios/state/data"
echo "[7] Windows launchers..."
rm_safe "launchers"
rm_safe "tradeai_fix"
find . -maxdepth 1 -name "*.bat" -delete 2>/dev/null | true
echo "[8] linux_port v1..."
rm_safe "linux_port"
rm_safe "linux_launchers/run_portfolio_monthly_lite.sh"
rm_safe "linux_launchers/run_portfolio_monthly_full.sh"
echo "[9] OpenClaw reset sessions..."
find ~/.openclaw/agents/main/sessions/ -name "*.reset.*" -delete 2>/dev/null | true
echo "[10] Old catalyst cache (keep last 3)..."
ls -t data/catalyst_cache_*.json 2>/dev/null | tail -n +4 | xargs rm -f 2>/dev/null | true
echo "[11] Docs cruft..."
rm_safe "docs/SKILL.md"; rm_safe "docs/SKILL_updated.md"; rm_safe "docs/command_center.html"
echo ""
echo "=============================================="
[[ "$DRY_RUN" == "true" ]] && echo "DRY RUN DONE — nothing deleted" || echo "CLEANUP COMPLETE — Log: $LOG"
python3 -c "import json; d=json.load(open('data/portfolios/state/holdings.json')); print(f'✅ Portfolio: \${d[\"portfolio_totals\"][\"total_value\"]:,.0f} | Holdings: {len(d[\"holdings\"])}')"
echo "=============================================="
