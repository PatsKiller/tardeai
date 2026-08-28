#!/usr/bin/env python3
"""portfolio_level_qa.py — Portfolio-wide guardrail checks.

Evaluates group caps, income floor, concentration, cross-symbol conflicts.
Persists results to portfolio_level_qa_history.

Usage:
    python3 scripts/portfolio_level_qa.py [--json]
"""
import json, os, sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
STATE_DIR = PROJECT_ROOT / "data" / "portfolios" / "state"


def _get_conn():
    import psycopg2
    pw = ""
    for line in (PROJECT_ROOT / ".env").read_text().splitlines():
        if line.startswith("DB_PASSWORD="): pw = line.split("=", 1)[1].strip()
    return psycopg2.connect(host="localhost", dbname="trade_ai", user="trade_ai", password=pw)


def evaluate_portfolio_qa() -> dict:
    import psycopg2.extras
    conn = _get_conn()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    # Portfolio value
    holdings = json.loads((STATE_DIR / "holdings.json").read_text()) if (STATE_DIR / "holdings.json").exists() else {}
    total_portfolio = sum(info.get("total_value", 0) for info in holdings.get("account_summaries", {}).values())

    # Income goals
    cur.execute("SELECT * FROM portfolio_income_goals LIMIT 1")
    goals = cur.fetchone() or {}

    # Total income
    cur.execute("SELECT SUM(annual_income) as total FROM income_asset_profiles")
    total_income = float((cur.fetchone() or {}).get("total", 0) or 0)
    target = float(goals.get("target_income", 55000))
    minimum = float(goals.get("minimum_income_target", 37500))
    stretch = float(goals.get("stretch_income_target", 67500))
    gap = max(0, target - total_income)

    # Group allocations — compute actual allocation per group
    cur.execute("SELECT * FROM strategy_group_caps WHERE active=TRUE")
    groups = cur.fetchall()

    # Build allocation by strategy_type
    alloc_by_type = {}
    for h in holdings.get("holdings", []):
        sym = h.get("symbol", "")
        mv = float(h.get("market_value", 0) or 0)
        if h.get("is_cash") or mv < 1:
            continue
        cur.execute("SELECT strategy_type FROM ticker_strategy_classifications WHERE symbol=%s AND active=TRUE", (sym,))
        c = cur.fetchone()
        st = c["strategy_type"] if c else "unclassified"
        alloc_by_type[st] = alloc_by_type.get(st, 0) + mv

    group_allocs = {}
    violations = []
    concentration_warnings = []

    for g in groups:
        gid = g["group_id"]
        members = g.get("member_strategy_types") or []
        if isinstance(members, str):
            members = json.loads(members)
        group_val = sum(alloc_by_type.get(st, 0) for st in members)
        group_pct = round(group_val / total_portfolio * 100, 1) if total_portfolio > 0 else 0
        target_min = float(g.get("target_min_pct", 0) or 0)
        target_max = float(g.get("target_max_pct", 100) or 100)
        hard_cap = float(g.get("hard_cap_pct", 100) or 100)

        status = "in_range"
        if group_pct > hard_cap:
            status = "OVER_HARD_CAP"
            violations.append({"group": gid, "actual": group_pct, "hard_cap": hard_cap, "severity": "critical"})
        elif group_pct > target_max:
            status = "over_target"
            violations.append({"group": gid, "actual": group_pct, "target_max": target_max, "severity": "warning"})
        elif group_pct < target_min:
            status = "under_target"
            violations.append({"group": gid, "actual": group_pct, "target_min": target_min, "severity": "warning"})

        group_allocs[gid] = {"value": round(group_val, 2), "pct": group_pct, "status": status,
                             "target": f"{target_min:.0f}-{target_max:.0f}%", "hard_cap": hard_cap}

    # Income floor status
    income_floor = "above_minimum" if total_income >= minimum else "below_minimum"
    if total_income >= target:
        income_floor = "at_target"
    elif total_income >= stretch:
        income_floor = "above_stretch"

    # Concentration: any single symbol > 15% of portfolio
    for h in holdings.get("holdings", []):
        sym = h.get("symbol", "")
        mv = float(h.get("market_value", 0) or 0)
        pct = round(mv / total_portfolio * 100, 2) if total_portfolio > 0 else 0
        if pct > 15:
            concentration_warnings.append({"symbol": sym, "weight": pct, "issue": "single_position_over_15pct"})

    # Concentration: any single symbol > 30% of income
    cur.execute("SELECT symbol, portfolio_income_pct FROM income_asset_profiles WHERE portfolio_income_pct > 30")
    for r in cur.fetchall():
        concentration_warnings.append({"symbol": r["symbol"], "income_pct": float(r["portfolio_income_pct"]), "issue": "income_concentration_over_30pct"})

    # Cross-symbol conflicts: multiple trim/sell recs on same group
    cur.execute("""
        SELECT fs.symbol, fs.recommendation, tsc.strategy_type
        FROM watchlist_final_synthesis fs
        JOIN ticker_strategy_classifications tsc ON tsc.symbol = fs.symbol
        WHERE fs.recommendation IN ('TRIM','SELL','REBALANCE_TRIM') AND fs.superseded IS NOT TRUE
    """)
    trims = cur.fetchall()
    trim_by_group = {}
    for t in trims:
        for g in groups:
            members = g.get("member_strategy_types") or []
            if isinstance(members, str):
                members = json.loads(members)
            if t["strategy_type"] in members:
                trim_by_group.setdefault(g["group_id"], []).append(t["symbol"])
    cross_conflicts = []
    for gid, syms in trim_by_group.items():
        if len(syms) >= 2:
            cross_conflicts.append({"group": gid, "symbols": syms, "issue": "multiple_trim_sell_in_same_group"})

    actionable = len(violations) == 0 and income_floor != "below_minimum"
    human_review = len(violations) > 0 or len(concentration_warnings) > 0

    qa_summary = f"Portfolio ${total_portfolio:,.0f}. Income ${total_income:,.0f}/yr ({total_income/target*100:.0f}% of target). {len(violations)} group violations. {len(concentration_warnings)} concentration warnings."

    result = {
        "portfolio_value": total_portfolio,
        "projected_annual_income": total_income,
        "minimum_income_target": minimum,
        "target_income": target,
        "stretch_income": stretch,
        "income_gap": gap,
        "group_allocations": group_allocs,
        "group_cap_violations": violations,
        "income_floor_status": income_floor,
        "concentration_warnings": concentration_warnings,
        "cross_symbol_conflicts": cross_conflicts,
        "actionable_allowed": actionable,
        "human_review_required": human_review,
        "qa_summary": qa_summary,
    }

    # Persist
    cur.execute("""
        INSERT INTO portfolio_level_qa_history
            (portfolio_value, projected_annual_income, minimum_income_target, target_income,
             stretch_income, income_gap, group_allocations, group_cap_violations,
             income_floor_status, concentration_warnings, cross_symbol_conflicts,
             actionable_allowed, human_review_required, qa_summary)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
    """, (total_portfolio, total_income, minimum, target, stretch, gap,
          json.dumps(group_allocs, default=str), json.dumps(violations, default=str),
          income_floor, json.dumps(concentration_warnings, default=str),
          json.dumps(cross_conflicts, default=str), actionable, human_review, qa_summary))

    # Intelligence event
    cur.execute("""
        INSERT INTO portfolio_intelligence_events (event_type, severity, source, payload)
        VALUES ('portfolio_qa', %s, 'portfolio_level_qa.py', %s)
    """, ("warning" if violations else "info",
          json.dumps({"violations": len(violations), "concentration": len(concentration_warnings),
                      "income_floor": income_floor, "gap": gap}, default=str)))

    conn.commit()
    conn.close()
    alert_critical_violations(result)
    return result


DEDUPE_FILE = STATE_DIR / "portfolio_qa_critical_alert_dedupe.json"
DEDUPE_HOURS = 24


def _critical_key(critical: list) -> str:
    return ",".join(sorted(str(v.get("group") or "") for v in critical))


def _deduped_recent(key: str, *, now=None, path=None, window_hours: int = DEDUPE_HOURS) -> bool:
    p = Path(path) if path is not None else DEDUPE_FILE
    if not p.is_file():
        return False
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return False
    if str(data.get("key") or "") != str(key):
        return False
    ts = data.get("sent_at")
    if not ts:
        return False
    try:
        sent = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except ValueError:
        return False
    if sent.tzinfo is None:
        sent = sent.replace(tzinfo=timezone.utc)
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    return (now - sent) < timedelta(hours=int(window_hours))


def _mark_sent(key: str, *, now=None, path=None) -> None:
    p = Path(path) if path is not None else DEDUPE_FILE
    now = now or datetime.now(timezone.utc)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({
        "key": key,
        "sent_at": now.isoformat(),
        "channel": "existing_ops_alert",
        "financial_product": False,
    }), encoding="utf-8")


def alert_critical_violations(result: dict, *, dedupe_path=None, now=None) -> bool:
    """A `severity: critical` group-cap breach (hard-cap exceeded) previously
    reached only logs/portfolio_qa.log and portfolio_intelligence_events —
    nothing forwarded it to a human. A live core_compounders breach at
    86.1-86.2% against a 40-60% target sat there, tagged critical, across
    multiple consecutive daily runs with zero alert. See
    docs/audits/CIO_PLATFORM_REMEDIATION_2026-08-27.md (Fix C5).

    Uses the existing `telegram_alert.send_telegram` ops chokepoint (not a
    new financial Telegram product). Same-key alerts are 24h-deduped.

    Returns whether an alert was sent, so callers/tests can assert on it
    without depending on Telegram actually being configured."""
    critical = [v for v in (result.get("group_cap_violations") or []) if v.get("severity") == "critical"]
    if not critical:
        return False
    key = _critical_key(critical)
    if _deduped_recent(key, now=now, path=dedupe_path):
        print("  [portfolio-qa] critical alert suppressed (24h dedupe)")
        return False
    lines = [f"⚠️ Portfolio QA: {len(critical)} CRITICAL hard-cap breach(es)"]
    for v in critical:
        lines.append(f"  • {v['group']}: {v['actual']:.1f}% (hard cap {v['hard_cap']:.0f}%)")
    if result.get("qa_summary"):
        lines.append("")
        lines.append(result["qa_summary"])
    message = "\n".join(lines)
    try:
        from telegram_alert import send_telegram
        send_telegram(message)
        _mark_sent(key, now=now, path=dedupe_path)
        return True
    except Exception as exc:
        # A failed alert must not fail the QA run itself — but it must not be
        # silent either, or this fix regresses to the exact gap it closes.
        print(f"  [portfolio-qa] ALERT DELIVERY FAILED ({type(exc).__name__}: {exc}); "
              f"critical violation was: {message}")
        return False


def _alert_crash(exc: Exception) -> None:
    """A prior FileNotFoundError on a missing .env killed a run entirely with
    no alert — same gap as alert_critical_violations, for the case where the
    QA check never even got to run. Best-effort: never let alerting itself
    mask the original failure."""
    try:
        from telegram_alert import send_telegram
        send_telegram(f"\U0001f6a8 portfolio_level_qa.py CRASHED: "
                      f"{type(exc).__name__}: {str(exc)[:300]}")
    except Exception:
        pass


if __name__ == "__main__":
    try:
        result = evaluate_portfolio_qa()
    except Exception as exc:
        _alert_crash(exc)
        raise
    if "--json" in sys.argv:
        print(json.dumps(result, indent=2, default=str))
    else:
        print(f"[portfolio-qa] {result['qa_summary']}")
        for gid, g in result["group_allocations"].items():
            print(f"  {gid:30} {g['pct']:>5.1f}% (target {g['target']}) [{g['status']}]")
        if result["group_cap_violations"]:
            print(f"  Violations: {len(result['group_cap_violations'])}")
            for v in result["group_cap_violations"]:
                print(f"    {v['group']}: {v['actual']:.1f}% ({v['severity']})")
        if result["concentration_warnings"]:
            print(f"  Concentration warnings: {len(result['concentration_warnings'])}")
