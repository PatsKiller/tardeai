#!/usr/bin/env python3
"""Command Center data consistency checker.

Verifies portfolio totals, account integrity, income data, CIO dedup,
and freshness across dashboard endpoints.

Usage: python3 scripts/check_command_center_data_consistency.py
"""
import json, sys, urllib.request
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
STATE_DIR = PROJECT_ROOT / "data" / "portfolios" / "state"
API_BASE = "http://localhost:7777"

results = []


def check(name, status, detail):
    results.append((status, name, detail))
    icon = {"PASS": "✅", "FAIL": "❌", "WARN": "⚠️"}.get(status, "?")
    print(f"  {icon} [{status}] {name}: {detail}")


def api_get(path):
    try:
        with urllib.request.urlopen(f"{API_BASE}{path}", timeout=15) as r:
            return json.loads(r.read())
    except Exception as e:
        return {"error": str(e)}


def check_canonical_total():
    h = json.load(open(STATE_DIR / "holdings.json"))
    canonical = h.get("portfolio_totals", {}).get("total_value", 0)
    count = len(h.get("holdings", []))
    check("Canonical holdings", "PASS" if canonical > 1_000_000 else "FAIL",
          f"${canonical:,.2f} / {count} positions")
    return canonical, count


def check_phantom_accounts():
    h = json.load(open(STATE_DIR / "holdings.json"))
    summaries = h.get("account_summaries", {})
    phantoms = [k for k, v in summaries.items()
                if float(v.get("total_value", v.get("market_value", 0)) or 0) <= 0]
    if phantoms:
        check("Phantom accounts (file)", "WARN", f"Zero-value accounts in holdings.json: {phantoms} (filtered by API)")
    else:
        check("Phantom accounts (file)", "PASS", "No zero-value accounts")

    # Check API
    r = api_get("/api/v2/attribution")
    if "error" not in r:
        data = r.get("data", r)
        accounts = data.get("accounts", {})
        api_phantoms = [k for k, v in accounts.items()
                        if float(v.get("total_value", 0) or 0) <= 0]
        if api_phantoms:
            check("Attribution API phantoms", "FAIL", f"API returns zero-value: {api_phantoms}")
        else:
            check("Attribution API phantoms", "PASS", f"{len(accounts)} accounts, all non-zero")


def check_rebalance_income():
    r = api_get("/api/v2/rebalance")
    if "error" in r:
        check("Rebalance income", "FAIL", f"API error: {r['error']}")
        return
    data = r.get("data", r)
    cv = data.get("computed_values", {})
    income = cv.get("income_current", 0)
    div = json.load(open(STATE_DIR / "dividend_calendar.json")) if (STATE_DIR / "dividend_calendar.json").exists() else {}
    expected = float(div.get("total_annual", 0))
    if income == 0 and expected > 0:
        check("Rebalance income", "FAIL", f"income_current=${income} but dividend_calendar has ${expected:,.0f}")
    elif income > 0:
        check("Rebalance income", "PASS", f"income_current=${income:,.0f}")
    else:
        check("Rebalance income", "WARN", f"income_current=${income}, no dividend_calendar data")


def check_cio_duplicates():
    r = api_get("/api/v2/cio-decisions")
    if "error" in r:
        check("CIO duplicates", "FAIL", f"API error: {r['error']}")
        return
    data = r.get("data", r)
    decisions = data.get("decisions", [])
    symbols = [d.get("symbol", "") for d in decisions]
    dupes = [s for s in set(symbols) if symbols.count(s) > 1]
    if dupes:
        check("CIO duplicates", "FAIL", f"Duplicate symbols: {dupes}")
    else:
        check("CIO duplicates", "PASS", f"{len(decisions)} decisions, no duplicates")


def check_retirement_delta(canonical):
    r = api_get("/api/v2/retirement")
    if "error" in r:
        check("Retirement delta", "FAIL", f"API error: {r['error']}")
        return
    data = r.get("data", r)
    ret_total = data.get("canonical_total") or data.get("total", 0)
    snapshot_note = data.get("snapshot_note")
    delta = abs(canonical - float(ret_total or 0))
    if delta > 5000:
        check("Retirement delta", "WARN", f"Retirement ${ret_total:,.0f} vs canonical ${canonical:,.0f} (delta ${delta:,.0f})")
    else:
        check("Retirement delta", "PASS", f"Within tolerance (delta ${delta:,.0f})")


def check_ai_analyst_freshness():
    r = api_get("/api/v2/ai-analyst")
    if "error" in r:
        check("AI Analyst freshness", "FAIL", f"API error: {r['error']}")
        return
    data = r.get("data", r)
    is_stale = data.get("is_stale")
    gen = data.get("generated_at")
    if is_stale is True:
        check("AI Analyst freshness", "WARN", f"Stale (generated_at={gen})")
    elif is_stale is False:
        check("AI Analyst freshness", "PASS", f"Fresh (generated_at={gen})")
    else:
        check("AI Analyst freshness", "WARN", f"No staleness indicator (generated_at={gen})")


def check_snapshot_sources():
    for endpoint, name in [("/api/v2/command", "Command"), ("/api/v2/rebalance", "Rebalance"), ("/api/v2/retirement", "Retirement")]:
        r = api_get(endpoint)
        if "error" in r:
            continue
        data = r.get("data", r)
        src = data.get("snapshot_source")
        if src:
            check(f"{name} snapshot_source", "PASS", src)
        else:
            check(f"{name} snapshot_source", "WARN", "No snapshot_source metadata")


def main():
    print("\n=== Command Center Data Consistency Check ===\n")
    canonical, count = check_canonical_total()
    check_phantom_accounts()
    check_rebalance_income()
    check_cio_duplicates()
    check_retirement_delta(canonical)
    check_ai_analyst_freshness()
    check_snapshot_sources()

    print(f"\n=== Summary ===")
    fails = sum(1 for s, _, _ in results if s == "FAIL")
    warns = sum(1 for s, _, _ in results if s == "WARN")
    passes = sum(1 for s, _, _ in results if s == "PASS")
    print(f"  PASS: {passes}  WARN: {warns}  FAIL: {fails}")

    if fails > 0:
        sys.exit(1)
    elif warns > 0:
        sys.exit(2)
    sys.exit(0)


if __name__ == "__main__":
    main()
