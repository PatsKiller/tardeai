#!/usr/bin/env python3
"""scalp_stop_monitor.py — real-time stop/risk monitoring for OPEN momentum_scalp paper trades.

Computes the MOMENTUM_SCALP_STOP_AND_TRAIL_POLICY §5 per-trade metrics + §7 portfolio alerts from
paper_trades + the strategy YAML limits. READ-ONLY / ADVISORY — emits metrics + alert objects for the
Risk tab; never places/modifies an order. Layer-3 trail alerts are omitted (trailing is config-OFF).

  python3 scripts/scalp_stop_monitor.py [--json]
"""
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))


def _limits():
    import yaml
    cfg = yaml.safe_load((PROJECT_ROOT / "config/strategies/momentum_scalp.yaml").read_text())
    er = cfg.get("exit_rules", {}); risk = cfg.get("risk", {})
    be = ((er.get("layered_stop") or {}).get("layer2_breakeven") or {})
    return {"breakeven_trigger_r": float(be.get("trigger_r", 1.2)),
            "max_initial_risk_r": float(risk.get("max_initial_risk_r", 1.2)),
            "max_concurrent": int(risk.get("max_concurrent_scalps", 3)),
            "daily_loss_limit_r": float(risk.get("daily_loss_limit_r", 3.0)),
            "heat_kill_pct": float(risk.get("portfolio_heat_kill_pct", 4.5))}


def _paper_equity(cur):
    """Best-effort paper/automated account equity for the heat %; None if unknown."""
    try:
        cur.execute("""SELECT equity FROM broker_accounts WHERE account_key ILIKE '%alpaca%'
                       AND equity IS NOT NULL ORDER BY updated_at DESC LIMIT 1""")
        r = cur.fetchone()
        return float(r[0]) if r and r[0] else None
    except Exception:
        return None


def run():
    from db_adapter import _get_conn
    lim = _limits()
    conn = _get_conn(); cur = conn.cursor()
    cur.execute("""SELECT symbol, entry_price, current_price, COALESCE(stop_loss_price, planned_stop) AS stop,
                          shares, dollar_risk, market_regime, recommendation_to_entry_seconds,
                          breakeven_trigger_r, max_adverse_excursion, trailing_active
                   FROM paper_trades WHERE strategy_id='momentum_scalp'
                     AND (lifecycle_state='open' OR status='open')""")
    rows = cur.fetchall()
    equity = _paper_equity(cur)
    scalps, alerts = [], []
    open_risk = 0.0
    for (sym, e, px, stop, sh, drisk, regime, rec_s, be_r, mae, trail_on) in rows:
        try:
            e = float(e); px = float(px) if px is not None else None; stop = float(stop) if stop is not None else None
        except Exception:
            continue
        risk_ps = (e - stop) if (stop and stop < e) else None
        cur_R = ((px - e) / risk_ps) if (risk_ps and px is not None) else None
        stop_dist_r = ((px - stop) / risk_ps) if (risk_ps and px is not None) else None
        be_done = be_r is not None
        dist_to_be = max(0.0, lim["breakeven_trigger_r"] - cur_R) if cur_R is not None else None
        risk_usd = float(drisk) if drisk is not None else (risk_ps * float(sh or 0) if risk_ps else None)
        if risk_usd:
            open_risk += max(0.0, risk_usd)
        s = {"symbol": sym, "entry": e, "price": px, "stop": stop,
             "current_R": round(cur_R, 2) if cur_R is not None else None,
             "stop_distance_R": round(stop_dist_r, 2) if stop_dist_r is not None else None,
             "dist_to_breakeven_R": round(dist_to_be, 2) if dist_to_be is not None else None,
             "breakeven_secured": be_done, "regime": regime, "freshness_s": rec_s,
             "risk_usd": round(risk_usd, 2) if risk_usd else None,
             "mae_R": (round(float(mae), 2) if mae is not None and risk_ps else None)}
        scalps.append(s)
        # ── §5/§7 alerts (active layers only) ──
        if stop_dist_r is not None and 0 <= stop_dist_r < 0.3:
            alerts.append({"level": "yellow", "symbol": sym, "rule": "near_stop",
                           "msg": f"{sym} within {stop_dist_r:.2f}R of stop ${stop:.2f}"})
        if cur_R is not None and cur_R >= lim["breakeven_trigger_r"] and not be_done:
            alerts.append({"level": "amber", "symbol": sym, "rule": "breakeven_overdue",
                           "msg": f"{sym} at +{cur_R:.1f}R but breakeven not secured (trigger +{lim['breakeven_trigger_r']}R)"})
        if rec_s is not None and rec_s > 90 and (cur_R is None or cur_R < 0.8):
            alerts.append({"level": "red", "symbol": sym, "rule": "stale_no_move",
                           "msg": f"{sym} freshness {rec_s}s >90s and no +0.8R move — force breakeven"})
    heat_pct = round(100 * open_risk / equity, 2) if (equity and open_risk) else None
    if heat_pct is not None and heat_pct > lim["heat_kill_pct"]:
        alerts.append({"level": "red", "symbol": "*", "rule": "portfolio_heat_kill",
                       "msg": f"portfolio heat {heat_pct:.1f}% > {lim['heat_kill_pct']}% — tighten all + pause new entries"})
    if len(scalps) > lim["max_concurrent"]:
        alerts.append({"level": "amber", "symbol": "*", "rule": "max_concurrent",
                       "msg": f"{len(scalps)} open scalps > max {lim['max_concurrent']}"})
    return {"open_scalps": scalps, "count": len(scalps), "open_risk_usd": round(open_risk, 2),
            "paper_equity": equity, "portfolio_heat_pct": heat_pct, "alerts": alerts, "limits": lim,
            "note": "advisory/read-only · Layer-3 trail alerts omitted (trailing config-OFF)"}


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--json", action="store_true"); ap.parse_args()
    print(json.dumps(run(), indent=2, default=str))


if __name__ == "__main__":
    main()
