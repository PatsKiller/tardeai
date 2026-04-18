#!/usr/bin/env python3
"""
Orchestrator cost basis patch + additional Phase 1 fixes
Fixes not covered by phase1_fix.py:
1. Orchestrator: inject cost basis computation after load_all_portfolios
2. Weekly report: add WEEKLY_SERVE_DIR copy after HTML save (corrected placement)
3. Fix qwen3:14b references in weekly report labels
"""
import ast
from pathlib import Path

root = Path('.')
ok = []
fail = []

# ═══════════════════════════════════════════════════════════
# FIX A: Orchestrator — cost basis from transactions
# ═══════════════════════════════════════════════════════════
path = root / 'scripts/portfolio_orchestrator.py'
c = path.read_text()

old = '''    portfolio = load_all_portfolios(str(root))
    portfolio = reprice_portfolio(portfolio, state_dir)
    save_state(portfolio, str(root))'''

new = '''    portfolio = load_all_portfolios(str(root))
    portfolio = reprice_portfolio(portfolio, state_dir)
    # Compute cost basis from transaction history
    try:
        from collections import defaultdict as _dd
        journal   = portfolio.get("trade_journal", [])
        holdings  = portfolio.get("holdings", [])
        if journal and holdings:
            cb = _dd(lambda: {"cost": 0.0, "shares": 0.0})
            for tx in journal:
                act = tx.get("action","").upper()
                if act not in ("BUY","REINVEST","REINVEST SHARES","REINVEST DIVIDEND"):
                    continue
                sym   = tx.get("symbol","").upper()
                acct  = tx.get("account","")
                qty   = abs(tx.get("quantity",0) or 0)
                price = abs(tx.get("price",0) or 0)
                if sym and qty > 0 and price > 0:
                    cb[f"{acct}|{sym}"]["cost"]   += qty * price
                    cb[f"{acct}|{sym}"]["shares"]  += qty
            upd = 0
            for h in holdings:
                key = f"{h.get('account','')}|{h.get('symbol','').upper()}"
                if key in cb and cb[key]["cost"] > 0:
                    h["cost_basis"] = round(cb[key]["cost"], 2)
                    mv = h.get("market_value", 0) or 0
                    h["gain_loss"] = round(mv - h["cost_basis"], 2)
                    h["gain_loss_pct"] = round(
                        (mv - h["cost_basis"]) / h["cost_basis"] * 100, 2
                    ) if h["cost_basis"] > 0 else 0
                    upd += 1
            if upd:
                tc = sum(h.get("cost_basis",0) or 0 for h in holdings)
                tv = portfolio.get("portfolio_totals",{}).get("total_value",0)
                pt = portfolio.setdefault("portfolio_totals",{})
                pt["total_cost"]      = round(tc, 2)
                pt["total_gain"]      = round(tv - tc, 2)
                pt["total_gain_pct"]  = round((tv - tc) / tc * 100, 2) if tc > 0 else 0
                print(f"  [loader] Cost basis: {upd}/{len(holdings)} holdings computed")
    except Exception as _e:
        print(f"  [loader] Cost basis warning: {_e}")
    save_state(portfolio, str(root))'''

if old in c:
    c = c.replace(old, new)
    path.write_text(c)
    ok.append("Fix A: Cost basis injection in orchestrator")
else:
    fail.append("Fix A: orchestrator marker not found")

# ═══════════════════════════════════════════════════════════
# FIX B: Weekly report — fix WEEKLY_SERVE_DIR placement
# and copy HTML to reports/weekly/ after save
# ═══════════════════════════════════════════════════════════
path = root / 'scripts/portfolio_weekly_report.py'
c = path.read_text()

# Fix 14b labels
c = c.replace('qwen3:14b', 'qwen3:1.7b')

# Fix WEEKLY_SERVE_DIR if it's misplaced (inside function)
bad = '''    WEEKLY_DIR = PROJECT_ROOT / "data" / "portfolios" / "reports" / "weekly"
WEEKLY_SERVE_DIR = PROJECT_ROOT / "reports" / "weekly"  # served by portfolio_server.py
    WEEKLY_DIR.mkdir(parents=True, exist_ok=True)'''
good = '''    WEEKLY_DIR = PROJECT_ROOT / "data" / "portfolios" / "reports" / "weekly"
    WEEKLY_DIR.mkdir(parents=True, exist_ok=True)'''
if bad in c:
    c = c.replace(bad, good)
    ok.append("Fix B1: WEEKLY_SERVE_DIR misplacement fixed")

# Add copy to reports/weekly/ after DOCX save
old_docx_save = '    print(f"[weekly-report] DOCX saved: {docx_path}")'
new_docx_save = '''    print(f"[weekly-report] DOCX saved: {docx_path}")
    # Copy both HTML and DOCX to reports/weekly/ so server can serve them
    try:
        import shutil as _sh
        _sv = PROJECT_ROOT / "reports" / "weekly"
        _sv.mkdir(parents=True, exist_ok=True)
        _sh.copy2(html_path, _sv / html_path.name)
        _sh.copy2(docx_path, _sv / docx_path.name)
        print(f"[weekly-report] Copied to reports/weekly/ for serving")
    except Exception as _e:
        print(f"[weekly-report] Copy warning: {_e}")'''

if old_docx_save in c and 'Copy both HTML and DOCX' not in c:
    c = c.replace(old_docx_save, new_docx_save)
    ok.append("Fix B2: Weekly reports copied to reports/weekly/")
else:
    fail.append("Fix B2: docx save marker not found or already patched")

path.write_text(c)

# ═══════════════════════════════════════════════════════════
# FIX C: Validate all patched files
# ═══════════════════════════════════════════════════════════
for f in ['scripts/portfolio_orchestrator.py',
          'scripts/portfolio_weekly_report.py',
          'scripts/portfolio_server.py',
          'scripts/portfolio_performance_history.py']:
    try:
        ast.parse((root/f).read_text())
        ok.append(f"✅ Syntax OK: {f}")
    except SyntaxError as e:
        fail.append(f"❌ SYNTAX ERROR {f}: {e}")

# ═══════════════════════════════════════════════════════════
# REPORT
# ═══════════════════════════════════════════════════════════
print("\n" + "="*60)
print("PHASE 1B FIX RESULTS")
print("="*60)
for msg in ok:   print(f"  ✅ {msg}")
for msg in fail: print(f"  ❌ {msg}")
print(f"\n{len(ok)} OK, {len(fail)} failed")
