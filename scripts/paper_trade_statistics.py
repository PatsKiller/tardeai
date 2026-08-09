#!/usr/bin/env python3
"""Paper Trade Statistics — comprehensive metrics for statistical readiness audit.

Usage:
    python scripts/paper_trade_statistics.py [--json] [--report]

Outputs:
    data/paper_trading/paper_trade_statistics_latest.json
"""
import json, sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
from db_adapter import _execute


def _q(sql, **kw):
    return _execute(sql, fetch=kw.get("fetch", "all")) or ([] if kw.get("fetch", "all") == "all" else {})


def compute_statistics():
    """Compute comprehensive paper trade statistics."""
    now = datetime.now(timezone.utc).isoformat()

    # ── Core counts ──
    totals = _q("""
        SELECT count(*) as total,
            count(*) FILTER (WHERE status='open') as open_trades,
            count(*) FILTER (WHERE status='closed') as closed_trades,
            count(*) FILTER (WHERE status='cancelled') as cancelled,
            count(*) FILTER (WHERE status='EXPIRED') as expired,
            min(created_at)::text as earliest,
            max(created_at)::text as latest
        FROM paper_trades
    """, fetch="one")

    closed = totals.get("closed_trades", 0)

    # ── Dollar/share size stats (all trades) ──
    size_all = _q("""
        SELECT avg(dollar_size)::numeric(10,2) as avg_notional,
            percentile_cont(0.5) WITHIN GROUP (ORDER BY dollar_size)::numeric(10,2) as median_notional,
            max(dollar_size)::numeric(10,2) as max_notional,
            min(dollar_size)::numeric(10,2) as min_notional,
            sum(dollar_size)::numeric(12,2) as total_notional,
            avg(shares)::numeric(10,1) as avg_shares,
            percentile_cont(0.5) WITHIN GROUP (ORDER BY shares)::numeric(10,1) as median_shares,
            avg(dollar_risk)::numeric(10,2) as avg_risk,
            percentile_cont(0.5) WITHIN GROUP (ORDER BY dollar_risk)::numeric(10,2) as median_risk
        FROM paper_trades WHERE dollar_size IS NOT NULL
    """, fetch="one")

    # ── Win/loss stats (closed only) ──
    wl = _q("""
        SELECT count(*) as total_closed,
            count(*) FILTER (WHERE pnl > 0) as wins,
            count(*) FILTER (WHERE pnl < 0) as losses,
            count(*) FILTER (WHERE pnl IS NULL OR pnl = 0) as flat_or_null,
            sum(CASE WHEN pnl > 0 THEN pnl ELSE 0 END)::numeric(10,2) as gross_profit,
            abs(sum(CASE WHEN pnl < 0 THEN pnl ELSE 0 END))::numeric(10,2) as gross_loss,
            sum(pnl)::numeric(10,2) as net_pnl,
            avg(pnl)::numeric(10,2) as avg_pnl,
            avg(r_multiple)::numeric(10,3) as avg_r,
            avg(hold_time_min)::numeric(10,1) as avg_hold_min,
            max(pnl)::numeric(10,2) as best_trade,
            min(pnl)::numeric(10,2) as worst_trade
        FROM paper_trades WHERE status='closed'
    """, fetch="one")

    wins = float(wl.get("wins") or 0)
    losses = float(wl.get("losses") or 0)
    total_closed = float(wl.get("total_closed") or 0)
    gross_profit = float(wl.get("gross_profit") or 0)
    gross_loss = float(wl.get("gross_loss") or 0)

    win_rate = round(wins / total_closed * 100, 1) if total_closed > 0 else 0
    profit_factor = round(gross_profit / gross_loss, 2) if gross_loss > 0 else 0
    expectancy = round(float(wl.get("net_pnl") or 0) / total_closed, 2) if total_closed > 0 else 0

    # ── Drawdown (sequential PnL) ──
    pnl_seq = _q("SELECT pnl FROM paper_trades WHERE status='closed' AND pnl IS NOT NULL ORDER BY closed_at")
    cumulative = 0
    peak = 0
    max_dd = 0
    for r in pnl_seq:
        cumulative += float(r["pnl"] or 0)
        peak = max(peak, cumulative)
        dd = peak - cumulative
        max_dd = max(max_dd, dd)

    # ── By strategy ──
    by_strategy = _q("""
        SELECT strategy_id,
            count(*) as total,
            count(*) FILTER (WHERE status='closed') as closed,
            count(*) FILTER (WHERE status='closed' AND pnl > 0) as wins,
            count(*) FILTER (WHERE status='closed' AND pnl < 0) as losses,
            sum(pnl) FILTER (WHERE status='closed')::numeric(10,2) as net_pnl,
            avg(pnl) FILTER (WHERE status='closed')::numeric(10,2) as avg_pnl,
            avg(r_multiple) FILTER (WHERE status='closed')::numeric(10,3) as avg_r,
            avg(pnl) FILTER (WHERE status='closed' AND pnl > 0)::numeric(10,2) as avg_win,
            avg(pnl) FILTER (WHERE status='closed' AND pnl < 0)::numeric(10,2) as avg_loss,
            avg(dollar_size)::numeric(10,2) as avg_size,
            avg(hold_time_min)::numeric(10,1) as avg_hold_min
        FROM paper_trades
        GROUP BY strategy_id ORDER BY count(*) DESC
    """)
    strategies = []
    for r in by_strategy:
        cl = float(r["closed"] or 0)
        w = float(r["wins"] or 0)
        l = float(r["losses"] or 0)
        avg_win = float(r["avg_win"]) if r["avg_win"] is not None else None
        avg_loss = float(r["avg_loss"]) if r["avg_loss"] is not None else None
        # realized payoff R:R = avg winning pnl / avg losing pnl (absolute)
        rr = round(avg_win / abs(avg_loss), 2) if (avg_win and avg_loss) else None
        net = float(r["net_pnl"] or 0)
        # per-trade $ expectancy = net pnl / closed trades; no_losses flag → R:R/PF are ∞ (good), not missing
        expectancy = round(net / cl, 2) if cl > 0 else None
        no_losses = (l == 0 and w > 0)
        strategies.append({
            "strategy": r["strategy_id"],
            "total": r["total"],
            "closed": r["closed"],
            "wins": r["wins"],
            "losses": r["losses"],
            "win_rate": round(w / cl * 100, 1) if cl > 0 else None,
            "net_pnl": net,
            "avg_pnl": float(r["avg_pnl"] or 0),
            "avg_r": float(r["avg_r"]) if r["avg_r"] else None,
            "avg_win": avg_win,
            "avg_loss": avg_loss,
            "rr": rr,
            "expectancy": expectancy,
            "no_losses": no_losses,
            "avg_size": float(r["avg_size"] or 0),
            "avg_hold_min": float(r["avg_hold_min"]) if r["avg_hold_min"] else None,
        })

    # ── By symbol ──
    by_symbol = _q("""
        SELECT symbol, count(*) as trades, sum(pnl)::numeric(10,2) as pnl
        FROM paper_trades GROUP BY symbol ORDER BY count(*) DESC LIMIT 20
    """)
    symbols = [{"symbol": r["symbol"], "trades": r["trades"], "pnl": float(r["pnl"] or 0)} for r in by_symbol]

    # ── By day ──
    by_day = _q("""
        SELECT created_at::date as day, count(*) as opened,
            count(*) FILTER (WHERE status='closed') as closed
        FROM paper_trades GROUP BY day ORDER BY day
    """)
    daily = [{"date": str(r["day"]), "opened": r["opened"], "closed": r["closed"]} for r in by_day]
    avg_per_day = round(len(_q("SELECT 1 FROM paper_trades")) / max(len(daily), 1), 1)

    # ── By hour ──
    by_hour = _q("""
        SELECT EXTRACT(HOUR FROM created_at) as hour, count(*) as trades
        FROM paper_trades GROUP BY hour ORDER BY hour
    """)
    hourly = [{"hour": int(r["hour"]), "trades": r["trades"]} for r in by_hour]

    # ── Field completeness (closed trades) ──
    comp = _q("""
        SELECT count(*) as total,
            count(*) FILTER (WHERE strategy_id IS NOT NULL AND strategy_id != '') as strategy,
            count(*) FILTER (WHERE exit_reason IS NOT NULL AND exit_reason != '') as exit_reason,
            count(*) FILTER (WHERE close_reason IS NOT NULL AND close_reason != '') as close_reason,
            count(*) FILTER (WHERE hold_time_min IS NOT NULL AND hold_time_min > 0) as hold_time,
            count(*) FILTER (WHERE dollar_size IS NOT NULL) as dollar_size,
            count(*) FILTER (WHERE dollar_risk IS NOT NULL) as dollar_risk,
            count(*) FILTER (WHERE r_multiple IS NOT NULL) as r_multiple,
            count(*) FILTER (WHERE catalyst_at_entry IS NOT NULL) as catalyst,
            count(*) FILTER (WHERE market_regime IS NOT NULL) as market_regime,
            count(*) FILTER (WHERE post_trade_analyzed = true) as post_analyzed,
            count(*) FILTER (WHERE stop_loss IS NOT NULL) as stop_loss,
            count(*) FILTER (WHERE target_1 IS NOT NULL) as target,
            count(*) FILTER (WHERE pnl IS NOT NULL) as pnl,
            count(*) FILTER (WHERE entry_price IS NOT NULL) as entry_price,
            count(*) FILTER (WHERE exit_price IS NOT NULL) as exit_price,
            count(*) FILTER (WHERE max_adverse_excursion IS NOT NULL) as mae,
            count(*) FILTER (WHERE max_favorable_excursion IS NOT NULL) as mfe,
            count(*) FILTER (WHERE broker_order_id IS NOT NULL) as broker_id,
            count(*) FILTER (WHERE proposal_id IS NOT NULL) as proposal_id
        FROM paper_trades WHERE status='closed'
    """, fetch="one")

    total_c = comp.get("total", 1)
    completeness = {}
    for k, v in comp.items():
        if k == "total":
            continue
        completeness[k] = {"count": v, "pct": round(v / total_c * 100, 1) if total_c > 0 else 0}

    # ── Linkage completeness ──
    thesis_linked = _q("SELECT count(*) as c FROM trade_thesis_outcomes WHERE paper_trade_id IS NOT NULL", fetch="one").get("c", 0)
    outcome_analytics = _q("SELECT count(*) as c FROM paper_trade_outcome_analytics", fetch="one").get("c", 0)
    lesson_memory = _q("SELECT count(*) as c FROM trade_lesson_memory", fetch="one").get("c", 0)
    hermes_linked = _q("SELECT count(*) as c FROM hermes_research_intelligence WHERE related_trade_id IS NOT NULL", fetch="one").get("c", 0)
    backtest_linked = _q("SELECT count(*) as c FROM paper_trades WHERE backtest_quality IS NOT NULL AND status='closed'", fetch="one").get("c", 0)

    # ── Readiness level ──
    if closed < 100:
        readiness = "P0_NOT_ENOUGH_DATA"
    elif closed < 500:
        readiness = "P1_EARLY_SIGNAL"
    elif closed < 1000:
        readiness = "P2_DEVELOPING"
    elif closed < 2000:
        readiness = "P3_MEANINGFUL"
    elif closed < 4000:
        readiness = "P4_STRONG_PAPER_EVIDENCE"
    else:
        readiness = "P5_LIVE_READINESS_CANDIDATE"

    # ── Build result ──
    result = {
        "timestamp": now,
        "mode": "PAPER_ONLY",
        "live_trading_prohibited": True,
        "level_7_prohibited": True,

        "counts": {
            "total_orders": totals["total"],
            "total_trades": totals["total"],
            "closed_trades": totals["closed_trades"],
            "open_trades": totals["open_trades"],
            "cancelled": totals["cancelled"],
            "expired": totals["expired"],
            "earliest": totals["earliest"],
            "latest": totals["latest"],
        },

        "size": {
            "total_notional": float(size_all.get("total_notional") or 0),
            "avg_notional": float(size_all.get("avg_notional") or 0),
            "median_notional": float(size_all.get("median_notional") or 0),
            "max_notional": float(size_all.get("max_notional") or 0),
            "min_notional": float(size_all.get("min_notional") or 0),
            "avg_shares": float(size_all.get("avg_shares") or 0),
            "median_shares": float(size_all.get("median_shares") or 0),
            "avg_risk": float(size_all.get("avg_risk") or 0),
            "median_risk": float(size_all.get("median_risk") or 0),
        },

        "performance": {
            "win_rate": win_rate,
            "profit_factor": profit_factor,
            "expectancy": expectancy,
            "net_pnl": float(wl.get("net_pnl") or 0),
            "gross_profit": gross_profit,
            "gross_loss": gross_loss,
            "avg_pnl": float(wl.get("avg_pnl") or 0),
            "avg_r": float(wl.get("avg_r") or 0),
            "best_trade": float(wl.get("best_trade") or 0),
            "worst_trade": float(wl.get("worst_trade") or 0),
            "max_drawdown": round(max_dd, 2),
            "avg_hold_min": float(wl.get("avg_hold_min") or 0),
        },

        "by_strategy": strategies,
        "by_symbol": symbols,
        "by_day": daily,
        "by_hour": hourly,
        "avg_trades_per_day": avg_per_day,

        "field_completeness": completeness,

        "linkage": {
            "thesis_outcomes_linked": thesis_linked,
            "outcome_analytics": outcome_analytics,
            "lesson_memory": lesson_memory,
            "hermes_trade_linked": hermes_linked,
            "backtest_linked": backtest_linked,
            "thesis_pct": round(thesis_linked / max(closed, 1) * 100, 1),
            "outcome_pct": round(outcome_analytics / max(closed, 1) * 100, 1),
            "hermes_pct": round(hermes_linked / max(closed, 1) * 100, 1),
            "backtest_pct": round(backtest_linked / max(closed, 1) * 100, 1),
        },

        "readiness": {
            "level": readiness,
            "closed_usable": closed,
            "distance_to_2000": max(0, 2000 - closed),
            "distance_to_4000": max(0, 4000 - closed),
            "pct_to_2000": round(closed / 2000 * 100, 1),
            "pct_to_4000": round(closed / 4000 * 100, 1),
        },
    }

    # Write output
    out_dir = PROJECT_ROOT / "data" / "paper_trading"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / "paper_trade_statistics_latest.json"
    out_file.write_text(json.dumps(result, indent=2, default=str))
    return result


def print_report(stats):
    """Print human-readable report."""
    c = stats["counts"]
    s = stats["size"]
    p = stats["performance"]
    r = stats["readiness"]
    fc = stats["field_completeness"]
    lk = stats["linkage"]

    print("=" * 60)
    print("PAPER TRADE STATISTICS REPORT")
    print(f"Generated: {stats['timestamp']}")
    print(f"Mode: {stats['mode']} | Live: PROHIBITED | Level 7: PROHIBITED")
    print("=" * 60)

    print(f"\nTrades: {c['total_trades']} total | {c['closed_trades']} closed | {c['open_trades']} open | {c['cancelled']} cancelled")
    print(f"Period: {c['earliest'][:10]} to {c['latest'][:10]}")
    print(f"Avg trades/day: {stats['avg_trades_per_day']}")

    print(f"\nSize:")
    print(f"  Avg notional:    ${s['avg_notional']:,.2f}")
    print(f"  Median notional: ${s['median_notional']:,.2f}")
    print(f"  Max trade:       ${s['max_notional']:,.2f}")
    print(f"  Min trade:       ${s['min_notional']:,.2f}")
    print(f"  Total notional:  ${s['total_notional']:,.2f}")
    print(f"  Avg shares:      {s['avg_shares']:.0f}")
    print(f"  Avg risk:        ${s['avg_risk']:,.2f}")

    print(f"\nPerformance (closed):")
    print(f"  Win rate:     {p['win_rate']}%")
    print(f"  Profit factor: {p['profit_factor']}")
    _exp = p.get("expectancy")
    print(f"  Expectancy:    ${(_exp if _exp is not None else 0):,.2f}")
    print(f"  Net PnL:       ${(p.get('net_pnl') or 0):,.2f}")
    print(f"  Avg R:         {(p.get('avg_r') or 0):.3f}")
    print(f"  Max drawdown:  ${(p.get('max_drawdown') or 0):,.2f}")
    print(f"  Best trade:    ${(p.get('best_trade') or 0):,.2f}")
    print(f"  Worst trade:   ${(p.get('worst_trade') or 0):,.2f}")

    print(f"\nBy Strategy:")
    for st in stats["by_strategy"]:
        wr = f"{st['win_rate']}%" if st["win_rate"] is not None else "N/A"
        print(f"  {st['strategy']:35s} {st['total']:3d} total  {st['closed']:3d} closed  WR={wr:>6s}  PnL=${st['net_pnl']:>8.2f}")

    print(f"\nField Completeness (closed trades):")
    for field, data in sorted(fc.items(), key=lambda x: -x[1]["pct"]):
        bar = "#" * int(data["pct"] / 5) + "." * (20 - int(data["pct"] / 5))
        print(f"  {field:20s} [{bar}] {data['pct']:5.1f}% ({data['count']}/{c['closed_trades']})")

    print(f"\nLinkage:")
    print(f"  Thesis outcomes:  {lk['thesis_pct']}% ({lk['thesis_outcomes_linked']}/{c['closed_trades']})")
    print(f"  Outcome analytics: {lk['outcome_pct']}% ({lk['outcome_analytics']}/{c['closed_trades']})")
    print(f"  Hermes audit:     {lk['hermes_pct']}% ({lk['hermes_trade_linked']}/{c['closed_trades']})")
    print(f"  Backtest:         {lk['backtest_pct']}% ({lk['backtest_linked']}/{c['closed_trades']})")
    print(f"  Lessons:          {lk['lesson_memory']} total")

    print(f"\nReadiness:")
    print(f"  Level:          {r['level']}")
    print(f"  Usable closed:  {r['closed_usable']}")
    print(f"  To 2,000:       {r['distance_to_2000']} more needed ({r['pct_to_2000']}% complete)")
    print(f"  To 4,000:       {r['distance_to_4000']} more needed ({r['pct_to_4000']}% complete)")
    print()


if __name__ == "__main__":
    stats = compute_statistics()
    if "--json" in sys.argv:
        print(json.dumps(stats, indent=2, default=str))
    else:
        print_report(stats)
    if "--report" not in sys.argv:
        print(f"Written to: data/paper_trading/paper_trade_statistics_latest.json")
