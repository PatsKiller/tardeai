#!/usr/bin/env python3
"""scalp_stop_monitor.py — real-time stop/risk monitoring for OPEN momentum_scalp paper trades.

Computes the MOMENTUM_SCALP_STOP_AND_TRAIL_POLICY §5 per-trade metrics + §4/§7 portfolio alerts from
paper_trades + the strategy YAML limits, and the §3 **Layer-4 dynamic adjustments** (advisory):
  • Regime-shift rule (§3 L4 #1): entry regime Trending → current Ranging while in-trade → tighten the
    active trail by 0.5× ATR.
  • Portfolio-heat rule (§3 L4 #2 / §4 Red): aggregate open risk > 3.5% → tighten ALL active trails by
    0.5× ATR and pause new entries; hard kill at 4.5% (§7).
  • Metrics (§4): stop distance in ATR, Trail-Tightness Score (% of price to the stop line).

`run()` is READ-ONLY / ADVISORY — emits metrics + alerts + Layer-4 SUGGESTIONS; it never mutates.
`tighten_all()` is the ONLY mutator: it APPLIES the 0.5× ATR tighten to OPEN momentum_scalp *paper*
trades (the auto/sim domain; L3 execution is config-OFF so this moves the current protective line, not a
broker order). It never touches real-account holdings. All thresholds are YAML-driven (no hardcoded values).

  python3 scripts/scalp_stop_monitor.py [--json]
  python3 scripts/scalp_stop_monitor.py --tighten-all [--apply] [--reason "..."]
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
    ls = er.get("layered_stop") or {}
    be = ls.get("layer2_breakeven") or {}
    l4 = ls.get("layer4_dynamic") or {}
    return {"breakeven_trigger_r": float(be.get("trigger_r", 1.2)),
            "max_initial_risk_r": float(risk.get("max_initial_risk_r", 1.2)),
            "max_concurrent": int(risk.get("max_concurrent_scalps", 3)),
            "daily_loss_limit_r": float(risk.get("daily_loss_limit_r", 3.0)),
            "heat_tighten_pct": float(risk.get("portfolio_heat_tighten_pct", 3.5)),
            "heat_kill_pct": float(risk.get("portfolio_heat_kill_pct", 4.5)),
            "l4_enabled": bool(l4.get("enabled", True)),
            "regime_tighten_atr": float(l4.get("regime_shift_tighten_atr", 0.5)),
            "heat_tighten_atr": float(l4.get("heat_tighten_atr", 0.5)),
            "trending_tokens": [str(t).lower() for t in (l4.get("trending_tokens") or ["trend", "risk on", "momentum", "bull"])],
            "ranging_tokens": [str(t).lower() for t in (l4.get("ranging_tokens") or ["rang", "chop", "neutral", "risk off", "defensive", "bear"])]}


def _classify_regime(text, lim):
    """Return 'trending' | 'ranging' | 'unknown' from a free-text regime label (config token match)."""
    t = str(text or "").lower()
    if not t:
        return "unknown"
    if any(tok in t for tok in lim["ranging_tokens"]):
        return "ranging"
    if any(tok in t for tok in lim["trending_tokens"]):
        return "trending"
    return "unknown"


def _current_regime():
    """Latest market regime label (e.g. 'risk_on_trend'). Rollback-safe via db_adapter._execute."""
    from db_adapter import _execute
    r = _execute("SELECT regime_label FROM market_regime_snapshots ORDER BY created_at DESC LIMIT 1", fetch="one")
    return str(r["regime_label"]) if (r and r.get("regime_label")) else None


def _paper_equity():
    """Paper/automated account equity for the heat % denominator. Config-driven (the paper account
    nominal in momentum_scalp.yaml risk.paper_account_equity); None if unset. No hardcoded value.
    (broker_accounts has no equity column — the live-broker equity source is not wired for paper.)"""
    try:
        import yaml
        cfg = yaml.safe_load((PROJECT_ROOT / "config/strategies/momentum_scalp.yaml").read_text())
        eq = (cfg.get("risk") or {}).get("paper_account_equity")
        return float(eq) if eq else None
    except Exception:
        return None


def _load_open_scalps():
    """Open momentum_scalp paper trades with the fields Layer-4 needs. Rollback-safe. Returns list of dicts."""
    from db_adapter import _execute
    rows = _execute("""SELECT id, symbol, entry_price, current_price,
                          COALESCE(current_stop, stop_loss_price, planned_stop) AS stop,
                          shares, dollar_risk, market_regime, recommendation_to_entry_seconds,
                          breakeven_trigger_r, max_adverse_excursion, trailing_active, initial_stop_atr
                   FROM paper_trades WHERE strategy_id='momentum_scalp'
                     AND (lifecycle_state='open' OR status='open')""", fetch="all") or []
    return [{"id": r["id"], "symbol": r["symbol"], "entry": r["entry_price"], "price": r["current_price"],
             "stop": r["stop"], "shares": r["shares"], "dollar_risk": r["dollar_risk"],
             "entry_regime_raw": r["market_regime"], "freshness_s": r["recommendation_to_entry_seconds"],
             "breakeven_trigger_r": r["breakeven_trigger_r"], "mae": r["max_adverse_excursion"],
             "trailing_active": r["trailing_active"], "atr": r["initial_stop_atr"]} for r in rows]


def _enrich(t, lim, current_regime_raw):
    """Compute per-scalp §4/§5 metrics + the Layer-4 tighten SUGGESTION (advisory). Pure."""
    try:
        e = float(t["entry"]); px = float(t["price"]) if t["price"] is not None else None
        stop = float(t["stop"]) if t["stop"] is not None else None
        atr = float(t["atr"]) if t["atr"] is not None else None
    except Exception:
        return None
    risk_ps = (e - stop) if (stop and stop < e) else None
    cur_R = ((px - e) / risk_ps) if (risk_ps and px is not None) else None
    stop_dist_r = ((px - stop) / risk_ps) if (risk_ps and px is not None) else None
    stop_dist_atr = ((px - stop) / atr) if (atr and atr > 0 and px is not None and stop is not None) else None
    trail_tightness_pct = ((px - stop) / px * 100.0) if (px and stop is not None) else None
    be_done = t["breakeven_trigger_r"] is not None
    dist_to_be = max(0.0, lim["breakeven_trigger_r"] - cur_R) if cur_R is not None else None
    risk_usd = float(t["dollar_risk"]) if t["dollar_risk"] is not None else (risk_ps * float(t["shares"] or 0) if risk_ps else None)
    entry_regime = _classify_regime(t["entry_regime_raw"], lim)
    now_regime = _classify_regime(current_regime_raw, lim)
    regime_shifted = (entry_regime == "trending" and now_regime == "ranging")
    # Layer-4 suggested tighten: raise the protective line by tighten_atr × ATR toward price (long).
    suggested_stop = None
    if atr and atr > 0 and stop is not None and px is not None:
        cand = round(stop + lim["regime_tighten_atr"] * atr, 2)
        if cand > stop and cand < px:                 # only ever TIGHTER, never at/above price
            suggested_stop = cand
    return {"id": t["id"], "symbol": t["symbol"], "entry": e, "price": px, "stop": stop, "atr": atr,
            "current_R": round(cur_R, 2) if cur_R is not None else None,
            "stop_distance_R": round(stop_dist_r, 2) if stop_dist_r is not None else None,
            "stop_distance_atr": round(stop_dist_atr, 2) if stop_dist_atr is not None else None,
            "trail_tightness_pct": round(trail_tightness_pct, 2) if trail_tightness_pct is not None else None,
            "dist_to_breakeven_R": round(dist_to_be, 2) if dist_to_be is not None else None,
            "breakeven_secured": be_done, "trailing_active": bool(t["trailing_active"]),
            "entry_regime": entry_regime, "current_regime": now_regime, "regime_shifted": regime_shifted,
            "freshness_s": t["freshness_s"], "risk_usd": round(risk_usd, 2) if risk_usd else None,
            "suggested_stop": suggested_stop,
            "mae_R": (round(float(t["mae"]), 2) if t["mae"] is not None and risk_ps else None)}


def run():
    lim = _limits()
    current_regime_raw = _current_regime()
    trades = _load_open_scalps()
    equity = _paper_equity()
    scalps, alerts = [], []
    open_risk = 0.0
    for t in trades:
        s = _enrich(t, lim, current_regime_raw)
        if s is None:
            continue
        if s["risk_usd"]:
            open_risk += max(0.0, s["risk_usd"])
        scalps.append(s)
        # ── §5/§7 per-trade alerts (active layers only) ──
        if s["stop_distance_R"] is not None and 0 <= s["stop_distance_R"] < 0.3:
            alerts.append({"level": "yellow", "symbol": s["symbol"], "rule": "near_stop",
                           "msg": f"{s['symbol']} within {s['stop_distance_R']:.2f}R of stop ${s['stop']:.2f}"})
        if s["current_R"] is not None and s["current_R"] >= lim["breakeven_trigger_r"] and not s["breakeven_secured"]:
            alerts.append({"level": "amber", "symbol": s["symbol"], "rule": "breakeven_overdue",
                           "msg": f"{s['symbol']} at +{s['current_R']:.1f}R but breakeven not secured (trigger +{lim['breakeven_trigger_r']}R)"})
        if s["freshness_s"] is not None and s["freshness_s"] > 90 and (s["current_R"] is None or s["current_R"] < 0.8):
            alerts.append({"level": "red", "symbol": s["symbol"], "rule": "stale_no_move",
                           "msg": f"{s['symbol']} freshness {s['freshness_s']}s >90s and no +0.8R move — force breakeven"})
        # ── §3 Layer-4 #1: regime-shift tighten (advisory) ──
        if lim["l4_enabled"] and s["regime_shifted"]:
            sug = f" → tighten to ${s['suggested_stop']:.2f}" if s["suggested_stop"] else ""
            alerts.append({"level": "amber", "symbol": s["symbol"], "rule": "regime_shift_tighten",
                           "msg": f"{s['symbol']} entry regime Trending → now Ranging: tighten trail {lim['regime_tighten_atr']}× ATR{sug}",
                           "suggested_stop": s["suggested_stop"]})
    heat_pct = round(100 * open_risk / equity, 2) if (equity and open_risk) else None
    # ── §3 Layer-4 #2 / §4: portfolio-heat tighten tier (3.5%) + hard kill (4.5%) ──
    heat_tighten_active = bool(heat_pct is not None and heat_pct > lim["heat_tighten_pct"])
    heat_kill_active = bool(heat_pct is not None and heat_pct > lim["heat_kill_pct"])
    pause_new_entries = heat_tighten_active or heat_kill_active
    if heat_kill_active:
        alerts.append({"level": "red", "symbol": "*", "rule": "portfolio_heat_kill",
                       "msg": f"portfolio heat {heat_pct:.1f}% > {lim['heat_kill_pct']}% KILL — pause ALL new entries + tighten all"})
    elif heat_tighten_active:
        alerts.append({"level": "red", "symbol": "*", "rule": "portfolio_heat_tighten",
                       "msg": f"portfolio heat {heat_pct:.1f}% > {lim['heat_tighten_pct']}% — global tighten all trails {lim['heat_tighten_atr']}× ATR + pause new entries"})
    if len(scalps) > lim["max_concurrent"]:
        alerts.append({"level": "amber", "symbol": "*", "rule": "max_concurrent",
                       "msg": f"{len(scalps)} open scalps > max {lim['max_concurrent']}"})
    # Tighten-All candidates: heat rule = every open scalp with a computable tighter stop; else the
    # regime-shifted ones. This is what the "Tighten All Trails" one-click applies.
    if heat_tighten_active:
        tighten_candidates = [s for s in scalps if s["suggested_stop"]]
        tighten_trigger = "portfolio_heat"
    else:
        tighten_candidates = [s for s in scalps if s["regime_shifted"] and s["suggested_stop"]]
        tighten_trigger = "regime_shift"
    return {"open_scalps": scalps, "count": len(scalps), "open_risk_usd": round(open_risk, 2),
            "paper_equity": equity, "portfolio_heat_pct": heat_pct,
            "current_regime": current_regime_raw,
            "heat_tighten_active": heat_tighten_active, "heat_kill_active": heat_kill_active,
            "pause_new_entries": pause_new_entries,
            "tighten_all_available": bool(tighten_candidates),
            "tighten_all_trigger": tighten_trigger if tighten_candidates else None,
            "tighten_all_candidates": [{"id": s["id"], "symbol": s["symbol"], "current_stop": s["stop"],
                                        "suggested_stop": s["suggested_stop"], "atr": s["atr"]}
                                       for s in tighten_candidates],
            "alerts": alerts, "limits": lim,
            "note": "advisory/read-only · Layer-3 trail execution config-OFF · Layer-4 tightens are suggestions until applied"}


def tighten_all(*, apply: bool = False, reason: str = "L4 tighten-all", trigger: str | None = None):
    """Layer-4 'Tighten All Trails' action (§8 #4). Computes the 0.5× ATR tighten for every open
    momentum_scalp *paper* trade the current snapshot flags, and — only when apply=True — writes the
    tighter stop to paper_trades (current_stop + stop_loss_price + stop_updated_at, tag stop_type).
    PAPER ONLY. Never touches real-account holdings or places a broker order. Returns the diff."""
    from db_adapter import _get_conn
    snap = run()
    cands = snap.get("tighten_all_candidates") or []
    changes = [{"id": c["id"], "symbol": c["symbol"], "from": c["current_stop"], "to": c["suggested_stop"]}
               for c in cands if c.get("suggested_stop")]
    applied = 0
    if apply and changes:
        conn = _get_conn(); cur = conn.cursor()
        for ch in changes:
            try:
                cur.execute("""UPDATE paper_trades
                               SET current_stop=%s, stop_loss_price=%s, stop_updated_at=NOW(),
                                   stop_type='l4_tightened'
                               WHERE id=%s AND strategy_id='momentum_scalp'
                                 AND (lifecycle_state='open' OR status='open')""",
                            (ch["to"], ch["to"], ch["id"]))
                applied += cur.rowcount
            except Exception as ex:
                ch["error"] = str(ex)[:120]
                conn.rollback()
                continue
        conn.commit()
    return {"ok": True, "trigger": trigger or snap.get("tighten_all_trigger"), "reason": reason,
            "applied": applied, "dry_run": not apply, "changes": changes,
            "note": "paper momentum_scalp only · advisory for any non-paper trade · no broker order placed"}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--tighten-all", action="store_true")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--reason", default="L4 tighten-all (cli)")
    args = ap.parse_args()
    if args.tighten_all:
        print(json.dumps(tighten_all(apply=args.apply, reason=args.reason), indent=2, default=str))
    else:
        print(json.dumps(run(), indent=2, default=str))


if __name__ == "__main__":
    main()
