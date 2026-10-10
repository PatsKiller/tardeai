#!/usr/bin/env python3
"""materialize_income_engine.py — Compute income profiles, layer allocations, and goal progress.

Reads holdings, enrichment, and known dividend data to produce:
- Per-symbol income_asset_profiles (yield, income, layer, payout safety)
- Portfolio layer allocation vs targets
- Income goal progress vs minimum/target/stretch

Usage:
    python3 scripts/materialize_income_engine.py [--json] [--dry-run]

--dry-run (n8n refactor wave 1, 2026-10-10): opens the DB session READ ONLY, computes every
profile, scenario and layer, prints the summary and what it would write, and returns before
``_persist`` (the only writer of income_asset_profiles / income_projection_history) is reachable.
A real run writes ``<state_root>/data/runtime/materialize-income-engine_last.json``
(LaneRunReceipt@v1; ok_at only on success) and exits 1 if it failed.
"""

import json, os, sys
from datetime import datetime, date
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _resolve_state_dir() -> Path:
    """Served holdings dir (persistent-state first, AGENTS.md §9.4), not whatever checkout runs this.

    In a release dir ``data/portfolios/state`` is a symlink into persistent-state, so this resolves to
    the same file as before; from a worktree/dev tree it reads the served copy instead of a stale or
    absent checkout copy (2026-10-10, n8n refactor wave 1)."""
    try:
        if str(PROJECT_ROOT) not in sys.path:
            sys.path.append(str(PROJECT_ROOT))
        from scripts.lib.persistent_state_root import portfolio_state_write_targets

        return portfolio_state_write_targets(PROJECT_ROOT)[0]
    except Exception:  # noqa: BLE001 — resolution layer unavailable: the historical checkout path
        return PROJECT_ROOT / "data" / "portfolios" / "state"


STATE_DIR = _resolve_state_dir()

# ── Known dividend data (Finviz doesn't provide yield) ──────────────
# Source: public data as of April 2026. Updated manually or via future API.
# annual_div = annual dividend per share, yield = approximate current yield %

KNOWN_DIVIDENDS = {
    # Core Compounders
    "SCHD": {
        "annual_div": 0.98,
        "yield_pct": 3.14,
        "growth_5yr": 12.0,
        "payout": "safe",
        "reliability": "high",
        "expense": 0.06,
    },
    "DGRO": {
        "annual_div": 1.25,
        "yield_pct": 2.35,
        "growth_5yr": 10.5,
        "payout": "safe",
        "reliability": "high",
        "expense": 0.08,
    },
    "VIG": {
        "annual_div": 2.90,
        "yield_pct": 1.70,
        "growth_5yr": 8.0,
        "payout": "safe",
        "reliability": "high",
        "expense": 0.06,
    },
    "SCHG": {
        "annual_div": 0.38,
        "yield_pct": 0.15,
        "growth_5yr": 5.0,
        "payout": "safe",
        "reliability": "medium",
        "expense": 0.04,
    },
    "V": {
        "annual_div": 2.36,
        "yield_pct": 0.72,
        "growth_5yr": 16.0,
        "payout": "safe",
        "reliability": "high",
        "expense": None,
    },
    # Income Generators
    "JEPI": {
        "annual_div": 4.50,
        "yield_pct": 7.85,
        "growth_5yr": None,
        "payout": "moderate",
        "reliability": "high",
        "expense": 0.35,
    },
    "JEPQ": {
        "annual_div": 4.80,
        "yield_pct": 9.20,
        "growth_5yr": None,
        "payout": "moderate",
        "reliability": "medium",
        "expense": 0.35,
    },
    "BND": {
        "annual_div": 2.50,
        "yield_pct": 3.40,
        "growth_5yr": None,
        "payout": "safe",
        "reliability": "high",
        "expense": 0.03,
    },
    "HTGC": {
        "annual_div": 1.92,
        "yield_pct": 12.38,
        "growth_5yr": 3.0,
        "payout": "at_risk",
        "reliability": "medium",
        "expense": None,
    },
    "PFLT": {
        "annual_div": 1.14,
        "yield_pct": 11.50,
        "growth_5yr": 0.0,
        "payout": "at_risk",
        "reliability": "medium",
        "expense": None,
    },
    "MAIN": {
        "annual_div": 2.76,
        "yield_pct": 5.60,
        "growth_5yr": 4.0,
        "payout": "safe",
        "reliability": "high",
        "expense": None,
    },
    "ARCC": {
        "annual_div": 1.92,
        "yield_pct": 8.80,
        "growth_5yr": 2.0,
        "payout": "moderate",
        "reliability": "high",
        "expense": None,
    },
    "O": {
        "annual_div": 3.10,
        "yield_pct": 5.50,
        "growth_5yr": 3.5,
        "payout": "safe",
        "reliability": "high",
        "expense": None,
    },
    # Growth / Defense (minimal or no dividend)
    "PLTR": {
        "annual_div": 0,
        "yield_pct": 0,
        "growth_5yr": None,
        "payout": "unknown",
        "reliability": "unknown",
        "expense": None,
    },
    "RKLB": {
        "annual_div": 0,
        "yield_pct": 0,
        "growth_5yr": None,
        "payout": "unknown",
        "reliability": "unknown",
        "expense": None,
    },
    "ARKQ": {
        "annual_div": 0.05,
        "yield_pct": 0.05,
        "growth_5yr": None,
        "payout": "unknown",
        "reliability": "low",
        "expense": 0.75,
    },
    "ARKG": {
        "annual_div": 0,
        "yield_pct": 0,
        "growth_5yr": None,
        "payout": "unknown",
        "reliability": "low",
        "expense": 0.75,
    },
    "LMT": {
        "annual_div": 13.20,
        "yield_pct": 2.57,
        "growth_5yr": 7.5,
        "payout": "safe",
        "reliability": "high",
        "expense": None,
    },
    "RTX": {
        "annual_div": 2.36,
        "yield_pct": 1.35,
        "growth_5yr": 7.0,
        "payout": "safe",
        "reliability": "high",
        "expense": None,
    },
    "NOC": {
        "annual_div": 7.40,
        "yield_pct": 1.29,
        "growth_5yr": 8.0,
        "payout": "safe",
        "reliability": "high",
        "expense": None,
    },
    "GD": {
        "annual_div": 5.68,
        "yield_pct": 1.81,
        "growth_5yr": 7.5,
        "payout": "safe",
        "reliability": "high",
        "expense": None,
    },
    "AXON": {
        "annual_div": 0,
        "yield_pct": 0,
        "growth_5yr": None,
        "payout": "unknown",
        "reliability": "unknown",
        "expense": None,
    },
    "AVAV": {
        "annual_div": 0,
        "yield_pct": 0,
        "growth_5yr": None,
        "payout": "unknown",
        "reliability": "unknown",
        "expense": None,
    },
}

# Layer classification rules
LAYER_MAP = {
    # Core Compounders
    "SCHD": "core_compounders",
    "DGRO": "core_compounders",
    "VIG": "core_compounders",
    "SCHG": "core_compounders",
    "V": "core_compounders",
    "MSFT": "core_compounders",
    "NEE": "core_compounders",
    "XLI": "core_compounders",
    "XLB": "core_compounders",
    # Income Generators
    "JEPI": "income_generators",
    "JEPQ": "income_generators",
    "BND": "income_generators",
    "HTGC": "income_generators",
    "PFLT": "income_generators",
    "MAIN": "income_generators",
    "ARCC": "income_generators",
    "O": "income_generators",
    "STAG": "income_generators",
    # Tactical
    "LMT": "tactical",
    "RTX": "tactical",
    "NOC": "tactical",
    "GD": "tactical",
    "HII": "tactical",
    "BAH": "tactical",
    "LDOS": "tactical",
    "KTOS": "tactical",
    "DRS": "tactical",
    "KBR": "tactical",
    "LHX": "tactical",
    "PLTR": "tactical",
    "RKLB": "tactical",
    "ARKQ": "tactical",
    "ARKG": "tactical",
    "AVAV": "tactical",
    "AXON": "tactical",
    "IRDM": "tactical",
}


def _get_conn():
    import psycopg2

    pw = os.environ.get("DB_PASSWORD", "")
    if not pw:
        for line in (PROJECT_ROOT / ".env").read_text().splitlines():
            if line.startswith("DB_PASSWORD="):
                pw = line.split("=", 1)[1].strip()
    return psycopg2.connect(host="localhost", dbname="trade_ai", user="trade_ai", password=pw)


def _infer_layer(symbol: str, strategy_type: str = None, yield_pct: float = 0, db_layer: str = None) -> str:
    """Classify a symbol into a portfolio layer. DB is authoritative. No runtime fallback dicts."""
    if db_layer:
        return db_layer
    # No DB classification — return unknown, do NOT use hard-coded dicts
    print(f"  [income] MISSING: {symbol} has no DB layer — add to ticker_strategy_classifications")
    return "core_compounders"  # Safe default, not a guess from symbol name


def _infer_preferred_account(layer: str, yield_pct: float = 0, db_preferred: str = None) -> str:
    """Determine preferred account type. Uses DB strategy_registry.preferred_accounts_json."""
    if db_preferred:
        return db_preferred
    # Fallback based on layer/yield only (no symbol checks)
    if layer == "income_generators" and yield_pct > 4:
        return "IRA"
    if layer == "core_compounders" and yield_pct < 1:
        return "Roth"
    return "Taxable"


UPSERT_PROFILE_SQL = """
            INSERT INTO income_asset_profiles
                (symbol, layer_id, annual_dividend_per_share, dividend_yield_pct,
                 forward_yield_pct, yield_on_cost_pct, dividend_growth_5yr_pct,
                 payout_safety, income_reliability, expense_ratio_pct,
                 preferred_account, annual_income, portfolio_income_pct,
                 income_goal_contribution_pct, updated_at)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,now())
            ON CONFLICT (symbol) DO UPDATE SET
                layer_id=EXCLUDED.layer_id,
                annual_dividend_per_share=EXCLUDED.annual_dividend_per_share,
                dividend_yield_pct=EXCLUDED.dividend_yield_pct,
                forward_yield_pct=EXCLUDED.forward_yield_pct,
                yield_on_cost_pct=EXCLUDED.yield_on_cost_pct,
                dividend_growth_5yr_pct=EXCLUDED.dividend_growth_5yr_pct,
                payout_safety=EXCLUDED.payout_safety,
                income_reliability=EXCLUDED.income_reliability,
                expense_ratio_pct=EXCLUDED.expense_ratio_pct,
                preferred_account=EXCLUDED.preferred_account,
                annual_income=EXCLUDED.annual_income,
                portfolio_income_pct=EXCLUDED.portfolio_income_pct,
                income_goal_contribution_pct=EXCLUDED.income_goal_contribution_pct,
                updated_at=now()
        """

INSERT_PROJECTION_SQL = """
        INSERT INTO income_projection_history
            (snapshot_date, total_annual_income, forward_annual_income,
             minimum_goal_pct, target_goal_pct, stretch_goal_pct,
             income_gap_to_minimum, income_gap_to_target,
             top_contributors, layer_breakdown)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
    """


def _persist(conn, cur, profiles, projection_params):
    """The ONLY writer in this script: upsert the profiles, append the projection, commit."""
    for p in profiles:
        cur.execute(
            UPSERT_PROFILE_SQL,
            (
                p["symbol"],
                p["layer_id"],
                p["annual_dividend_per_share"],
                p["dividend_yield_pct"],
                p["forward_yield_pct"],
                p["yield_on_cost_pct"],
                p["dividend_growth_5yr_pct"],
                p["payout_safety"],
                p["income_reliability"],
                p["expense_ratio_pct"],
                p["preferred_account"],
                p["annual_income"],
                p["portfolio_income_pct"],
                p["income_goal_contribution_pct"],
            ),
        )
    cur.execute(INSERT_PROJECTION_SQL, projection_params)
    conn.commit()


def materialize(dry_run=False):
    conn = _get_conn()
    if dry_run:
        # Structural: Postgres refuses any write on a read-only session (AGENTS.md §6).
        conn.set_session(readonly=True)
    import psycopg2.extras

    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    # Load holdings
    holdings = json.loads((STATE_DIR / "holdings.json").read_text()) if (STATE_DIR / "holdings.json").exists() else {}
    acct_summaries = holdings.get("account_summaries", {})
    total_portfolio = sum(info.get("total_value", 0) for info in acct_summaries.values())

    # Aggregate holdings by symbol
    sym_data = {}
    for h in holdings.get("holdings", []):
        sym = h.get("symbol", "")
        if not sym or h.get("is_cash"):
            continue
        if sym not in sym_data:
            sym_data[sym] = {"shares": 0, "market_value": 0, "cost_basis": 0}
        sym_data[sym]["shares"] += float(h.get("shares", 0) or 0)
        sym_data[sym]["market_value"] += float(h.get("market_value", 0) or 0)
        sym_data[sym]["cost_basis"] += float(h.get("cost_basis", 0) or 0)

    # Get strategy types from strategy cards
    cur.execute("SELECT symbol, strategy_type FROM watchlist_strategy_cards")
    strategy_map = {r["symbol"]: r["strategy_type"] for r in cur.fetchall()}

    # Get income goals
    cur.execute("SELECT * FROM portfolio_income_goals LIMIT 1")
    goals = cur.fetchone() or {}
    target_income = float(goals.get("target_income", 55000))
    min_income = float(goals.get("minimum_income_target", 37500))
    stretch_income = float(goals.get("stretch_income_target", 67500))

    # Compute per-symbol income profiles
    total_annual_income = 0
    profiles = []

    for sym, data in sym_data.items():
        shares = data["shares"]
        mv = data["market_value"]
        cost = data["cost_basis"]

        # Dividend data — DB first (ticker_dividend_data), then in-code seed fallback
        cur.execute("SELECT * FROM ticker_dividend_data WHERE symbol=%s", (sym,))
        db_div = cur.fetchone()
        if db_div:
            annual_div = float(db_div.get("annual_dividend_per_share", 0) or 0)
            yield_pct = float(db_div.get("dividend_yield_pct", 0) or 0)
            growth_5yr = float(db_div["dividend_growth_5y"]) if db_div.get("dividend_growth_5y") is not None else None
            _ps = float(db_div.get("payout_safety_score", 0) or 0)
            payout = "safe" if _ps >= 0.8 else "moderate" if _ps >= 0.5 else "at_risk" if _ps > 0 else "unknown"
            _ir = float(db_div.get("income_reliability_score", 0) or 0)
            reliability = "high" if _ir >= 0.8 else "medium" if _ir >= 0.5 else "low" if _ir > 0 else "unknown"
            expense = None  # Not in dividend table
        else:
            # Fallback to in-code seed (logs warning)
            div_info = KNOWN_DIVIDENDS.get(sym, {})
            if div_info:
                print(
                    f"  [income] WARNING: {sym} using in-code KNOWN_DIVIDENDS fallback — migrate to ticker_dividend_data"
                )
            annual_div = div_info.get("annual_div", 0)
            yield_pct = div_info.get("yield_pct", 0)
            growth_5yr = div_info.get("growth_5yr")
            payout = div_info.get("payout", "unknown")
            reliability = div_info.get("reliability", "unknown")
            expense = div_info.get("expense")

        # Compute income
        annual_income = round(shares * annual_div, 2) if annual_div else 0
        total_annual_income += annual_income

        # Yield on cost
        yoc = round(annual_income / cost * 100, 2) if cost > 0 and annual_income > 0 else None

        # Forward yield estimate (assume dividend grows at 5yr rate next year)
        fwd_yield = None
        if yield_pct and growth_5yr and growth_5yr > 0:
            fwd_yield = round(yield_pct * (1 + growth_5yr / 100), 2)
        elif yield_pct:
            fwd_yield = yield_pct

        # Layer — DB classification first, then fallback
        strategy_type = strategy_map.get(sym)
        cur.execute(
            "SELECT sr.layer_id FROM ticker_strategy_classifications tsc JOIN strategy_registry sr ON sr.strategy_type=tsc.strategy_type WHERE tsc.symbol=%s AND tsc.active=TRUE",
            (sym,),
        )
        db_layer_row = cur.fetchone()
        db_layer = db_layer_row["layer_id"] if db_layer_row else None
        layer = _infer_layer(sym, strategy_type, yield_pct, db_layer)
        # Preferred account from DB strategy_registry
        cur.execute(
            "SELECT sr.preferred_accounts_json FROM ticker_strategy_classifications tsc JOIN strategy_registry sr ON sr.strategy_type=tsc.strategy_type WHERE tsc.symbol=%s AND tsc.active=TRUE",
            (sym,),
        )
        _pa_row = cur.fetchone()
        _db_preferred = None
        if _pa_row and _pa_row.get("preferred_accounts_json"):
            _pa_list = _pa_row["preferred_accounts_json"]
            if isinstance(_pa_list, list) and _pa_list:
                _db_preferred = _pa_list[0]  # First preferred
            elif isinstance(_pa_list, str):
                import json as _j2

                _pa_list = _j2.loads(_pa_list)
                _db_preferred = _pa_list[0] if _pa_list else None
        preferred_account = _infer_preferred_account(layer, yield_pct, _db_preferred)

        profiles.append(
            {
                "symbol": sym,
                "layer_id": layer,
                "annual_dividend_per_share": annual_div or None,
                "dividend_yield_pct": yield_pct or None,
                "forward_yield_pct": fwd_yield,
                "yield_on_cost_pct": yoc,
                "dividend_growth_5yr_pct": growth_5yr,
                "payout_ratio_pct": None,  # Would need earnings data
                "payout_safety": payout,
                "income_reliability": reliability,
                "expense_ratio_pct": expense,
                "preferred_account": preferred_account,
                "annual_income": annual_income,
                "shares": shares,
                "market_value": mv,
            }
        )

    # Compute portfolio income percentages
    for p in profiles:
        p["portfolio_income_pct"] = (
            round(p["annual_income"] / total_annual_income * 100, 2) if total_annual_income > 0 else 0
        )
        p["income_goal_contribution_pct"] = (
            round(p["annual_income"] / target_income * 100, 2) if target_income > 0 else 0
        )

    # Compute layer allocations
    layer_totals = {}
    for p in profiles:
        lid = p["layer_id"]
        layer_totals.setdefault(lid, {"value": 0, "income": 0, "count": 0})
        layer_totals[lid]["value"] += p["market_value"]
        layer_totals[lid]["income"] += p["annual_income"]
        layer_totals[lid]["count"] += 1

    # Income projection scenarios — NOT predictions, scenario-based estimates
    # Conservative: 0% dividend growth (flat), no reinvestment
    # Base: historical growth rate continues, no reinvestment
    # Aggressive: historical growth + reinvestment compounding
    # Build div data lookup from DB for scenarios
    _div_db = {}
    cur.execute("SELECT symbol, annual_dividend_per_share, dividend_growth_5y FROM ticker_dividend_data")
    for _dr in cur.fetchall():
        _div_db[_dr["symbol"]] = {
            "annual_div": float(_dr.get("annual_dividend_per_share", 0) or 0),
            "growth_5yr": float(_dr.get("dividend_growth_5y", 0) or 0)
            if _dr.get("dividend_growth_5y") is not None
            else 0,
        }

    def _scenario_income(growth_haircut: float, reinvest: bool) -> float:
        total = 0
        for p in profiles:
            div_info = _div_db.get(p["symbol"], {})
            annual_div = div_info.get("annual_div", 0)
            growth = (div_info.get("growth_5yr", 0) or 0) * growth_haircut
            fwd_div = annual_div * (1 + growth / 100)
            shares = p["shares"]
            if reinvest and p["market_value"] > 0 and annual_div > 0:
                # Approximate 1 year of DRIP at current price
                price = p["market_value"] / shares if shares > 0 else 1
                reinvested_shares = (shares * annual_div) / price
                shares += reinvested_shares
            total += shares * fwd_div
        return round(total, 2)

    scenario_conservative = _scenario_income(0.0, False)  # No growth, no DRIP
    scenario_base = _scenario_income(1.0, False)  # Historical growth, no DRIP
    scenario_aggressive = _scenario_income(1.0, True)  # Historical growth + DRIP

    forward_income = scenario_base  # Base case for goal tracking

    top_contributors = sorted(profiles, key=lambda p: p["annual_income"], reverse=True)[:10]

    projection_params = (
        date.today(),
        round(total_annual_income, 2),
        round(forward_income, 2),
        round(total_annual_income / min_income * 100, 1) if min_income > 0 else 0,
        round(total_annual_income / target_income * 100, 1) if target_income > 0 else 0,
        round(total_annual_income / stretch_income * 100, 1) if stretch_income > 0 else 0,
        round(max(0, min_income - total_annual_income), 2),
        round(max(0, target_income - total_annual_income), 2),
        json.dumps(
            [
                {"symbol": p["symbol"], "income": p["annual_income"], "pct": p["portfolio_income_pct"]}
                for p in top_contributors
            ]
        ),
        json.dumps(
            {
                lid: {
                    "value": round(v["value"], 2),
                    "pct": round(v["value"] / total_portfolio * 100, 1) if total_portfolio > 0 else 0,
                    "income": round(v["income"], 2),
                    "count": v["count"],
                }
                for lid, v in layer_totals.items()
            }
        ),
    )

    if dry_run:
        conn.rollback()
        conn.close()
        print(
            f"[income-engine] DRY-RUN: would upsert {len(profiles)} income_asset_profiles rows "
            f"and append 1 income_projection_history row for {date.today()}"
        )
    else:
        _persist(conn, cur, profiles, projection_params)
        conn.close()

    # Print summary
    print(f"[income-engine] {len(profiles)} symbols profiled")
    print(f"  Annual income: ${total_annual_income:,.0f}")
    print("  Scenarios (1-year forward estimate, NOT prediction):")
    print(f"    Conservative (0% growth, no DRIP):  ${scenario_conservative:,.0f}/yr")
    print(f"    Base (historical growth, no DRIP):  ${scenario_base:,.0f}/yr")
    print(f"    Aggressive (growth + DRIP):         ${scenario_aggressive:,.0f}/yr")
    print(f"  Goal progress: {total_annual_income / target_income * 100:.1f}% of ${target_income:,.0f} target")
    print(f"  Income gap to target: ${max(0, target_income - total_annual_income):,.0f}")
    print()
    print("  Layer allocations:")
    for lid, v in sorted(layer_totals.items()):
        pct = v["value"] / total_portfolio * 100 if total_portfolio > 0 else 0
        print(f"    {lid:25} ${v['value']:>12,.0f}  {pct:>5.1f}%  income=${v['income']:>8,.0f}  ({v['count']} symbols)")
    print()
    print("  Top income contributors:")
    for p in top_contributors[:5]:
        if p["annual_income"] > 0:
            print(
                f"    {p['symbol']:>6}  ${p['annual_income']:>8,.0f}/yr  yield={p.get('dividend_yield_pct') or 0:.1f}%  {p['income_goal_contribution_pct']:.1f}% of target"
            )

    return {
        "total_annual_income": total_annual_income,
        "scenarios": {
            "conservative": scenario_conservative,
            "base": scenario_base,
            "aggressive": scenario_aggressive,
            "assumptions": {
                "conservative": "0% dividend growth, no reinvestment",
                "base": "Historical 5-year dividend growth rate continues, no reinvestment",
                "aggressive": "Historical growth rate + full DRIP reinvestment at current prices",
            },
            "disclaimer": "Scenario estimates based on historical behavior. Past performance is not a guarantee of future results.",
        },
        "forward_income": forward_income,
        "target_income": target_income,
        "goal_pct": round(total_annual_income / target_income * 100, 1),
        "income_gap": max(0, target_income - total_annual_income),
        "profiles": len(profiles),
        "layers": layer_totals,
        "dry_run": bool(dry_run),
    }


LANE_ID = "materialize-income-engine"


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    dry_run = "--dry-run" in argv
    sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
    from lib.lane_last_receipt import dry_run_report, now_iso, write_lane_receipt

    started = now_iso()
    try:
        result = materialize(dry_run=dry_run)
    except Exception as exc:  # noqa: BLE001 — recorded, then a non-zero exit (never swallowed)
        import traceback

        traceback.print_exc()
        if not dry_run:
            write_lane_receipt(
                LANE_ID,
                ok=False,
                started_at=started,
                script="materialize_income_engine.py",
                exit_code=1,
                summary={"error": f"{type(exc).__name__}: {str(exc)[:200]}"},
            )
        return 1
    if "--json" in argv:
        print(json.dumps(result, indent=2, default=str))
    summary = {
        k: result.get(k)
        for k in (
            "profiles",
            "total_annual_income",
            "forward_income",
            "target_income",
            "goal_pct",
            "income_gap",
            "dry_run",
        )
    }
    if dry_run:
        dry_run_report(
            LANE_ID,
            summary,
            would_write=[
                f"income_asset_profiles: upsert {result.get('profiles')} rows",
                "income_projection_history: append 1 row",
            ],
        )
        return 0
    write_lane_receipt(
        LANE_ID, ok=True, started_at=started, script="materialize_income_engine.py", exit_code=0, summary=summary
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
