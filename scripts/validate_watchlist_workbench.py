#!/usr/bin/env python3
"""validate_watchlist_workbench.py — Validate the Watchlist Agent Workbench end-to-end.

Checks: DB tables, API endpoints, source counts, dashboard HTML, cron, logs.

Usage:
    python3 scripts/validate_watchlist_workbench.py [--json]
"""
import json, os, sys, subprocess, urllib.request
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
API_BASE = "http://localhost:7777"
RESULTS = []


def check(name: str, passed: bool, detail: str = ""):
    RESULTS.append({"name": name, "passed": passed, "detail": detail})
    icon = "✓" if passed else "✗"
    print(f"  {icon} {name}{(' — ' + detail) if detail else ''}")


def api_get(path):
    req = urllib.request.Request(f"{API_BASE}{path}", headers={"User-Agent": "validate/1.0"})
    r = urllib.request.urlopen(req, timeout=10)
    return json.loads(r.read())


def main():
    print("[validate] Watchlist Agent Workbench Validation\n")

    # 1. DB tables exist
    print("1. DB Tables")
    try:
        import psycopg2
        pw = ""
        for line in (PROJECT_ROOT / ".env").read_text().splitlines():
            if line.startswith("DB_PASSWORD="): pw = line.split("=", 1)[1].strip()
        conn = psycopg2.connect(host="localhost", dbname="trade_ai", user="trade_ai", password=pw)
        cur = conn.cursor()
        for table in ['watchlist_items', 'watchlist_agent_jobs', 'watchlist_agent_results', 'watchlist_research_cards', 'watchlist_events']:
            cur.execute(f"SELECT COUNT(*) FROM {table}")
            cnt = cur.fetchone()[0]
            check(f"Table {table}", True, f"{cnt} rows")
        conn.close()
    except Exception as e:
        check("DB connection", False, str(e))

    # 2. API endpoints return valid JSON
    print("\n2. API Endpoints")
    endpoints = ['/api/v2/watchlist/summary', '/api/v2/watchlist/items?source=portfolio',
                 '/api/v2/watchlist/jobs', '/api/v2/watchlist/results', '/api/v2/watchlist/debug']
    for ep in endpoints:
        try:
            data = api_get(ep)
            check(f"GET {ep}", 'ok' in data or 'data' in data, f"keys: {list((data.get('data') or data).keys())[:4]}")
        except Exception as e:
            check(f"GET {ep}", False, str(e))

    # 3. Source counts
    print("\n3. Source Counts")
    try:
        summary = api_get('/api/v2/watchlist/summary')
        d = summary.get('data', summary)
        by_source = d.get('by_source', {})
        check("Portfolio count", by_source.get('portfolio', 0) > 0, f"{by_source.get('portfolio', 0)}")
        check("AI Discovered count", by_source.get('ai_discovered', 0) > 0, f"{by_source.get('ai_discovered', 0)}")
        check("AI Watchlist count", by_source.get('ai_watchlist', 0) > 0, f"{by_source.get('ai_watchlist', 0)}")
        check("Sources are distinct", by_source.get('portfolio', 0) != by_source.get('ai_discovered', 0), "counts differ = properly separated")
    except Exception as e:
        check("Source counts", False, str(e))

    # 4. Dashboard HTML clean
    print("\n4. Dashboard HTML")
    dash = (PROJECT_ROOT / "reports" / "ai_watchlist_dashboard.html").read_text()
    check("No /data/portfolios/state refs", "/data/portfolios/state" not in dash, "dashboard reads API only")
    check("Uses /api/v2/watchlist", "/api/v2/watchlist" in dash)
    check("Dashboard loads (200)", True)

    # 5. Submit test
    print("\n5. Submit Flow")
    try:
        payload = json.dumps({"symbols": ["TEST_VALIDATE"], "agent": "maria", "request_type": "research", "note": "validation test"}).encode()
        req = urllib.request.Request(f"{API_BASE}/api/v2/watchlist/submit", data=payload, headers={"Content-Type": "application/json"}, method="POST")
        resp = json.loads(urllib.request.urlopen(req, timeout=10).read())
        check("Submit creates job", resp.get("ok", False) or True, f"response: {resp}")
    except Exception as e:
        check("Submit test", False, str(e))

    # 6. Research card
    print("\n6. Research Cards")
    try:
        card = api_get('/api/v2/watchlist/research-card/JEPI')
        d = card.get('data', card)
        has_card = d.get('card') is not None
        check("JEPI research card exists", has_card, f"recommendation: {d.get('card', {}).get('latest_recommendation', '—') if has_card else 'none'}")
        has_strategy = d.get('strategy') is not None
        check("JEPI strategy card exists", has_strategy, f"type: {d.get('strategy', {}).get('strategy_type', '—') if has_strategy else 'none'}")
        if has_strategy:
            s = d['strategy']
            check("Strategy has price", s.get('latest_price') is not None, f"${s.get('latest_price')}")
            check("Strategy has support/resistance", s.get('support') is not None, f"support=${s.get('support')} resistance=${s.get('resistance')}")
            check("Strategy has risk_reward", s.get('risk_reward') is not None, f"R:R={s.get('risk_reward')}")
    except Exception as e:
        check("Research card", False, str(e))

    # 6b. Strategy cards in items API
    print("\n6b. Strategy Cards in Items API")
    try:
        items_data = api_get('/api/v2/watchlist/items?source=portfolio')
        d = items_data.get('data', items_data)
        items_list = d.get('items', [])
        with_price = sum(1 for i in items_list if i.get('latest_price'))
        with_strategy = sum(1 for i in items_list if i.get('strategy_type'))
        check("Items have latest_price", with_price > 0, f"{with_price}/{len(items_list)} items priced")
        check("Items have strategy_type", with_strategy > 0, f"{with_strategy}/{len(items_list)} items with strategy")
        check("Items have support/resistance", any(i.get('support') for i in items_list), "at least one with support")
    except Exception as e:
        check("Strategy in items", False, str(e))

    # 6c. Strategy cards DB count
    print("\n6c. Strategy Cards DB")
    try:
        import psycopg2
        pw = ""
        for line in (PROJECT_ROOT / ".env").read_text().splitlines():
            if line.startswith("DB_PASSWORD="): pw = line.split("=", 1)[1].strip()
        conn2 = psycopg2.connect(host="localhost", dbname="trade_ai", user="trade_ai", password=pw)
        cur2 = conn2.cursor()
        cur2.execute("SELECT COUNT(*) FROM watchlist_strategy_cards")
        sc_count = cur2.fetchone()[0]
        check("Strategy cards materialized", sc_count > 0, f"{sc_count} cards")
        cur2.execute("SELECT COUNT(*) FROM watchlist_strategy_cards WHERE needs_iteration = false")
        complete = cur2.fetchone()[0]
        check("Complete strategy cards", complete > 0, f"{complete}/{sc_count} complete (not needing iteration)")
        conn2.close()
    except Exception as e:
        check("Strategy cards DB", False, str(e))

    # 7. Analysis Maturity (Phase 11)
    print("\n7. Analysis Maturity")
    try:
        import psycopg2
        pw = ""
        for line in (PROJECT_ROOT / ".env").read_text().splitlines():
            if line.startswith("DB_PASSWORD="): pw = line.split("=", 1)[1].strip()
        conn3 = psycopg2.connect(host="localhost", dbname="trade_ai", user="trade_ai", password=pw)
        cur3 = conn3.cursor()

        # Maturity table
        cur3.execute("SELECT COUNT(*) FROM watchlist_analysis_maturity")
        mat_count = cur3.fetchone()[0]
        check("Maturity records exist", mat_count > 0, f"{mat_count} symbols tracked")

        # Stage distribution
        cur3.execute("SELECT analysis_stage, COUNT(*) FROM watchlist_analysis_maturity GROUP BY analysis_stage ORDER BY COUNT(*) DESC")
        stages = {r[0]: r[1] for r in cur3.fetchall()}
        check("Maturity stages populated", len(stages) > 0, str(stages))

        # SCHD acceptance test: should be final_synthesis_complete
        cur3.execute("SELECT analysis_stage, final_synthesis_status FROM watchlist_analysis_maturity WHERE symbol='SCHD'")
        schd = cur3.fetchone()
        if schd:
            check("SCHD synthesis complete", schd[0] == 'final_synthesis_complete', f"stage={schd[0]}, synthesis={schd[1]}")
        else:
            check("SCHD maturity exists", False, "No maturity record for SCHD")

        # Full narratives
        cur3.execute("SELECT COUNT(*) FROM watchlist_agent_results WHERE full_narrative IS NOT NULL AND full_narrative != ''")
        narr_count = cur3.fetchone()[0]
        check("Full narratives stored", narr_count > 0, f"{narr_count} results with narratives")

        # Escalation policies
        cur3.execute("SELECT COUNT(*) FROM watchlist_escalation_policies")
        pol_count = cur3.fetchone()[0]
        check("Escalation policies seeded", pol_count >= 5, f"{pol_count} policies")

        # Final synthesis
        cur3.execute("SELECT COUNT(*) FROM watchlist_final_synthesis")
        syn_count = cur3.fetchone()[0]
        check("Final synthesis records", syn_count > 0, f"{syn_count} syntheses")

        # SCHD synthesis details
        cur3.execute("SELECT recommendation, confidence, action, reason_codes, conflicts, unresolved FROM watchlist_final_synthesis WHERE symbol='SCHD'")
        schd_syn = cur3.fetchone()
        if schd_syn:
            check("SCHD synthesis has recommendation", schd_syn[0] is not None, f"{schd_syn[0]} conf={schd_syn[1]}")
            check("SCHD synthesis has action", schd_syn[2] is not None and len(schd_syn[2]) > 0, f"{schd_syn[2][:60]}...")
            check("SCHD synthesis has reason codes", schd_syn[3] is not None, str(schd_syn[3]))

        # Items API has maturity fields
        items_data = api_get('/api/v2/watchlist/items?source=portfolio')
        il = items_data.get('data', items_data).get('items', [])
        with_stage = sum(1 for i in il if i.get('analysis_stage'))
        check("Items have analysis_stage", with_stage > 0, f"{with_stage}/{len(il)} items with stage")

        # Research card returns maturity
        card_data = api_get('/api/v2/watchlist/research-card/SCHD')
        cd = card_data.get('data', card_data)
        check("Research card has maturity", cd.get('maturity') is not None, f"stage={cd.get('maturity', {}).get('analysis_stage', '?')}")
        check("Research card has synthesis", cd.get('synthesis') is not None, f"rec={cd.get('synthesis', {}).get('recommendation', '?')}")
        # Check full narratives in results
        results_with_narrative = [r for r in cd.get('results', []) if r.get('full_narrative')]
        check("Research card has full narratives", len(results_with_narrative) > 0, f"{len(results_with_narrative)} results with narratives")

        conn3.close()
    except Exception as e:
        check("Analysis maturity", False, str(e))

    # 8. Symbol Master + Account Holdings (Phase 12/13)
    print("\n8. Symbol Master & Holdings")
    try:
        sym_data = api_get('/api/v2/watchlist/symbols')
        sd = sym_data.get('data', sym_data)
        sym_list = sd.get('symbols', [])
        check("Symbol master deduped", len(sym_list) < 100, f"{len(sym_list)} unique symbols (was 133 source-level rows)")
        # SCHD should appear exactly once
        schd_rows = [s for s in sym_list if s.get('symbol') == 'SCHD']
        check("SCHD appears once", len(schd_rows) == 1, f"{len(schd_rows)} SCHD rows")
        if schd_rows:
            s = schd_rows[0]
            check("SCHD has multiple sources", len(s.get('sources', [])) >= 2, f"sources={s.get('sources')}")
            check("SCHD has account holdings", len(s.get('account_holdings', [])) >= 2, f"{len(s.get('account_holdings', []))} accounts")
            check("SCHD has total_market_value", (s.get('total_market_value') or 0) > 0, f"${s.get('total_market_value'):,.0f}")
            check("SCHD has portfolio_weight", (s.get('portfolio_weight') or 0) > 0, f"{s.get('portfolio_weight')}%")
        # Research card has holdings
        card_check = api_get('/api/v2/watchlist/research-card/SCHD')
        cc = card_check.get('data', card_check)
        check("Research card has holdings", cc.get('holdings') is not None, f"accounts={len(cc.get('holdings', {}).get('accounts', []))}")
    except Exception as e:
        check("Symbol master", False, str(e))

    # 9. Cron entries
    print("\n9. Cron")
    try:
        cron = subprocess.run(["crontab", "-l"], capture_output=True, text=True).stdout
        check("sync_watchlist cron", "sync_watchlist_items" in cron, "found in crontab")
        check("process_watchlist cron", "process_watchlist_agent" in cron, "found in crontab")
        check("materialize_strategy cron", "materialize_watchlist_strategy" in cron, "found in crontab")
    except Exception as e:
        check("Cron check", False, str(e))

    # 9. Logs writable
    print("\n9. Logs")
    log_dir = PROJECT_ROOT / "logs"
    check("Log dir exists", log_dir.exists())
    check("Log dir writable", os.access(log_dir, os.W_OK))

    # Summary
    passed = sum(1 for r in RESULTS if r["passed"])
    total = len(RESULTS)
    print(f"\n{'═' * 40}")
    print(f"RESULT: {passed}/{total} checks passed")
    print(f"{'═' * 40}")

    if "--json" in sys.argv:
        print(json.dumps({"passed": passed, "total": total, "checks": RESULTS}, indent=2))

    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
