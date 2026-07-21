#!/usr/bin/env python3
"""Stop Health Check (Stage 2c) — the HEALTH-AGENT face of the stop lifecycle monitor.

Runs the stop_lifecycle_monitor scan, persists the snapshot, and escalates any alert-worthy stop condition
through the SAME surfaces the rest of the system uses:
  • SIEM      : save_alert_event(source_script='stop_health', ...) — visible in the security/alerts feed
                and consumable by Hermes (which reads alert_events per symbol).
  • Telegram  : central alert router (telegram_alert.send_telegram) — NEVER a direct bypass.
  • health log: system_health_events row so the system_health_agent watchdog sees this check ran.

Alert conditions (per the engine's health=alert): ORPHANED (a live stop with no matching holding —
on trigger it could short / reject), OVERSIZED (stop qty > shares held — a GTC stop does NOT auto-resize
when you trim), FILLED/TRIGGERED (the stop fired — the position may be flat now), and NEAR-TRIGGER within
0.75% (about to fire). Dedup: one Telegram per (symbol, condition) per 2h via the SIEM event history.

Run on cron during market hours (read-only on the broker side):
  python3 scripts/stop_health_check.py [--quiet]
"""
from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

_COMPONENT = "stop_health"


def _send_telegram(msg: str) -> bool:
    try:
        from telegram_alert import send_telegram
        send_telegram(msg)
        return True
    except Exception:
        return False


def _siem(symbol: str, severity: str, text: str, payload: dict) -> None:
    try:
        from alert_event_writer import save_alert_event
        save_alert_event(alert_type="strategic_alert", severity=severity, source_script=_COMPONENT,
                         symbol=symbol or "", raw_text=text, parsed_payload=payload)
    except Exception:
        pass


_HOLDINGS_BASIS = None


def _pl_if_fired(symbol: str, account: str, stop_price, qty) -> dict | None:
    """Realized P/L if the stop fills at stop_price: qty × (stop − avg_cost).

    avg_cost per share = cost_basis / shares from holdings.json. Returns the
    dollar P/L, the R-multiple-ish percent vs cost, and whether the basis is
    partial (so the number is flagged, not silently wrong). None when basis is
    unavailable — an unknown P/L is stated as unknown, never guessed."""
    global _HOLDINGS_BASIS
    try:
        if _HOLDINGS_BASIS is None:
            import json
            from pathlib import Path
            p = Path(__file__).resolve().parent.parent / "data" / "portfolios" / "state" / "holdings.json"
            d = json.loads(p.read_text()) if p.exists() else {}
            _HOLDINGS_BASIS = {}
            for r in (d.get("holdings") or []):
                key = (str(r.get("symbol", "")).upper(), str(r.get("account", "")))
                _HOLDINGS_BASIS[key] = r
        h = _HOLDINGS_BASIS.get((str(symbol).upper(), str(account)))
        if not h:
            return None
        shares = float(h.get("shares") or h.get("quantity") or 0)
        cost_basis = h.get("cost_basis")
        if not shares or cost_basis in (None, ""):
            return None
        avg_cost = float(cost_basis) / shares
        sold = float(qty) if qty else shares
        pl = round(sold * (float(stop_price) - avg_cost), 2)
        pct = round((float(stop_price) - avg_cost) / avg_cost * 100, 1) if avg_cost else None
        return {"pl": pl, "pct": pct, "avg_cost": round(avg_cost, 2),
                "partial_basis": bool(h.get("basis_partial"))}
    except Exception:
        return None


def _pl_line(pl: dict | None) -> str:
    """Human tail for a stop alert: ' · if fired: −$413 (−44% vs cost $179)'."""
    if not pl or pl.get("pl") is None:
        return " · P/L if fired: basis unavailable"
    sign = "+" if pl["pl"] >= 0 else "−"
    tail = f" · if fired: {sign}${abs(pl['pl']):,.0f}"
    if pl.get("pct") is not None:
        tail += f" ({'+' if pl['pct'] >= 0 else '−'}{abs(pl['pct'])}% vs cost ${pl['avg_cost']:g})"
    if pl.get("partial_basis"):
        tail += " [partial basis]"
    return tail


def _recently_alerted(symbol: str, condition: str, hours: int = 2) -> bool:
    """Dedup via alert_events: True if the same (symbol, condition) fired in the last `hours`."""
    try:
        from db_adapter import _get_conn
        cur = _get_conn().cursor()
        cur.execute("""SELECT 1 FROM alert_events
                       WHERE source_script=%s AND symbol=%s AND raw_text LIKE %s
                         AND created_at > NOW() - INTERVAL '%s hours' LIMIT 1""",
                    (_COMPONENT, symbol, f"%{condition}%", hours))
        return cur.fetchone() is not None
    except Exception:
        return False   # fail open ⇒ we alert (better a dup than a miss on a safety signal)


def _hermes_finding(symbol: str, condition: str, line: str, payload: dict) -> None:
    """Write the stop-health condition into Hermes' research stream so Hermes 'monitors' it — it surfaces
    on the Open Trades card's Hermes section and in the Hermes hub, same as any research finding."""
    conn = None
    try:
        import json
        from db_adapter import _get_conn
        conn = _get_conn(); cur = conn.cursor()
        # research_type='stop_health' is the identity; thesis_type/status must satisfy the table's CHECKs
        # (thesis_type ∈ bullish/bearish/neutral/mixed → 'neutral'; status ∈ staged/.. → 'staged').
        cur.execute("""INSERT INTO hermes_research_intelligence
            (source, hermes_agent_name, research_type, symbol, topic, summary, thesis, thesis_type,
             evidence_json, confidence_score, model_used, status, category_lifecycle, freshness_date, created_at)
            VALUES (%s,%s,'stop_health',%s,%s,%s,%s,'neutral',%s::jsonb,%s,'stop_lifecycle_monitor',
                    'staged','stop', CURRENT_DATE, NOW())""",
            ("hermes", "StopHealthMonitor", symbol, f"Stop health: {condition}",
             f"{condition} — {line}", line, json.dumps(payload), 0.95))
        conn.commit()
    except Exception:
        if conn is not None:
            try:
                conn.rollback()   # never leave the shared connection in an aborted txn
            except Exception:
                pass


def _log_health_event(ok: bool, summary: dict) -> None:
    try:
        from db_adapter import _get_conn
        conn = _get_conn(); cur = conn.cursor()
        cur.execute("""CREATE TABLE IF NOT EXISTS system_health_events (
                         id SERIAL PRIMARY KEY, component TEXT, event_type TEXT, severity TEXT,
                         message TEXT, action_taken TEXT, success BOOLEAN, created_at TIMESTAMPTZ DEFAULT NOW())""")
        cur.execute("""INSERT INTO system_health_events (component, event_type, severity, message, success)
                       VALUES (%s,'STOP_HEALTH_SCAN',%s,%s,%s)""",
                    (_COMPONENT, "WARN" if not ok else "INFO",
                     f"{summary.get('total')} stops · health {summary.get('by_health')}", ok))
        conn.commit()
    except Exception:
        pass


def _portfolio_drawdown_guard() -> dict | None:
    """Portfolio-level drawdown guard (stop_policy.yaml portfolio_drawdown_guard).

    Advisory only — compares the newest daily_system_metrics portfolio_value to its
    peak over peak_window_days and alerts at alert_pct / critical_pct below peak.
    Never places or modifies an order. Fail-soft: any error returns None."""
    try:
        import holding_family as hf
        cfg = (hf._policy().get("portfolio_drawdown_guard") or {})
        if not cfg.get("enabled"):
            return None
        window = int(cfg.get("peak_window_days") or 90)
        alert_pct = float(cfg.get("alert_pct") or 10.0)
        critical_pct = float(cfg.get("critical_pct") or 12.0)
        dedup_h = int(cfg.get("dedup_hours") or 6)
        from db_adapter import _get_conn
        conn = _get_conn()
        cur = conn.cursor()
        cur.execute("""SELECT metric_date, portfolio_value FROM daily_system_metrics
                       WHERE metric_date >= CURRENT_DATE - %s::int
                         AND portfolio_value IS NOT NULL AND portfolio_value > 0
                       ORDER BY metric_date""", (window,))
        rows = cur.fetchall()
        conn.rollback()
        if len(rows) < 2:
            return None
        peak_date, peak = max(rows, key=lambda r: float(r[1]))
        cur_date, cur_val = rows[-1]
        dd_pct = (float(peak) - float(cur_val)) / float(peak) * 100.0
        out = {"peak_usd": float(peak), "peak_date": str(peak_date),
               "current_usd": float(cur_val), "as_of": str(cur_date),
               "drawdown_pct": round(dd_pct, 2), "window_days": window,
               "alert_pct": alert_pct, "critical_pct": critical_pct}
        if dd_pct < alert_pct:
            return {**out, "level": "ok"}
        level = "critical" if dd_pct >= critical_pct else "warning"
        cond = "PORTFOLIO_DRAWDOWN_CRITICAL" if level == "critical" else "PORTFOLIO_DRAWDOWN"
        line = (f"portfolio ${float(cur_val):,.0f} is {dd_pct:.1f}% below its {window}d peak "
                f"${float(peak):,.0f} ({peak_date}) — review stops/exposure (advisory; no orders placed)")
        if not _recently_alerted("PORTFOLIO", cond, hours=dedup_h):
            payload = {"kind": "stop_health", "condition": cond, **out}
            _siem("PORTFOLIO", "critical" if level == "critical" else "warning",
                  f"[stop-health] {cond} · {line}", payload)
            _send_telegram(f"{'🚨' if level == 'critical' else '⚠️'} PORTFOLIO DRAWDOWN — {line}")
            _hermes_finding("PORTFOLIO", cond, line, payload)
        return {**out, "level": level, "condition": cond}
    except Exception as e:
        print(f"stop_health: drawdown guard skipped ({e})", file=sys.stderr)
        return None


def run(quiet: bool = False) -> dict:
    import stop_lifecycle_monitor as slm
    res = slm.scan(persist=True)
    summary, alerts = res["summary"], res["alerts"]
    fired = []
    for r in alerts:
        sym, acct = r["symbol"], r["account"]
        # the single most severe condition for the message
        # severity MUST be one of the alert_events constraint values: info|warning|urgent|critical
        # P/L that WOULD be realized if this stop fills — the number the operator
        # actually decides on (a near-trigger on a deep loser reads very
        # differently from one locking a gain).
        _pl = _pl_if_fired(sym, acct, r.get("stop_price"), r.get("qty") or r.get("held_qty"))
        if "orphaned" in r["flags"]:
            cond, sev, line = "ORPHANED", "urgent", f"stop with no matching {acct} holding (#{r['order_id']}) — on trigger it could short/reject. Cancel it."
        elif "oversized" in r["flags"]:
            cond, sev, line = "OVERSIZED", "urgent", f"stop covers {r['qty']} sh but you hold {r['held_qty']} — modify to {r['held_qty']} sh.{_pl_line(_pl)}"
        elif "filled" in r["flags"]:
            cond, sev, line = "TRIGGERED", "urgent", f"stop FILLED (#{r['order_id']}) — position may be flat; review.{_pl_line(_pl)}"
        else:
            cond, sev, line = "NEAR_TRIGGER", "warning", f"price within {r.get('proximity_pct')}% of stop ${r.get('stop_price')} — about to fire.{_pl_line(_pl)}"
        payload = {"kind": "stop_health", "condition": cond,
                   "pl_if_fired": (_pl or {}).get("pl"), "pl_if_fired_pct": (_pl or {}).get("pct"),
                   **{k: r.get(k) for k in
                   ("account", "symbol", "broker", "order_id", "order_type", "stop_price", "qty",
                    "held_qty", "current_price", "proximity_pct", "coverage", "lifecycle", "health")}}
        # dedup ALL persistence (SIEM + Telegram + Hermes) to one per (symbol,condition) per 2h — the cron
        # runs every 10 min, so without this a single stop-out would write a row every run for hours.
        if not _recently_alerted(sym, cond):
            _siem(sym, sev, f"[stop-health] {cond} · {sym}@{acct} · {line}", payload)
            _send_telegram(f"{'🚨' if sev == 'urgent' else '⚠️'} STOP HEALTH — {cond}: *{sym}* ({acct})\n{line}")
            _hermes_finding(sym, cond, line, payload)   # enter Hermes' research stream (deduped via the same 2h window)
            fired.append(f"{sym}:{cond}")
    dd = _portfolio_drawdown_guard()
    if dd and dd.get("level") in ("warning", "critical"):
        fired.append(f"PORTFOLIO:{dd['condition']}")
    summary["portfolio_drawdown"] = dd
    _log_health_event(ok=(not alerts), summary=summary)
    if not quiet:
        print(f"stop_health: {summary['total']} stops · health {summary['by_health']} · "
              f"alerts {len(alerts)} · telegram fired {fired or 'none'} · "
              f"drawdown {dd.get('drawdown_pct') if dd else 'n/a'}%")
    return {"summary": summary, "alert_count": len(alerts), "telegram_fired": fired,
            "portfolio_drawdown": dd}


if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv(str(PROJECT_ROOT / ".env"))
    run(quiet="--quiet" in sys.argv)
