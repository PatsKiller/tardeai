"""redeploy_pro_forma — three-state portfolio modeling for redeploy plans (Part D).

For a deploy event + plan:
  PRE-SALE      current holdings with the sold position added back at proceeds value
  POST-SALE     current holdings as they stand (proceeds in cash)
  POST-PLAN     current holdings + exact proposed legs at whole-share quantities

Each state is a real modeled portfolio: sector weights (ETF/fund look-through
applied), asset classes, direct + look-through issuer exposure, income, weighted
expense ratio, weighted beta/volatility, concentration, cash. Deltas and
restoration-by-dimension are computed between states — quantified, never
"restores growth" prose. Advisory only; no fabricated data (missing metrics stay
None and are reported in data_gaps).
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from lib.redeploy_data_truth import STATE, _as_float, _load_json
from lib.redeploy_income import income_snapshot
from lib.redeploy_price_history import (
    annualized_vol_pct,
    beta_vs,
    get_instrument_facts,
    load_closes,
)

ENGINE_VERSION = "pro_forma_1.1.0"
TOP_CONCENTRATION_N = 10


def _holdings() -> list[dict[str, Any]]:
    return _load_json(Path(STATE) / "holdings.json", {}).get("holdings") or []


def _lookthrough() -> dict[str, Any]:
    return _load_json(Path(STATE) / "fund_lookthrough.json", {}) or {}


def _known_fund_symbols() -> set[str]:
    """Symbols known to be fund wrappers from state files (no hardcoded tickers):
    fund_lookthrough.json + fund_holdings_cache.json membership."""
    syms: set[str] = set()
    for fname in ("fund_lookthrough.json", "fund_holdings_cache.json"):
        d = _load_json(Path(STATE) / fname, {}) or {}
        syms.update(str(k).upper() for k in d.keys() if not str(k).startswith("_"))
    return syms


def _is_fund_wrapper(sym: str, facts: dict[str, Any], known_funds: set[str]) -> bool:
    qt = (facts.get("quote_type") or "").upper()
    return qt in ("ETF", "MUTUALFUND") or sym.upper() in known_funds


def _sector_maps() -> tuple[dict, dict]:
    cache = _load_json(Path(STATE) / "sector_cache.json", {}) or {}
    manual = _load_json(Path(STATE) / "manual_sector_map.json", {}) or {}
    return cache, manual


def _sector_of(sym: str, cache: dict, manual: dict) -> str:
    s = cache.get(sym) or manual.get(sym) or {}
    if isinstance(s, dict):
        return str(s.get("sector") or "Unknown")
    return str(s or "Unknown")


class PortfolioState:
    """A modeled portfolio: positions [{symbol, market_value, is_cash}]."""

    def __init__(self, label: str, positions: list[dict[str, Any]]):
        self.label = label
        self.positions = positions

    def total(self) -> float:
        return sum(_as_float(p.get("market_value")) for p in self.positions)


def _current_positions() -> list[dict[str, Any]]:
    return [
        {"symbol": str(h.get("symbol") or "").upper(),
         "market_value": _as_float(h.get("market_value")),
         "is_cash": bool(h.get("is_cash")),
         "account": h.get("account")}
        for h in _holdings()
    ]


def build_states(event: dict[str, Any], plan_legs: list[dict[str, Any]],
                 *, leg_prices: dict[str, float]) -> dict[str, PortfolioState]:
    """Construct the three states. plan_legs: [{ticker, target_dollars, is_reserve}]."""
    sold_sym = str(event.get("symbol") or "").upper()
    proceeds = _as_float(event.get("net_proceeds_usd")) or _as_float(event.get("proceeds_usd"))
    current = _current_positions()

    pre = [dict(p) for p in current]
    pre.append({"symbol": sold_sym, "market_value": proceeds, "is_cash": False,
                "account": event.get("account"), "note": "sold position at proceeds value"})
    # pre-sale: the proceeds cash isn't there yet — remove it from the cash line
    for p in pre:
        if p["is_cash"] and p.get("account") == event.get("account"):
            p["market_value"] = max(0.0, _as_float(p["market_value"]) - proceeds)
            break

    post_sale = [dict(p) for p in current]

    post_plan = [dict(p) for p in current]
    deployed = 0.0
    modeled_legs = []
    for leg in plan_legs:
        if leg.get("is_reserve"):
            continue
        sym = str(leg.get("ticker") or "").upper()
        px = leg_prices.get(sym) or _as_float(leg.get("current_price"))
        dollars = _as_float(leg.get("target_dollars"))
        if px <= 0 or dollars <= 0:
            modeled_legs.append({"ticker": sym, "modeled": False,
                                 "reason": "no price or target dollars"})
            continue
        shares = int(dollars // px)  # whole shares only
        actual = round(shares * px, 2)
        deployed += actual
        modeled_legs.append({"ticker": sym, "modeled": True, "price_used": px,
                             "whole_shares": shares, "modeled_dollars": actual,
                             "residual_vs_target": round(dollars - actual, 2)})
        merged = False
        for p in post_plan:
            if p["symbol"] == sym and not p["is_cash"]:
                p["market_value"] = _as_float(p["market_value"]) + actual
                merged = True
                break
        if not merged:
            post_plan.append({"symbol": sym, "market_value": actual, "is_cash": False,
                              "account": event.get("account")})
    for p in post_plan:
        if p["is_cash"] and p.get("account") == event.get("account"):
            p["market_value"] = max(0.0, _as_float(p["market_value"]) - deployed)
            break

    states = {
        "pre_sale": PortfolioState("pre_sale", pre),
        "post_sale": PortfolioState("post_sale", post_sale),
        "post_plan": PortfolioState("post_plan", post_plan),
    }
    states["_modeled_legs"] = modeled_legs  # type: ignore[assignment]
    states["_deployed"] = round(deployed, 2)  # type: ignore[assignment]
    return states


def analyze_state(cur, state: PortfolioState, *, facts_map: dict, lookthrough: dict,
                  sector_cache: dict, manual_map: dict,
                  bench_closes: list) -> dict[str, Any]:
    total = state.total()
    sectors: dict[str, float] = {}
    issuers: dict[str, float] = {}
    asset_classes: dict[str, float] = {}
    income = 0.0
    weighted_er = 0.0
    er_covered = 0.0
    weighted_beta = 0.0
    beta_covered = 0.0
    cash = 0.0
    data_gaps: list[str] = []
    # defect #17: separated look-through tables
    direct_agg: dict[str, dict[str, Any]] = {}     # symbol -> {dollars, is_fund_wrapper}
    underlying: dict[str, dict[str, Any]] = {}     # issuer -> {direct_usd, indirect_usd, source_funds}
    unresolved: dict[str, dict[str, Any]] = {}     # fund symbol -> row
    known_funds = _known_fund_symbols()
    # defect #8: canonical income model — one snapshot batch per state
    inc_syms = sorted({p["symbol"] for p in state.positions
                       if not p.get("is_cash") and _as_float(p.get("market_value")) > 0})
    income_map = income_snapshot(cur, inc_syms) if inc_syms else {}

    for p in state.positions:
        sym = p["symbol"]
        mv = _as_float(p.get("market_value"))
        if mv <= 0:
            continue
        if p.get("is_cash"):
            cash += mv
            asset_classes["cash"] = asset_classes.get("cash", 0.0) + mv
            continue

        facts = facts_map.get(sym, {})
        lt = lookthrough.get(sym) or {}
        qt = (facts.get("quote_type") or "").upper()
        cat = (facts.get("category") or "").lower()
        if "bond" in cat or sym in ("BND", "AGG", "SHY", "TLT"):
            ac = "fixed_income"
        elif sym in ("SGOV", "BIL"):
            ac = "cash_equivalent"
        elif qt in ("ETF", "MUTUALFUND") or lt:
            ac = "fund_equity"
        else:
            ac = "direct_equity"
        asset_classes[ac] = asset_classes.get(ac, 0.0) + mv

        # sector: look-through when available (fund_lookthrough.json first,
        # then yfinance instrument_facts), direct map otherwise
        lt_sectors = lt.get("sector_weights") or facts.get("sector_weights") or {}
        if ac == "fixed_income" and not lt_sectors:
            sectors["Fixed Income"] = sectors.get("Fixed Income", 0.0) + mv
        elif lt_sectors:
            for sec, wpct in lt_sectors.items():
                sectors[sec] = sectors.get(sec, 0.0) + mv * _as_float(wpct) / 100.0
        else:
            sec = _sector_of(sym, sector_cache, manual_map)
            sectors[sec] = sectors.get(sec, 0.0) + mv

        # DEPRECATED issuer table (mixes fund wrappers with underlying issuers);
        # kept only for backward compat — use direct_positions/underlying_issuers/
        # unresolved_lookthrough instead (defect #17).
        lt_holdings = lt.get("top_holdings") or facts.get("top_holdings") or []
        issuers[sym] = issuers.get(sym, 0.0) + (0.0 if lt_holdings else mv)
        for th in lt_holdings:
            t = str(th.get("ticker") or "").upper()
            w = _as_float(th.get("weight") or th.get("weight_pct"))
            if t and w > 0:
                issuers[t] = issuers.get(t, 0.0) + mv * w / 100.0

        # defect #17: three separated tables — fund wrappers NEVER appear as issuers
        is_fund_wrapper = _is_fund_wrapper(sym, facts, known_funds) or bool(lt)
        d = direct_agg.setdefault(sym, {"symbol": sym, "dollars": 0.0,
                                        "is_fund_wrapper": is_fund_wrapper})
        d["dollars"] += mv
        if is_fund_wrapper:
            resolved_w = 0.0
            for th in lt_holdings:
                t = str(th.get("ticker") or "").upper()
                w = _as_float(th.get("weight") or th.get("weight_pct"))
                if t and w > 0:
                    u = underlying.setdefault(
                        t, {"direct_usd": 0.0, "indirect_usd": 0.0, "source_funds": set()})
                    u["indirect_usd"] += mv * w / 100.0
                    u["source_funds"].add(sym)
                    resolved_w += w
            if resolved_w < 99.5:
                row = unresolved.setdefault(sym, {
                    "symbol": sym, "dollars": 0.0,
                    "lookthrough_coverage_pct": round(min(resolved_w, 100.0), 1),
                    "note": ("no holdings data — excluded from underlying_issuers"
                             if resolved_w <= 0 else
                             f"top-holdings look-through covers {min(resolved_w, 100.0):.1f}% "
                             "of the fund — remainder unresolved"),
                })
                row["dollars"] += mv
        else:
            u = underlying.setdefault(
                sym, {"direct_usd": 0.0, "indirect_usd": 0.0, "source_funds": set()})
            u["direct_usd"] += mv

        snap = income_map.get(sym) or {}
        dy = snap.get("yield_pct")
        if dy is not None:
            income += mv * float(dy) / 100.0
        else:
            data_gaps.append(f"{sym}: no cached distribution yield")

        er = facts.get("expense_ratio_pct")
        if er is not None:
            weighted_er += mv * float(er)
            er_covered += mv
        elif qt in ("ETF", "MUTUALFUND"):
            data_gaps.append(f"{sym}: no cached expense ratio")

        closes = load_closes(cur, sym, days=400)
        b = beta_vs(closes, bench_closes) if closes else None
        if b is not None:
            weighted_beta += mv * b
            beta_covered += mv
        vol = annualized_vol_pct(closes) if closes else None
        p["_vol"] = vol

    top = sorted(((s, v) for s, v in issuers.items() if v > 0), key=lambda x: -x[1])
    equity_total = total - cash

    # nested-fund filter: a look-through holding that is itself a known fund
    # wrapper is not an economic issuer — reroute it to unresolved_lookthrough
    lt_only = [t for t, u in underlying.items()
               if u["indirect_usd"] > 0 and t not in facts_map]
    nested_facts = get_instrument_facts(cur, lt_only) if lt_only else {}
    for t in list(underlying):
        u = underlying[t]
        t_facts = facts_map.get(t) or nested_facts.get(t) or {}
        if _is_fund_wrapper(t, t_facts, known_funds) and u["direct_usd"] <= 0:
            row = unresolved.setdefault(t, {
                "symbol": t, "dollars": 0.0,
                "lookthrough_coverage_pct": 0.0,
                "note": (f"nested fund inside {', '.join(sorted(u['source_funds']))} — "
                         "not an economic issuer; second-level holdings unresolved"),
            })
            row["dollars"] += u["indirect_usd"]
            del underlying[t]

    underlying_rows = []
    for issuer, u in underlying.items():
        tot_usd = u["direct_usd"] + u["indirect_usd"]
        if tot_usd <= 0:
            continue
        underlying_rows.append({
            "issuer": issuer,
            "direct_usd": round(u["direct_usd"], 2),
            "indirect_usd": round(u["indirect_usd"], 2),
            "total_usd": round(tot_usd, 2),
            "pct_of_portfolio": round(tot_usd / total * 100.0, 2) if total > 0 else None,
            "source_funds": sorted(u["source_funds"]),
            "coverage_note": ("indirect exposure via top-holdings look-through only — "
                              "uncovered fund weight listed in unresolved_lookthrough"
                              if u["source_funds"] else None),
        })
    underlying_rows.sort(key=lambda r: -r["total_usd"])
    unresolved_rows = sorted(
        ({**r, "dollars": round(r["dollars"], 2)} for r in unresolved.values()),
        key=lambda r: -r["dollars"])

    return {
        "label": state.label,
        "total_usd": round(total, 2),
        "cash_usd": round(cash, 2),
        "cash_pct": round(cash / total * 100.0, 2) if total > 0 else None,
        "asset_classes": [
            {"asset_class": k, "usd": round(v, 2),
             "pct": round(v / total * 100.0, 2) if total > 0 else None}
            for k, v in sorted(asset_classes.items(), key=lambda x: -x[1])
        ],
        "sectors": [
            {"sector": k, "usd": round(v, 2),
             "pct": round(v / total * 100.0, 2) if total > 0 else None}
            for k, v in sorted(sectors.items(), key=lambda x: -x[1])
        ],
        # DEPRECATED: mixes fund wrappers with underlying issuers — kept only for
        # backward compat; use the three separated tables below (defect #17).
        "top_issuers": [
            {"symbol": s, "usd": round(v, 2),
             "pct": round(v / total * 100.0, 2) if total > 0 else None}
            for s, v in top[:25]
        ],
        "direct_positions": sorted(
            ({**d, "dollars": round(d["dollars"], 2)} for d in direct_agg.values()),
            key=lambda r: -r["dollars"])[:50],
        "underlying_issuers": underlying_rows[:40],
        "unresolved_lookthrough": unresolved_rows,
        "lookthrough_note": ("direct_positions = what is actually held (wrappers flagged); "
                             "underlying_issuers = economic issuers via look-through + direct "
                             "single stocks (fund tickers never appear here); "
                             "unresolved_lookthrough = fund dollars without (complete) "
                             "holdings data"),
        "concentration_top10_pct": round(
            sum(v for _, v in top[:TOP_CONCENTRATION_N]) / total * 100.0, 2
        ) if total > 0 else None,
        "expected_annual_income_usd": round(income, 2),
        "portfolio_yield_pct": round(income / total * 100.0, 2) if total > 0 else None,
        "expected_monthly_income_usd": round(income / 12.0, 2),
        "weighted_expense_ratio_pct": (
            round(weighted_er / er_covered, 3) if er_covered > 0 else None
        ),
        "expense_ratio_coverage_pct": (
            round(er_covered / equity_total * 100.0, 1) if equity_total > 0 else None
        ),
        "weighted_beta_1y": round(weighted_beta / beta_covered, 2) if beta_covered > 0 else None,
        "beta_coverage_pct": (
            round(beta_covered / equity_total * 100.0, 1) if equity_total > 0 else None
        ),
        "data_gaps": sorted(set(data_gaps)),
    }


def _dimension_deltas(pre: dict, post_sale: dict, post_plan: dict) -> dict[str, Any]:
    def sector_map(st):
        return {r["sector"]: r["pct"] or 0.0 for r in st["sectors"]}

    pre_s, sale_s, plan_s = sector_map(pre), sector_map(post_sale), sector_map(post_plan)
    all_sectors = sorted(set(pre_s) | set(sale_s) | set(plan_s))
    sector_rows = []
    for sec in all_sectors:
        lost = pre_s.get(sec, 0.0) - sale_s.get(sec, 0.0)
        restored = plan_s.get(sec, 0.0) - sale_s.get(sec, 0.0)
        sector_rows.append({
            "sector": sec,
            "pre_pct": pre_s.get(sec, 0.0), "post_sale_pct": sale_s.get(sec, 0.0),
            "post_plan_pct": plan_s.get(sec, 0.0),
            "lost_pct_pts": round(lost, 2), "restored_pct_pts": round(restored, 2),
            "restoration_ratio": round(restored / lost, 2) if abs(lost) > 0.05 else None,
        })
    sector_rows.sort(key=lambda r: -abs(r["lost_pct_pts"]))

    def scalar(key):
        return {
            "pre": pre.get(key), "post_sale": post_sale.get(key), "post_plan": post_plan.get(key),
            "plan_delta": (
                round(post_plan[key] - post_sale[key], 3)
                if isinstance(post_plan.get(key), (int, float)) and isinstance(post_sale.get(key), (int, float))
                else None
            ),
        }

    return {
        "sectors": sector_rows[:15],
        "income_annual_usd": scalar("expected_annual_income_usd"),
        "portfolio_yield_pct": scalar("portfolio_yield_pct"),
        "weighted_expense_ratio_pct": scalar("weighted_expense_ratio_pct"),
        "weighted_beta_1y": scalar("weighted_beta_1y"),
        "cash_pct": scalar("cash_pct"),
        "concentration_top10_pct": scalar("concentration_top10_pct"),
    }


def build_pro_forma(cur, event: dict[str, Any], plan_legs: list[dict[str, Any]],
                    *, bench_symbol: str = "SPY") -> dict[str, Any]:
    lookthrough = _lookthrough()
    sector_cache, manual_map = _sector_maps()
    bench_closes = load_closes(cur, bench_symbol)

    leg_syms = [str(l.get("ticker") or "").upper() for l in plan_legs]
    leg_prices = {}
    for sym in leg_syms:
        closes = load_closes(cur, sym, days=30)
        if closes:
            leg_prices[sym] = closes[-1][1]

    states = build_states(event, plan_legs, leg_prices=leg_prices)
    all_syms = sorted({p["symbol"] for st in ("pre_sale", "post_sale", "post_plan")
                       for p in states[st].positions if not p.get("is_cash")})
    facts_map = get_instrument_facts(cur, all_syms)

    analyzed = {}
    for key in ("pre_sale", "post_sale", "post_plan"):
        analyzed[key] = analyze_state(
            cur, states[key], facts_map=facts_map, lookthrough=lookthrough,
            sector_cache=sector_cache, manual_map=manual_map, bench_closes=bench_closes,
        )

    deltas = _dimension_deltas(analyzed["pre_sale"], analyzed["post_sale"], analyzed["post_plan"])
    remaining = [r for r in deltas["sectors"]
                 if r["lost_pct_pts"] > 0.25 and (r["restoration_ratio"] or 0) < 0.5]

    return {
        "ok": True,
        "advisory_only": True,
        "engine_version": ENGINE_VERSION,
        "as_of": datetime.now(timezone.utc).isoformat(),
        "event_id": event.get("id"),
        "sold_symbol": event.get("symbol"),
        "benchmark": bench_symbol,
        "modeled_legs": states["_modeled_legs"],
        "modeled_deploy_usd": states["_deployed"],
        "states": analyzed,
        "deltas": deltas,
        "remaining_gaps": [
            {"sector": r["sector"], "lost_pct_pts": r["lost_pct_pts"],
             "restored_pct_pts": r["restored_pct_pts"],
             "statement": (
                 f"{r['sector']}: sale removed {r['lost_pct_pts']:.2f} pct-pts; "
                 f"plan restores {r['restored_pct_pts']:.2f} pct-pts "
                 f"({(r['restoration_ratio'] or 0) * 100:.0f}% of the loss)"
             )}
            for r in remaining
        ],
        "note": "whole-share modeling at latest cached close; residuals stay in cash",
    }
