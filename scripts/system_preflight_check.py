#!/usr/bin/env python3
"""system_preflight_check.py — Run before any code changes to verify system health.

Checks all critical systems and reports status. Run this:
1. BEFORE making changes (baseline)
2. AFTER making changes (verify nothing broke)
3. On any morning where alerts seem wrong

Usage:
    python3 scripts/system_preflight_check.py
"""
import json, os, sys, urllib.request
from datetime import datetime
from pathlib import Path
from finviz_http import finviz_get, finviz_probe  # global Finviz throttle (2026-07-20)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PASS = 0
FAIL = 0


def check(name, condition, detail=""):
    global PASS, FAIL
    if condition:
        PASS += 1
        print(f"  \u2705 {name}")
    else:
        FAIL += 1
        print(f"  \u274C {name}: {detail}")


def run():
    global PASS, FAIL
    print(f"=== System Preflight Check — {datetime.now().strftime('%Y-%m-%d %H:%M')} ===\n")

    # 1. Finviz cookie
    print("FINVIZ:")
    cookie = ""
    for line in (PROJECT_ROOT / ".env").read_text().splitlines():
        if line.startswith("FINVIZ_COOKIE="): cookie = line.split("=", 1)[1].strip().strip("'\"")

    check("FINVIZ_COOKIE exists", len(cookie) > 50, f"Only {len(cookie)} chars")
    check("Has .ASPXAUTH", ".ASPXAUTH=" in cookie, "Missing authentication token")
    check("Has .AspNetCore.Session", ".AspNetCore.Session=" in cookie, "Missing session")

    # Test actual download
    try:
        import requests
        url = "https://elite.finviz.com/export?v=152&f=cap_smallunder,sh_relvol_o5&ft=3"
        resp = finviz_probe(url, headers={"Cookie": cookie, "User-Agent": "Mozilla/5.0"})
        is_csv = "Ticker" in resp.text[:100]
        check("Finviz CSV download", is_csv, f"Got {resp.headers.get('Content-Type','?')} ({len(resp.text)} bytes)")
        if is_csv:
            rows = len(resp.text.strip().split("\n")) - 1
            check(f"Finviz returns tickers", rows > 0, "0 tickers returned")
    except Exception as e:
        check("Finviz download", False, str(e))

    # 2. Ollama
    print("\nOLLAMA:")
    try:
        from local_llm_config import get_local_llm_model, get_local_llm_base_url
        _model = get_local_llm_model()
        _base = get_local_llm_base_url().rstrip("/")
        payload = json.dumps({"model": _model, "stream": False, "prompt": "hi", "options": {"num_predict": 1}}).encode()
        req = urllib.request.Request(f"{_base}/api/generate", data=payload, headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=30) as resp:
            check(f"Ollama {_model} responds", True)
    except Exception as e:
        check("Ollama", False, str(e))

    # 3. Portfolio server
    print("\nPORTFOLIO SERVER:")
    for endpoint in ["/api/v2/overview", "/api/v2/tax-situation", "/api/v2/alex/recent"]:
        try:
            with urllib.request.urlopen(f"http://localhost:7777{endpoint}", timeout=5) as resp:
                data = json.loads(resp.read())
                check(f"API {endpoint}", data.get("ok", False), json.dumps(data)[:80])
        except Exception as e:
            check(f"API {endpoint}", False, str(e))

    # 4. Database
    print("\nDATABASE:")
    try:
        import psycopg2
        pw = ""
        for line in (PROJECT_ROOT / ".env").read_text().splitlines():
            if line.startswith("DB_PASSWORD="): pw = line.split("=", 1)[1].strip()
        conn = psycopg2.connect(host="localhost", dbname="trade_ai", user="trade_ai", password=pw)
        cur = conn.cursor()
        cur.execute("SELECT count(*) FROM information_schema.tables WHERE table_schema='public'")
        tables = cur.fetchone()[0]
        check(f"PostgreSQL ({tables} tables)", tables > 100)
        cur.execute("SELECT count(*) FROM news_articles")
        check(f"News articles ({cur.fetchone()[0]})", True)
        cur.execute("SELECT count(*) FROM watchlist_agent_results")
        check(f"Agent results ({cur.fetchone()[0]})", True)
        conn.close()
    except Exception as e:
        check("Database", False, str(e))

    # 5. Systemd services
    print("\nSERVICES:")
    import subprocess
    for svc in ["tradeai-continuous", "portfolio-server"]:
        r = subprocess.run(["systemctl", "--user", "is-active", f"{svc}.service"], capture_output=True, text=True)
        check(f"{svc} service", r.stdout.strip() == "active", r.stdout.strip())

    # 6. Key files
    print("\nSTATE FILES:")
    state = PROJECT_ROOT / "data" / "portfolios" / "state"
    for f in ["holdings.json", "ticker_enrichment_cache.json", "dividend_calendar.json"]:
        p = state / f
        if p.exists():
            age_h = (datetime.now().timestamp() - p.stat().st_mtime) / 3600
            check(f"{f} ({age_h:.1f}h old)", age_h < 24, f"{age_h:.1f}h stale")
        else:
            check(f, False, "MISSING")

    # 7. Screener config
    print("\nSCREENER CONFIG:")
    try:
        import yaml
        cfg = yaml.safe_load((PROJECT_ROOT / "assets" / "screeners.yaml").read_text())
        urls = []
        for name, s in cfg.get("screeners", {}).items():
            u = s.get("finviz_url", "")
            urls.append(u)
            check(f"Screener {name} URL uses /export (not .ashx)", "/export?" in u and ".ashx" not in u, u[:60])
    except Exception as e:
        check("screeners.yaml", False, str(e))

    # 8. Data sync (catches the value desync + header 0s issues)
    print("\nDATA SYNC:")
    try:
        ov = json.loads(urllib.request.urlopen("http://localhost:7777/api/v2/overview", timeout=5).read()).get("data", {})
        ta = json.loads(urllib.request.urlopen("http://localhost:7777/api/v2/trade-ai", timeout=5).read()).get("data", {})
        ae = json.loads(urllib.request.urlopen("http://localhost:7777/api/v2/aegis/chat-context", timeout=5).read()).get("data", {})
        # Portfolio value sync
        ov_val = ov.get("portfolio_value", 0)
        ae_sum = ae.get("portfolio_summary", "")
        check("Aegis portfolio value matches overview", f"${ov_val:,.0f}" in ae_sum if ov_val > 0 else True,
              f"Overview: ${ov_val:,.0f}, Aegis: {ae_sum[:40]}")
        # Trade AI header sync
        ov_go = ov.get("trade_ai", {}).get("go_count", 0)
        ta_go = ta.get("go_count", 0)
        check(f"Header GO count matches Trade AI page ({ov_go} vs {ta_go})", ov_go == ta_go,
              f"Overview: {ov_go}, Trade AI: {ta_go}")
    except Exception as e:
        check("Data sync", False, str(e))

    # 9. Continuous runner producing results
    print("\nTRADE AI RUNNER:")
    import glob
    summaries = sorted(glob.glob(str(PROJECT_ROOT / "reports" / "2026-*" / "*" / "run_summary.json")))
    if summaries:
        latest = json.loads(Path(summaries[-1]).read_text())
        go = latest.get("go_count", latest.get("goCount", 0))
        tickers = latest.get("ticker_count", 0)
        label = latest.get("run_label", "?")
        check(f"Latest run {label}: {tickers} tickers, {go} GO", tickers > 0 or go >= 0, f"0 tickers = Finviz may be broken")
    else:
        check("Run summaries exist", False, "No run_summary.json found")

    # 10. Stop brief prices (catches the $0.00 bug)
    print("\nSTOP BRIEF INTEGRITY:")
    try:
        import psycopg2
        pw = ""
        for line in (PROJECT_ROOT / ".env").read_text().splitlines():
            if line.startswith("DB_PASSWORD="): pw = line.split("=", 1)[1].strip()
        conn = psycopg2.connect(host="localhost", dbname="trade_ai", user="trade_ai", password=pw)
        cur = conn.cursor()
        cur.execute("SELECT count(*) FROM watchlist_strategy_cards WHERE stop_loss IS NOT NULL AND stop_loss > 0")
        stops = cur.fetchone()[0]
        check(f"Stops with real prices: {stops}", stops > 0, "No stops have prices set")
        conn.close()
    except Exception as e:
        check("Stop data", False, str(e))

    # Summary
    print(f"\n{'='*50}")
    print(f"PASS: {PASS}  FAIL: {FAIL}")
    if FAIL == 0:
        print("ALL CHECKS PASSED — system is healthy")
    else:
        print(f"⚠️  {FAIL} ISSUE(S) FOUND — fix before proceeding")
    return FAIL


if __name__ == "__main__":
    sys.exit(run())
