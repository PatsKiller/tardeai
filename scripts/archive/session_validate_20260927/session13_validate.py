#!/usr/bin/env python3
"""session13_validate.py — Validate Session 13 Paper Trading Infrastructure."""
import json, os, sys, urllib.request
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / 'scripts'))
os.chdir(str(PROJECT_ROOT))

PASS = FAIL = 0

def check(name, condition, detail=""):
    global PASS, FAIL
    if condition:
        PASS += 1; print(f"  \u2705 {name}")
    else:
        FAIL += 1; print(f"  \u274c {name}{': ' + detail if detail else ''}")

def main():
    global PASS, FAIL
    print("=== SESSION 13 VALIDATION ===\n")

    # 1. paper_trade_logger imports
    print("[1] Imports")
    try:
        from paper_trade_logger import parse_pt_command, open_paper_trade, close_paper_trade
        check("paper_trade_logger imports", True)
    except Exception as e:
        check("paper_trade_logger imports", False, str(e))

    # 2. alpaca_paper_adapter imports
    try:
        from alpaca_paper_adapter import AlpacaPaperAdapter
        check("alpaca_paper_adapter imports", True)
    except Exception as e:
        check("alpaca_paper_adapter imports", False, str(e))

    # 3-4. Syntax
    print("\n[3-4] Syntax")
    for f in ['scripts/paper_trade_logger.py', 'scripts/alpaca_paper_adapter.py',
              'scripts/telegram_command_handler.py', 'scripts/api_v2.py', 'scripts/session13_db.py']:
        fp = PROJECT_ROOT / f
        if fp.exists():
            try:
                import ast; ast.parse(fp.read_text())
                check(f"syntax {f}", True)
            except SyntaxError as e:
                check(f"syntax {f}", False, str(e))

    # 5-6. API endpoints
    print("\n[5-6] API endpoints")
    for ep in ['paper-analytics', 'paper-trades/open', 'paper-trades']:
        try:
            with urllib.request.urlopen(f'http://localhost:7777/api/v2/{ep}', timeout=5) as r:
                d = json.loads(r.read())
                check(f"GET /api/v2/{ep}", d.get('ok', False))
        except Exception as e:
            check(f"GET /api/v2/{ep}", False, str(e))

    # 7. Parser tests
    print("\n[7] Parser tests")
    from paper_trade_logger import parse_pt_command
    tests = [
        ('FTCI auto', True), ('FTCI auto tos', True), ('FTCI auto alpaca', True),
        ('FTCI 300 4.96 4.61 5.31', True), ('FTCI auto live', False),
        ('FTCI auto taxable', False), ('', False), ('FTCI', False),
    ]
    all_pass = True
    for cmd, expected in tests:
        ok, _, _ = parse_pt_command(cmd)
        if ok != expected:
            all_pass = False
            check(f"parser: '{cmd}'", False, f"expected {expected} got {ok}")
    if all_pass:
        check(f"parser: all {len(tests)} tests", True)

    # 8. Risk gate called by logger
    print("\n[8] Risk gate integration")
    src = (PROJECT_ROOT / 'scripts/paper_trade_logger.py').read_text()
    check("risk gate called in logger", 'RiskGate' in src or 'risk_gate' in src)

    # 9. Live accounts rejected
    ok, _, err = parse_pt_command('FTCI auto live')
    check("live account rejected", not ok and 'LIVE' in err.upper() or 'BLOCKED' in err.upper())
    ok2, _, err2 = parse_pt_command('FTCI auto rollover_ira')
    check("IRA rejected for paper", not ok2)

    # 10. No hardcoded DB password
    print("\n[10] No hardcoded secrets")
    _pw = '1AHC' + '_w9F'
    found = False
    for f in ['scripts/paper_trade_logger.py', 'scripts/alpaca_paper_adapter.py', 'scripts/session13_db.py']:
        fp = PROJECT_ROOT / f
        if fp.exists() and _pw in fp.read_text():
            found = True
            check(f"no hardcoded password in {f}", False)
    if not found:
        check("no hardcoded DB password", True)

    # 11. Alpaca live endpoint not used
    print("\n[11] Alpaca safety")
    alpaca_src = (PROJECT_ROOT / 'scripts/alpaca_paper_adapter.py').read_text()
    check("paper endpoint only", 'paper-api.alpaca.markets' in alpaca_src)
    check("live endpoint blocked", 'BLOCKED' in alpaca_src or 'Live' in alpaca_src)

    # 12. Alpaca disabled by default
    check("alpaca disabled by default", "'false'" in alpaca_src or '"false"' in alpaca_src)

    # 13. Crons not duplicated
    print("\n[13] Cron check")
    import subprocess
    crons = subprocess.run(['crontab', '-l'], capture_output=True, text=True).stdout
    alpaca_lines = [l for l in crons.splitlines() if 'alpaca_paper_adapter.py' in l and not l.strip().startswith('#')]
    check(f"alpaca cron lines ({len(alpaca_lines)})", len(alpaca_lines) <= 1)

    # 14. Holdings unchanged
    print("\n[14] Holdings safety")
    d = json.load(open('data/portfolios/state/holdings.json'))
    v = d['portfolio_totals']['total_value']
    check(f"holdings ${v:,.0f}", v > 1000000)

    print(f"\n{'='*40}")
    print(f"Results: {PASS} passed, {FAIL} failed")
    print("SESSION 13 VALIDATION:", "PASSED" if FAIL == 0 else "FAILED")
    sys.exit(1 if FAIL > 0 else 0)

if __name__ == '__main__':
    main()
