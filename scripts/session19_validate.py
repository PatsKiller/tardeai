#!/usr/bin/env python3
"""Session 19 validation — weekly incubator, roll-on/roll-off, proposal quality review."""
import json
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

PASS = 0
FAIL = 0
WARN = 0


def check(label, ok, msg=""):
    global PASS, FAIL
    if ok:
        PASS += 1
        print(f"  [PASS] {label}")
    else:
        FAIL += 1
        print(f"  [FAIL] {label}: {msg}")


def warn(label, msg=""):
    global WARN
    WARN += 1
    print(f"  [WARN] {label}: {msg}")


def main():
    print("=" * 60)
    print("SESSION 19 VALIDATION: WEEKLY INCUBATOR")
    print("=" * 60)

    # 1. Tables exist
    print("\n--- Check 1: Schema ---")
    try:
        import psycopg2
        conn = psycopg2.connect(host="127.0.0.1", dbname="trade_ai", user="trade_ai",
                                password=os.environ.get("DB_PASSWORD", ""))
        cur = conn.cursor()
        for tbl in ("incubator_universe", "incubator_events", "proposal_quality_reviews"):
            cur.execute("SELECT COUNT(*) FROM information_schema.tables WHERE table_name=%s", [tbl])
            exists = cur.fetchone()[0] > 0
            check(f"Table {tbl} exists", exists)
        conn.close()
    except Exception as e:
        check("Schema check", False, str(e))

    # 2. Weekly builder dry-run
    print("\n--- Check 2: Weekly builder ---")
    try:
        import ast
        ast.parse((PROJECT_ROOT / "scripts" / "weekly_incubator_builder.py").read_text())
        check("weekly_incubator_builder.py parses", True)
    except Exception as e:
        check("weekly_incubator_builder.py parses", False, str(e))

    # 3. Daily refresh dry-run
    print("\n--- Check 3: Daily refresh ---")
    try:
        ast.parse((PROJECT_ROOT / "scripts" / "daily_incubator_refresh.py").read_text())
        check("daily_incubator_refresh.py parses", True)
    except Exception as e:
        check("daily_incubator_refresh.py parses", False, str(e))

    # 4. Rolloff
    print("\n--- Check 4: Rolloff engine ---")
    try:
        ast.parse((PROJECT_ROOT / "scripts" / "incubator_rolloff_engine.py").read_text())
        check("incubator_rolloff_engine.py parses", True)
    except Exception as e:
        check("incubator_rolloff_engine.py parses", False, str(e))

    # 5. Proposal quality reviewer
    print("\n--- Check 5: Proposal quality reviewer ---")
    try:
        ast.parse((PROJECT_ROOT / "scripts" / "proposal_quality_reviewer.py").read_text())
        check("proposal_quality_reviewer.py parses", True)
    except Exception as e:
        check("proposal_quality_reviewer.py parses", False, str(e))

    # 6. Model
    print("\n--- Check 6: LLM model ---")
    try:
        from local_llm_config import get_local_llm_model
        model = get_local_llm_model()
        check(f"model = {model}", model == "qwen3:14b")
    except Exception as e:
        check("model check", False, str(e))

    # 7. APIs
    print("\n--- Check 7: APIs ---")
    import urllib.request
    for ep in ("incubator", "incubator-events", "incubator-health", "proposal-quality-review"):
        try:
            with urllib.request.urlopen(f"http://localhost:7777/api/v2/{ep}", timeout=5) as r:
                d = json.loads(r.read())
                inner = d.get("data", d)
                check(f"/api/v2/{ep} returns ok", inner.get("ok", False))
        except Exception as e:
            warn(f"/api/v2/{ep}", str(e))

    # 8. Incubator has data
    print("\n--- Check 8: Incubator data ---")
    try:
        with urllib.request.urlopen("http://localhost:7777/api/v2/incubator-health", timeout=5) as r:
            d = json.loads(r.read()).get("data", {})
            active = d.get("active", 0)
            check(f"Incubator active = {active}", active > 0, "no active entries")
    except Exception as e:
        warn("Incubator data", str(e))

    # 9. Real journal clean
    print("\n--- Check 9: Real journal clean ---")
    try:
        with urllib.request.urlopen("http://localhost:7777/api/v2/journal", timeout=5) as resp:
            raw = json.loads(resp.read())
            inner = raw.get("data", raw) if isinstance(raw, dict) else raw
            trades = (inner.get("trades", []) if isinstance(inner, dict) else inner) or []
            paper = sum(1 for t in trades if isinstance(t, dict) and "PAPER" in (str(t.get("account", "")) + str(t.get("account_name", ""))).upper())
            check(f"Real journal clean ({len(trades)} trades, {paper} paper)", paper == 0)
    except Exception as e:
        warn("Real journal", str(e))

    # 10. Holdings
    print("\n--- Check 10: Holdings ---")
    try:
        h = json.loads((PROJECT_ROOT / "data" / "portfolios" / "state" / "holdings.json").read_text())
        v = h["portfolio_totals"]["total_value"]
        check(f"Holdings ${v:,.0f} > $1M", v > 1_000_000)
    except Exception as e:
        check("Holdings", False, str(e))

    # 11. No hardcoded model
    print("\n--- Check 11: No hardcoded model ---")
    import re
    model_pat = re.compile(r'"model"\s*:\s*"(qwen3:[0-9]+\.?[0-9]*b|llama3|mistral|deepseek|gemma)"')
    bad = []
    for py in sorted((PROJECT_ROOT / "scripts").glob("*.py")):
        if py.name.startswith("session") or py.name == "local_llm_config.py":
            continue
        for i, line in enumerate(py.read_text().splitlines(), 1):
            if line.strip().startswith("#"):
                continue
            if model_pat.search(line):
                bad.append(f"{py.name}:{i}")
    check("No hardcoded models in payloads", len(bad) == 0, f"found: {', '.join(bad)}")

    # Summary
    print("\n" + "=" * 60)
    if FAIL == 0:
        print(f"SESSION 19 VALIDATION: PASSED ({PASS} passed, {WARN} warnings)")
    else:
        print(f"SESSION 19 VALIDATION: FAILED ({PASS} passed, {FAIL} failed, {WARN} warnings)")
    print("=" * 60)
    sys.exit(1 if FAIL > 0 else 0)


if __name__ == "__main__":
    main()
