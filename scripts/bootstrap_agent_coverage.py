#!/usr/bin/env python3
"""bootstrap_agent_coverage.py — Queue missing agent jobs for all portfolio/watchlist symbols.

Usage:
    python3 scripts/bootstrap_agent_coverage.py --portfolio-only --json
    python3 scripts/bootstrap_agent_coverage.py --all-watchlist --json
    python3 scripts/bootstrap_agent_coverage.py --dry-run --json
    python3 scripts/bootstrap_agent_coverage.py --symbol SCHD --force --json
"""
import json, os, sys
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
STATE_DIR = PROJECT_ROOT / "data" / "portfolios" / "state"

# Map detailed strategy_type to escalation policy key
_POLICY_MAP = {
    "dividend_growth_compounder": "income", "covered_call_income": "income",
    "high_yield_income_bdc": "income", "bond_income": "income",
    "reit_income": "income", "international_dividend": "income",
    "core_growth_compounder": "growth_etf", "core_index": "growth_etf",
    "defense_thesis": "defense_thesis", "speculative_growth": "speculative_growth",
    "swing_trade": "swing_trade", "recovery_watch": "swing_trade",
}


def _get_conn():
    import psycopg2
    pw = ""
    for line in (PROJECT_ROOT / ".env").read_text().splitlines():
        if line.startswith("DB_PASSWORD="): pw = line.split("=", 1)[1].strip()
    return psycopg2.connect(host="localhost", dbname="trade_ai", user="trade_ai", password=pw)


def bootstrap(portfolio_only: bool = True, all_watchlist: bool = False,
              dry_run: bool = False, force_symbol: str = None) -> dict:
    import psycopg2.extras
    conn = _get_conn()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    # Get escalation policies
    cur.execute("SELECT strategy_type, required_agents FROM watchlist_escalation_policies")
    policies = {r["strategy_type"]: [a.replace("_agent", "") for a in r["required_agents"]] for r in cur.fetchall()}

    # Get target symbols
    if force_symbol:
        symbols = [force_symbol.upper()]
    elif portfolio_only:
        holdings = json.loads((STATE_DIR / "holdings.json").read_text())
        symbols = list(set(h.get("symbol") for h in holdings.get("holdings", [])
                           if h.get("symbol") and not h.get("is_cash")))
    elif all_watchlist:
        cur.execute("SELECT DISTINCT symbol FROM ticker_strategy_classifications WHERE active=TRUE")
        symbols = [r["symbol"] for r in cur.fetchall()]
    else:
        symbols = []

    # Get completed agents per symbol
    cur.execute("""
        SELECT symbol, array_agg(DISTINCT agent) as agents
        FROM watchlist_agent_results WHERE status='completed' AND symbol != 'TEST_VALIDATE'
        GROUP BY symbol
    """)
    completed_map = {r["symbol"]: set(a.replace("_agent", "") for a in r["agents"]) for r in cur.fetchall()}

    # Get pending jobs
    cur.execute("SELECT symbol, requested_agent FROM watchlist_agent_jobs WHERE status IN ('queued','processing')")
    pending = set()
    for r in cur.fetchall():
        pending.add(f"{r['symbol']}:{r['requested_agent'].replace('_agent', '')}")

    # Determine missing agents and queue jobs
    queued = []
    skipped = []
    ts = datetime.now().strftime("%Y%m%d%H%M%S")

    for sym in sorted(symbols):
        # Get classification
        cur.execute("SELECT strategy_type FROM ticker_strategy_classifications WHERE symbol=%s AND active=TRUE", (sym,))
        cls = cur.fetchone()
        if not cls:
            skipped.append({"symbol": sym, "reason": "not_classified"})
            continue

        strategy_type = cls["strategy_type"]
        policy_key = _POLICY_MAP.get(strategy_type, "core_holding")
        required = set(policies.get(policy_key, ["steph", "risk"]))
        completed = completed_map.get(sym, set())

        if force_symbol:
            missing = required  # Force re-queue all
        else:
            missing = required - completed

        for agent in sorted(missing):
            agent_key = agent if agent in ("maria", "steph") else f"{agent}_agent"
            pend_key = f"{sym}:{agent}"

            if pend_key in pending and not force_symbol:
                skipped.append({"symbol": sym, "agent": agent, "reason": "already_pending"})
                continue

            job_id = f"v8-{sym.lower()}-{agent_key}-{ts}"

            if not dry_run:
                sys.path.insert(0, str(PROJECT_ROOT / "scripts" / "lib"))
                from agent_job_enqueue_governance import EnqueueRequest, governed_enqueue
                governed_enqueue(cur, EnqueueRequest(
                    symbol=sym,
                    requested_agent=agent_key,
                    request_type="research",
                    submitted_from="v8_bootstrap",
                    priority=2,
                    note=f"V8 bootstrap: {strategy_type}",
                    job_id=job_id,
                    payload={"source": "v8_bootstrap", "strategy_type": strategy_type},
                    universe_tier="T1",
                    material=True,
                ))
                cur.execute("""
                    INSERT INTO watchlist_events (event_type, symbol, agent, status, message)
                    VALUES ('v8_bootstrap', %s, %s, 'queued', %s)
                """, (sym, agent_key, f"V8 agent bootstrap for {strategy_type}"))

            queued.append({"symbol": sym, "agent": agent_key, "strategy_type": strategy_type, "job_id": job_id})

    if not dry_run:
        conn.commit()

    conn.close()

    result = {
        "mode": "dry_run" if dry_run else "live",
        "target": "portfolio_only" if portfolio_only else ("all_watchlist" if all_watchlist else f"symbol:{force_symbol}"),
        "symbols_checked": len(symbols),
        "jobs_queued": len(queued),
        "jobs_skipped": len(skipped),
        "queued": queued[:20],  # First 20 for display
        "skipped_sample": skipped[:5],
    }

    print(f"[v8-bootstrap] {'DRY RUN — ' if dry_run else ''}Checked {len(symbols)} symbols, queued {len(queued)} jobs, skipped {len(skipped)}")
    return result


if __name__ == "__main__":
    dry = "--dry-run" in sys.argv
    portfolio = "--portfolio-only" in sys.argv
    all_wl = "--all-watchlist" in sys.argv
    force = None
    if "--symbol" in sys.argv:
        force = sys.argv[sys.argv.index("--symbol") + 1].upper()
    elif "--force" in sys.argv and "--symbol" not in sys.argv:
        pass  # --force only works with --symbol

    result = bootstrap(portfolio_only=portfolio or (not all_wl and not force),
                       all_watchlist=all_wl, dry_run=dry, force_symbol=force)

    if "--json" in sys.argv:
        print(json.dumps(result, indent=2, default=str))
    else:
        for q in result.get("queued", []):
            print(f"  {'[DRY]' if dry else '[QUEUED]'} {q['symbol']:>8} → {q['agent']:>12} ({q['strategy_type']})")
