#!/usr/bin/env python3
"""P0-5: dry-run simulator for the momentum_scalp PAPER path.

Proves that a valid, verified, in-window, liquid momentum_scalp candidate WOULD reach
paper-trade creation — and that invalid candidates are correctly blocked/deferred — using the
real deterministic gate functions (route policy, config validator, intraday window, ATM
expiry, liquidity prescreen). NO broker orders, NO database writes; the quote provider is
mocked in-process.

    python3 scripts/simulate_momentum_scalp_paper_path.py --json
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

# A fixed reference "now": 2026-06-29 09:30 ET == 13:30 UTC (inside the 06:00–12:00 ET window).
NOW_UTC = datetime(2026, 6, 29, 13, 30, tzinfo=timezone.utc)


def _et_minutes(dt_utc):
    try:
        import zoneinfo
        et = dt_utc.astimezone(zoneinfo.ZoneInfo("America/New_York"))
        return et.hour * 60 + et.minute
    except Exception:
        return None


def _in_window(now_utc):
    """Deterministic check of now against momentum_scalp.intraday_execution window."""
    import yaml
    cfg = yaml.safe_load((ROOT / "config" / "strategies" / "momentum_scalp.yaml").read_text()) or {}
    win = (cfg.get("intraday_execution") or {}).get("trading_window_et") or {}
    def m(s):
        h, mi = str(s).split(":")
        return int(h) * 60 + int(mi)
    start, end = m(win.get("start", "06:00")), m(win.get("end", "12:00"))
    cur = _et_minutes(now_utc)
    return cur is not None and start <= cur <= end, (start, end, cur)


def _mock_quote_provider(fresh: bool, present: bool = True):
    import market_quote_provider as mqp
    def cf(symbol, strategy_id=None):
        if not present:
            return {"ok": False, "reason": "no_quote"}
        return {"ok": fresh, "reason": "fresh" if fresh else "stale (1100min)", "age_minutes": 1 if fresh else 1100}
    def bq(symbol):
        if not present:
            return {}
        return {"spread_pct": 1.0, "last_price": 5.0, "day_volume": 2_000_000}
    mqp.check_fresh_quote, mqp.get_best_quote = cf, bq


def simulate(spec: dict) -> dict:
    """Run one synthetic candidate through the paper-path gates. spec keys:
    verified, rvol, float_m, price, gap_pct, quote_fresh, quote_present, in_window, age_minutes."""
    from social_route_policy import route_social_candidate
    from strategy_config_validator import validate_strategy_config
    from atm_auto_approver import resolve_atm_expiry
    from auto_proposal_generator import _liquidity_prescreen

    gates_passed, blocked_at, reason = [], None, None
    result = "WOULD_CREATE_PAPER_TRADE"

    candidate = {"symbol": spec.get("symbol", "SCLP"), "mention_count": 25,
                 "sources": ["stocktwits"], "strategy_tags": [],
                 "sample_content": spec.get("sample_content", "FDA approval news")}
    finviz = {"price": spec.get("price", 5.0), "rvol": spec.get("rvol", 7.0),
              "float_m": spec.get("float_m", 8.0), "gap_pct": spec.get("gap_pct", 4.0)}
    catalyst = {"catalyst_verified": spec.get("verified", True), "catalyst_source": "news"}

    # 1. Route policy.
    route = route_social_candidate(candidate, finviz, catalyst, trace_id="sim-trace")
    if route["actionability"] != "GO" or route["route"] != "momentum_scalp":
        return {"result": "WATCH_WAIT" if route["social_only"] else "BLOCKED",
                "blocked_at": "route_policy", "reason": f"route={route['route']} act={route['actionability']}",
                "gates_passed": gates_passed, "route": route}
    gates_passed.append("route_policy:momentum_scalp/GO")

    # 2. Strategy config consistency.
    cfg = validate_strategy_config("momentum_scalp")
    if not cfg["ok"]:
        return {"result": "BLOCKED", "blocked_at": "strategy_config", "reason": "config drift",
                "gates_passed": gates_passed}
    gates_passed.append("strategy_config:consistent")

    # 3. Intraday window.
    in_win, win = _in_window(NOW_UTC if spec.get("in_window", True)
                             else NOW_UTC.replace(hour=20))  # 16:00 ET = outside
    if not in_win:
        return {"result": "BLOCKED", "blocked_at": "intraday_window",
                "reason": f"outside 06:00–12:00 ET window {win}", "gates_passed": gates_passed}
    gates_passed.append("intraday_window:inside")

    # 4. ATM expiry (fresh proposal not expired; stale/expired blocked).
    age = spec.get("age_minutes", 5)
    created = NOW_UTC - timedelta(minutes=age)
    exp = resolve_atm_expiry("momentum_scalp", created, None, now=NOW_UTC)
    if exp["action"] != "ok":
        return {"result": "BLOCKED", "blocked_at": "atm_expiry",
                "reason": f"{exp['action']}:{exp.get('reason')}", "gates_passed": gates_passed}
    gates_passed.append("atm_expiry:fresh")

    # 5. Liquidity prescreen (mocked quote).
    _mock_quote_provider(fresh=spec.get("quote_fresh", True), present=spec.get("quote_present", True))
    rules = {"liquidity_prescreen": {"enabled": True, "max_spread_pct": 5.0,
                                     "min_day_volume_shares": 25000, "min_dollar_day_volume": 100000}}
    ok, lreason = _liquidity_prescreen(candidate["symbol"], rules, "momentum_scalp")
    if not ok:
        return {"result": "DEFERRED" if "DEFER" in lreason else "BLOCKED", "blocked_at": "liquidity",
                "reason": lreason, "gates_passed": gates_passed}
    gates_passed.append("liquidity:ok")

    # 6. Paper risk gate (deterministic R:R check; paper-mode, no DB).
    entry, stop, target = 5.0, 4.6, 5.8
    rr = (target - entry) / (entry - stop) if entry > stop else 0
    if rr < 1.5:
        return {"result": "BLOCKED", "blocked_at": "risk_gate", "reason": f"R:R {rr:.2f} < 1.5",
                "gates_passed": gates_passed}
    gates_passed.append(f"risk_gate:RR={rr:.2f}")

    # WOULD create the paper_trade — show the payload shape (NOT written).
    payload = {"strategy_id": "momentum_scalp", "symbol": candidate["symbol"], "account": "alpaca_paper",
               "entry_price": entry, "stop_loss": stop, "target_1": target, "side": "long",
               "discovery_trace_id": route["trace_id"], "status": "would_open(paper)",
               "execution_environment": "paper"}
    return {"result": result, "blocked_at": None, "reason": "all gates passed",
            "gates_passed": gates_passed, "would_create_paper_trade": payload}


SCENARIOS = {
    "valid_in_window": {},
    "expired": {"age_minutes": 45},
    "social_only_unverified": {"verified": False},
    "liquidity_unknown": {"quote_present": False},
    "stale_quote": {"quote_fresh": False},
    "out_of_window": {"in_window": False},
}


def run_all() -> dict:
    results = {name: simulate(spec) for name, spec in SCENARIOS.items()}
    return {
        "ok": True,
        "generated_at": NOW_UTC.isoformat(),
        "results": {k: {"result": v["result"], "blocked_at": v["blocked_at"],
                        "reason": v["reason"], "gates_passed": v["gates_passed"]}
                    for k, v in results.items()},
        "valid_payload": results["valid_in_window"].get("would_create_paper_trade"),
        "note": "Dry-run simulation. NO broker orders, NO database writes. Quote provider mocked. "
                "Operator/2FA path unchanged; this proves only that a valid candidate WOULD reach "
                "paper-trade creation if generated with a fresh in-window quote.",
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--scenario", default=None)
    args = ap.parse_args()
    if args.scenario:
        print(json.dumps(simulate(SCENARIOS.get(args.scenario, {})), indent=2, default=str))
        return 0
    rep = run_all()
    if args.json:
        print(json.dumps(rep, indent=2, default=str))
    else:
        for k, v in rep["results"].items():
            print(f"  {k:24} -> {v['result']:24} ({v['blocked_at'] or 'all gates'})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
