#!/usr/bin/env python3
"""finviz_validator.py — Validate Finviz screeners + strategy synthesis.

Checks every screener URL returns valid CSV data, validates strategy mappings,
and optionally runs LLM to detect overlaps/gaps in strategy definitions.

Usage:
    python3 scripts/finviz_validator.py --check         # Validate all screeners
    python3 scripts/finviz_validator.py --strategies     # Show strategy matrix
    python3 scripts/finviz_validator.py --llm-review     # LLM reviews strategies for gaps/overlaps
"""
import json, sys, yaml, re
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))


def _env(key: str) -> str:
    for line in (PROJECT_ROOT / ".env").read_text().splitlines():
        if line.startswith(f"{key}="): return line.split("=", 1)[1].strip()
    return ""


def _get_conn():
    import psycopg2
    return psycopg2.connect(host="localhost", dbname="trade_ai", user="trade_ai", password=_env("DB_PASSWORD"))


def validate_screeners() -> list:
    """Test every Finviz screener URL and validate data quality."""
    import requests

    screeners_path = PROJECT_ROOT / "assets" / "screeners.yaml"
    if not screeners_path.exists():
        print("ERROR: screeners.yaml not found")
        return []

    cfg = yaml.safe_load(screeners_path.read_text()) or {}
    screeners = cfg.get("screeners", {})
    cookie = _env("FINVIZ_COOKIE")
    results = []

    for name, entry in screeners.items():
        url = entry.get("finviz_url", "")
        strategy = entry.get("strategy_class", "unknown")
        status_flag = entry.get("status", "active")

        result = {"name": name, "strategy": strategy, "status": status_flag, "url_ok": False,
                  "rows": 0, "has_required_cols": False, "issues": []}

        if not url:
            result["issues"].append("No finviz_url defined")
            results.append(result)
            continue

        # Check URL format
        if "v=152" not in url:
            result["issues"].append(f"URL uses v={re.search(r'v=(\\d+)', url).group(1) if re.search(r'v=(\\d+)', url) else '?'} — should use v=152")
        if "&c=" not in url and "c=0" not in url:
            result["issues"].append("No custom columns (&c=) — will get default fields only")

        if status_flag != "active":
            result["issues"].append(f"Status is '{status_flag}', not 'active'")
            results.append(result)
            continue

        # Test download
        if not cookie:
            result["issues"].append("FINVIZ_COOKIE not set — can't test download")
            results.append(result)
            continue

        try:
            resp = requests.get(url, headers={"Cookie": cookie, "User-Agent": "Mozilla/5.0"}, timeout=15)
            if resp.status_code != 200:
                result["issues"].append(f"HTTP {resp.status_code}")
                results.append(result)
                continue

            content = resp.text
            if "login" in content.lower()[:500] or "sign in" in content.lower()[:500]:
                result["issues"].append("Cookie expired — login page returned")
                results.append(result)
                continue

            result["url_ok"] = True
            lines = content.strip().split("\n")
            result["rows"] = max(0, len(lines) - 1)

            if lines:
                headers = lines[0].replace('"', '').split(",")
                required = {"Ticker", "Price", "Shares Float", "Gap", "Relative Volume"}
                present = set(headers)
                missing = required - present
                result["has_required_cols"] = len(missing) == 0
                if missing:
                    result["issues"].append(f"Missing columns: {missing}")

        except Exception as e:
            result["issues"].append(f"Download error: {e}")

        results.append(result)

    return results


def show_strategy_matrix():
    """Show all strategies with their sources, counts, and coverage."""
    import psycopg2.extras

    conn = _get_conn()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    # Strategy cards
    cur.execute("""SELECT strategy_type, count(*) as cards,
        SUM(CASE WHEN stop_loss IS NOT NULL THEN 1 ELSE 0 END) as with_targets,
        AVG(risk_reward)::numeric(3,1) as avg_rr
        FROM watchlist_strategy_cards GROUP BY strategy_type ORDER BY cards DESC""")
    cards = cur.fetchall()

    # Classification rules
    cur.execute("""SELECT strategy_type, count(*) as symbols
        FROM ticker_strategy_classifications WHERE active=TRUE
        GROUP BY strategy_type ORDER BY symbols DESC""")
    classifications = cur.fetchall()

    # Agent results by strategy
    cur.execute("""SELECT tsc.strategy_type, count(DISTINCT r.symbol) as analyzed_symbols,
        AVG(r.confidence)::numeric(3,2) as avg_conf
        FROM watchlist_agent_results r
        JOIN ticker_strategy_classifications tsc ON r.symbol = tsc.symbol AND tsc.active=TRUE
        WHERE r.created_at > NOW() - INTERVAL '14 days'
        GROUP BY tsc.strategy_type ORDER BY analyzed_symbols DESC""")
    agent_coverage = cur.fetchall()

    conn.close()

    print("\n=== Strategy Matrix ===\n")
    print(f"{'Strategy':<25} {'Cards':>6} {'Targets':>8} {'Avg R:R':>8} {'Classified':>11} {'Analyzed':>9} {'Avg Conf':>9}")
    print("-" * 85)

    strat_map = {}
    for c in cards:
        strat_map[c["strategy_type"]] = {"cards": c["cards"], "targets": c["with_targets"], "rr": c["avg_rr"]}
    for cl in classifications:
        strat_map.setdefault(cl["strategy_type"], {})["classified"] = cl["symbols"]
    for a in agent_coverage:
        strat_map.setdefault(a["strategy_type"], {})["analyzed"] = a["analyzed_symbols"]
        strat_map[a["strategy_type"]]["conf"] = a["avg_conf"]

    for name in sorted(strat_map.keys()):
        s = strat_map[name]
        print(f"{name:<25} {s.get('cards',0):>6} {s.get('targets',0):>8} {str(s.get('rr','—')):>8} {s.get('classified',0):>11} {s.get('analyzed',0):>9} {str(s.get('conf','—')):>9}")

    print(f"\nTotal: {len(strat_map)} strategies")
    return strat_map


def llm_review_strategies() -> dict:
    """Use LLM to review strategy definitions for overlaps, gaps, and suggestions."""
    strat_map = show_strategy_matrix()

    # Build strategy summary for LLM
    strategy_lines = []
    for name, s in sorted(strat_map.items()):
        strategy_lines.append(f"- {name}: {s.get('cards',0)} cards, {s.get('classified',0)} symbols, avg R:R {s.get('rr','?')}")

    # Load YAML definitions
    yaml_path = PROJECT_ROOT / "config" / "agents_data_sources.yaml"
    yaml_strategies = ""
    if yaml_path.exists():
        cfg = yaml.safe_load(yaml_path.read_text()) or {}
        agents = cfg.get("agents", {})
        for agent_name, agent_cfg in agents.items():
            yaml_strategies += f"\n{agent_name}: {agent_cfg.get('role', '')}"

    prompt = f"""/no_think You are a portfolio strategy analyst. Review these 10 investment strategies for a $1.2M disability retirement portfolio (SSDI, MFS filing, 4 accounts).

CURRENT STRATEGIES:
{chr(10).join(strategy_lines)}

AGENT ROLES:
{yaml_strategies}

Analyze (under 300 words):
1. OVERLAPS: Which strategies overlap significantly? Should any be merged?
2. GAPS: What important strategy types are missing? (e.g., covered calls, momentum, sector rotation)
3. CONSISTENCY: Are all strategies well-defined with clear entry/exit criteria?
4. SUGGESTIONS: Top 3 specific improvements to the strategy framework.
5. SSDI/DISABILITY: Are strategies properly accounting for SSDI income protection, IRMAA thresholds, and Medicaid lookback?

Be specific and actionable."""

    try:
        from llm_router import get_llm_response
        result = get_llm_response("agent_narrative", prompt, max_tokens=600, high_impact=False)
        review = result.get("response", "") if result.get("success") else "LLM review failed"

        # Store review
        try:
            conn = _get_conn()
            cur = conn.cursor()
            cur.execute("""INSERT INTO agent_intelligence_rules (rule_type, rule_key, config, changed_by, updated_at)
                VALUES ('strategy_review', 'latest', %s, 'finviz_validator', NOW())
                ON CONFLICT (rule_type, rule_key) DO UPDATE SET config=EXCLUDED.config, updated_at=NOW()""",
                (json.dumps({"review": review, "strategy_count": len(strat_map), "provider": result.get("provider", "")}),))
            conn.commit()
            conn.close()
        except Exception:
            pass

        print(f"\n=== LLM Strategy Review ===\n")
        print(review)
        return {"review": review, "provider": result.get("provider")}
    except Exception as e:
        print(f"LLM review error: {e}")
        return {"error": str(e)}


def full_audit() -> dict:
    """Full audit: validate screeners (YAML + DB) + strategy matrix + gaps."""
    import psycopg2.extras

    print("=" * 70)
    print("FINVIZ FULL AUDIT")
    print("=" * 70)

    # 1. YAML screeners (Elite, used for Trade AI day-scalp)
    print("\n── YAML Screeners (screeners.yaml — Elite Finviz) ──\n")
    yaml_results = validate_screeners()
    for r in yaml_results:
        icon = "✅" if r["url_ok"] and r["has_required_cols"] else "❌"
        print(f"  {icon} {r['name']}: {r['rows']} rows, strategy={r['strategy']}")
        for issue in r["issues"]:
            print(f"       → {issue}")

    # 2. DB screeners (finviz_screeners table — strategy-based)
    print("\n── DB Screeners (finviz_screeners table) ──\n")
    conn = _get_conn()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("""SELECT screener_id, display_name, strategy_type, active, schedule,
        results_count, finviz_url FROM finviz_screeners ORDER BY strategy_type, screener_id""")
    db_screeners = cur.fetchall()

    issues = []
    for s in db_screeners:
        url = s.get("finviz_url", "") or ""
        problems = []
        if not url:
            problems.append("NO URL")
        elif "v=111" in url:
            problems.append("v=111 (free — no RVOL/Float)")
        if not s.get("strategy_type"):
            problems.append("NO STRATEGY mapped")
        if not s.get("active"):
            problems.append("INACTIVE")

        icon = "✅" if not problems else "⚠️" if "v=111" in str(problems) else "❌"
        print(f"  {icon} {s['screener_id']:<25} {(s.get('strategy_type') or '—'):<28} {s.get('schedule','—'):<8} results={s.get('results_count',0)}")
        for p in problems:
            print(f"       → {p}")
            issues.append({"screener": s["screener_id"], "issue": p})

    conn.close()

    # 3. Strategy coverage gaps
    print(f"\n── Summary ──\n")
    print(f"  YAML screeners: {len(yaml_results)} ({sum(1 for r in yaml_results if r['url_ok'])} OK)")
    print(f"  DB screeners:   {len(db_screeners)} ({sum(1 for s in db_screeners if s.get('active') and s.get('finviz_url'))} active with URL)")
    print(f"  Total issues:   {len(issues)}")

    strategies_with_screener = set(s.get("strategy_type") for s in db_screeners if s.get("strategy_type") and s.get("finviz_url"))
    all_strategies = set()
    cur2 = _get_conn().cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur2.execute("SELECT DISTINCT strategy_type FROM ticker_strategy_classifications WHERE active=TRUE")
    all_strategies = {r["strategy_type"] for r in cur2.fetchall()}
    cur2.connection.close()

    uncovered = all_strategies - strategies_with_screener
    if uncovered:
        print(f"\n  ⚠️  Strategies WITHOUT a Finviz screener:")
        for s in sorted(uncovered):
            print(f"       → {s}")

    return {"yaml": len(yaml_results), "db": len(db_screeners), "issues": len(issues), "uncovered_strategies": sorted(uncovered)}


if __name__ == "__main__":
    if "--full-audit" in sys.argv:
        r = full_audit()
        # llm_review already calls show_strategy_matrix internally,
        # so only show it standalone if --llm-review is NOT present
        if "--strategies" in sys.argv and "--llm-review" not in sys.argv:
            show_strategy_matrix()
        if "--llm-review" in sys.argv:
            llm_review_strategies()

    elif "--check" in sys.argv:
        print("=== Finviz Screener Validation ===\n")
        results = validate_screeners()
        for r in results:
            icon = "✅" if r["url_ok"] and r["has_required_cols"] and not r["issues"] else "⚠️" if r["url_ok"] else "❌"
            print(f"  {icon} {r['name']}: {r['rows']} rows, strategy={r['strategy']}")
            for issue in r["issues"]:
                print(f"       → {issue}")
        ok = sum(1 for r in results if r["url_ok"] and not r["issues"])
        print(f"\n  {ok}/{len(results)} screeners OK")

    elif "--strategies" in sys.argv:
        show_strategy_matrix()

    elif "--llm-review" in sys.argv:
        llm_review_strategies()

    else:
        print("Usage: --full-audit [--strategies] [--llm-review] | --check | --strategies | --llm-review")
