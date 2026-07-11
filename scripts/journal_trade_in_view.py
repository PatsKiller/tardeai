#!/usr/bin/env python3
"""journal_trade_in_view.py — TradeInView analytics (read-only + filter CRUD).

Exit intelligence, Zella score, behavioral/tilt, sector breakdown, options summary, CSV export.
"""
from __future__ import annotations

import csv
import io
import json
from collections import defaultdict
from datetime import datetime
from typing import Any

_DOW = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
_SESSIONS = (
    ("premarket", 0, 9),
    ("open", 9, 11),
    ("midday", 11, 14),
    ("close", 14, 16),
    ("after_hours", 16, 24),
)


def _q(sql, params=None, fetch="all"):
    from db_adapter import _execute
    return _execute(sql, params, fetch) or ([] if fetch == "all" else None)


def _agg(rows, pnl_key="pnl"):
    n = len(rows)
    wins = sum(1 for r in rows if float(r.get(pnl_key) or 0) > 0)
    net = sum(float(r.get(pnl_key) or 0) for r in rows)
    return {
        "trades": n,
        "wins": wins,
        "win_rate": round(wins / n * 100, 1) if n else 0.0,
        "net_pnl": round(net, 2),
    }


def _trade_where(account=None, date_from=None, date_to=None):
    parts, params = ["tc.buy_price > 0 OR tc.pnl != 0"], []
    if account:
        parts.append("tc.account = %s")
        params.append(account)
    if date_from:
        parts.append("tc.close_date >= %s::date")
        params.append(date_from)
    if date_to:
        parts.append("tc.close_date <= %s::date")
        params.append(date_to)
    return " AND ".join(parts), params


def fetch_closed_trades(account=None, date_from=None, date_to=None, limit=2000):
    where, params = _trade_where(account, date_from, date_to)
    params.append(int(limit))
    return _q(f"""
        SELECT tc.symbol, tc.account, tc.open_date::text, tc.close_date::text, tc.trade_type,
               tc.shares, tc.buy_price, tc.sell_price, tc.pnl, tc.pnl_pct, tc.hold_days,
               (tc.symbol || ':' || tc.account || ':' || tc.close_date::text) AS trade_key,
               COALESCE(eq.entry_time, srt.entry_time)::text AS entry_time,
               COALESCE(eq.exit_time, srt.exit_time)::text AS exit_time
        FROM trade_closed tc
        LEFT JOIN LATERAL (
            SELECT entry_time, exit_time FROM schwab_round_trips s
            WHERE UPPER(s.symbol) = UPPER(tc.symbol) AND s.account = tc.account
              AND s.exit_time::date = tc.close_date
              AND ABS(s.entry_price - tc.buy_price) < 0.08 AND s.entry_time IS NOT NULL
            ORDER BY ABS(s.entry_price - tc.buy_price), s.exit_time DESC LIMIT 1
        ) srt ON true
        LEFT JOIN LATERAL (
            SELECT entry_time, exit_time FROM trade_execution_quality eq
            WHERE UPPER(eq.symbol) = UPPER(tc.symbol) AND eq.entry_time::date = tc.close_date
              AND ABS(eq.entry_price - tc.buy_price) < 0.08
            ORDER BY ABS(eq.entry_price - tc.buy_price), eq.exit_time DESC LIMIT 1
        ) eq ON true
        WHERE {where}
        ORDER BY tc.close_date DESC
        LIMIT %s
    """, params)


def exit_intelligence(account=None, days=365):
    """MAE/MFE, capture, exit timing, best-exit vs actual."""
    date_from = None
    if days:
        date_from = (datetime.utcnow().date().replace(year=datetime.utcnow().year - 1)
                     if days > 400 else None)
    params: list[Any] = []
    where = ["ti.status = 'closed'", "ti.exit_time IS NOT NULL"]
    if account:
        where.append("ti.execution_account = %s")
        params.append(account)
    if days and days < 4000:
        where.append("ti.exit_time > now() - (%s || ' days')::interval")
        params.append(int(days))

    rows = _q(f"""
        SELECT ti.symbol, ti.strategy_id, ti.execution_account AS account,
               ti.entry_time, ti.exit_time, ti.entry_price, ti.exit_price, ti.pnl, ti.r_multiple,
               eq.mfe_after_entry, eq.mae_after_entry, eq.capture_ratio, eq.mfe_after_exit,
               eq.mfe_after_exit_pct, eq.exit_timing_grade, eq.runner_type,
               EXTRACT(HOUR FROM ti.entry_time AT TIME ZONE 'America/New_York') AS entry_hour_et,
               EXTRACT(HOUR FROM ti.exit_time AT TIME ZONE 'America/New_York') AS exit_hour_et,
               pc.giveback_pct_of_mfe, pc.capture_ratio AS pc_capture, pc.measurable,
               pc.money_left_usd, pc.max_profit_usd, pc.failure_class
        FROM trade_instances ti
        LEFT JOIN trade_execution_quality eq
          ON eq.symbol = ti.symbol
         AND eq.entry_time::date = ti.entry_time::date
        LEFT JOIN trade_profit_capture_analysis pc ON pc.trade_instance_id = ti.id
        WHERE {' AND '.join(where)}
        ORDER BY ti.exit_time DESC
        LIMIT 500
    """, params)

    measurable = [r for r in rows if r.get("measurable") or r.get("capture_ratio") is not None]
    winners = [r for r in measurable if float(r.get("pnl") or 0) > 0]

    capture_vals = [float(r["capture_ratio"]) for r in measurable if r.get("capture_ratio") is not None]
    giveback_vals = [float(r["giveback_pct_of_mfe"]) for r in measurable
                     if r.get("giveback_pct_of_mfe") is not None]

    by_hour: dict[int, list] = defaultdict(list)
    for r in rows:
        h = r.get("exit_hour_et")
        if h is not None:
            by_hour[int(h)].append(r)

    exit_timing = []
    for h in sorted(by_hour):
        exit_timing.append({"hour": h, "label": f"{h:02d}:00", **_agg(by_hour[h], "pnl")})

    eod = {"intraday": [], "eod": []}
    for r in rows:
        et = r.get("exit_time")
        if not et:
            continue
        bucket = "eod" if hasattr(et, "hour") and et.hour >= 15 else "intraday"
        eod[bucket].append(r)

    return {
        "ok": True,
        "sample": len(rows),
        "measurable": len(measurable),
        "avg_capture_ratio": round(sum(capture_vals) / len(capture_vals), 3) if capture_vals else None,
        "avg_giveback_pct": round(sum(giveback_vals) / len(giveback_vals) * 100, 1) if giveback_vals else None,
        "money_left_total": round(sum(float(r.get("money_left_usd") or 0) for r in measurable), 2),
        "exit_timing_by_hour": exit_timing,
        "eod_vs_intraday": {k: _agg(v, "pnl") for k, v in eod.items()},
        "failure_classes": _count_field(measurable, "failure_class"),
        "runner_types": _count_field(measurable, "runner_type"),
        "top_giveback": sorted(
            [r for r in measurable if float(r.get("money_left_usd") or 0) > 0],
            key=lambda x: float(x.get("money_left_usd") or 0), reverse=True)[:15],
    }


def _count_field(rows, field):
    m: dict[str, int] = defaultdict(int)
    for r in rows:
        v = r.get(field) or "unknown"
        m[str(v)] += 1
    return [{"label": k, "count": v} for k, v in sorted(m.items(), key=lambda x: -x[1])]


def zella_score(account=None, days=365):
    """Composite 0-100: profitability, risk mgmt, consistency, discipline, psychology."""
    params: list[Any] = [int(days)]
    acct_sql = ""
    if account:
        acct_sql = " AND tc.account = %s"
        params.append(account)

    stats = _q(f"""
        SELECT COUNT(*) total,
               SUM(CASE WHEN tc.pnl > 0 THEN 1 ELSE 0 END) wins,
               SUM(tc.pnl) net_pnl,
               SUM(CASE WHEN tc.pnl > 0 THEN tc.pnl ELSE 0 END) gross_win,
               ABS(SUM(CASE WHEN tc.pnl < 0 THEN tc.pnl ELSE 0 END)) gross_loss,
               STDDEV(tc.pnl) pnl_sd
        FROM trade_closed tc
        WHERE (tc.buy_price > 0 OR tc.pnl != 0)
          AND tc.close_date > now() - (%s || ' days')::interval
          {acct_sql}
    """, params, fetch="one") or {}

    rev_params: list[Any] = [int(days)]
    rev_acct = ""
    if account:
        rev_acct = " AND tc.account = %s"
        rev_params.append(account)
    rev = _q(f"""
        SELECT COUNT(*) reviewed,
               COUNT(*) FILTER (WHERE followed_plan = true) followed,
               COUNT(*) FILTER (WHERE emotion_during IN ('tilt','greed','fear','moved stop')) tiltish,
               AVG(realized_r) avg_r
        FROM journal_trade_reviews r
        JOIN trade_closed tc ON r.trade_key = (tc.symbol || ':' || tc.account || ':' || tc.close_date::text)
        WHERE tc.close_date > now() - (%s || ' days')::interval {rev_acct}
    """, rev_params, fetch="one") or {}

    total = int(stats.get("total") or 0)
    wins = int(stats.get("wins") or 0)
    gl = float(stats.get("gross_loss") or 0)
    gw = float(stats.get("gross_win") or 0)
    pf = gw / gl if gl > 0 else (2.0 if gw > 0 else 0)
    wr = wins / total if total else 0
    sd = float(stats.get("pnl_sd") or 1) or 1
    consistency = max(0, min(100, 100 - min(sd / max(abs(float(stats.get("net_pnl") or 1) / max(total, 1)), 1) * 20, 100)))

    profitability = min(100, max(0, (pf - 0.5) * 40 + wr * 40))
    risk_mgmt = min(100, max(0, 50 + float(rev.get("avg_r") or 0) * 25))
    reviewed = int(rev.get("reviewed") or 0)
    followed = int(rev.get("followed") or 0)
    discipline = (followed / reviewed * 100) if reviewed else 50
    tiltish = int(rev.get("tiltish") or 0)
    psychology = max(0, 100 - (tiltish / max(reviewed, 1) * 100))

    components = {
        "profitability": round(profitability, 1),
        "risk_management": round(risk_mgmt, 1),
        "consistency": round(consistency, 1),
        "discipline": round(discipline, 1),
        "psychology": round(psychology, 1),
    }
    score = round(sum(components.values()) / len(components), 1)
    return {"ok": True, "score": score, "components": components, "trades": total, "reviewed": reviewed}


def behavioral_analytics(account=None, days=365):
    """Tilt, revenge, streaks, mistake $ cost."""
    params: list[Any] = [int(days)]
    acct = ""
    if account:
        acct = " AND tc.account = %s"
        params.append(account)

    reviews = _q(f"""
        SELECT r.trade_key, r.mistake_tags, r.emotion_during, r.emotion_before,
               r.followed_plan, tc.pnl, tc.close_date::text AS close_date
        FROM journal_trade_reviews r
        JOIN trade_closed tc ON r.trade_key = (tc.symbol || ':' || tc.account || ':' || tc.close_date::text)
        WHERE tc.close_date > now() - (%s || ' days')::interval {acct}
        ORDER BY tc.close_date
    """, params)

    mistake_cost: dict[str, dict] = defaultdict(lambda: {"count": 0, "pnl": 0.0})
    for r in reviews:
        for tag in (r.get("mistake_tags") or []):
            mistake_cost[tag]["count"] += 1
            mistake_cost[tag]["pnl"] += float(r.get("pnl") or 0)

    tilt_trades = [r for r in reviews if (r.get("emotion_during") or "").lower() in
                   ("tilt", "greed", "fear", "moved stop", "revenge")]
    tilt_pnl = sum(float(r.get("pnl") or 0) for r in tilt_trades)

    # Win/loss streak impact
    daily = _q(f"""
        SELECT close_date::text d, SUM(pnl) pnl
        FROM trade_closed tc
        WHERE close_date > now() - (%s || ' days')::interval {acct}
        GROUP BY close_date ORDER BY close_date
    """, params)
    after_win, after_loss = [], []
    for i in range(1, len(daily)):
        prev = float(daily[i - 1].get("pnl") or 0)
        cur = {"pnl": float(daily[i].get("pnl") or 0), "date": daily[i]["d"]}
        (after_win if prev > 0 else after_loss if prev < 0 else []).append(cur)

    critique_insights: dict = {}
    try:
        import journal_ai_critique as jac
        ins = jac.coaching_insights(days=min(int(days), 90))
        critique_insights = {
            "critique_count": ins.get("critique_count", 0),
            "stale_count": ins.get("stale_count", 0),
            "top_improvements": (ins.get("top_improvements") or [])[:6],
            "top_strengths": (ins.get("top_strengths") or [])[:4],
            "coaching_bullets": (ins.get("coaching_bullets") or [])[:4],
            "highlights": (ins.get("highlights") or [])[:3],
        }
    except Exception:
        pass

    return {
        "ok": True,
        "mistake_cost": sorted(
            [{"tag": k, **v, "avg_pnl": round(v["pnl"] / v["count"], 2) if v["count"] else 0}
             for k, v in mistake_cost.items()],
            key=lambda x: x["count"], reverse=True),
        "tilt": {"trades": len(tilt_trades), "net_pnl": round(tilt_pnl, 2)},
        "after_winning_day": _agg(after_win, "pnl"),
        "after_losing_day": _agg(after_loss, "pnl"),
        "revenge_tags": sum(1 for r in reviews if "Revenge" in (r.get("mistake_tags") or [])
                            or "revenge" in (r.get("emotion_during") or "").lower()),
        "ai_critique": critique_insights,
    }


def sector_breakdown(account=None, days=365):
    """Symbol P&L grouped by sector from holdings/state."""
    import os
    from pathlib import Path
    state = Path(__file__).resolve().parent.parent / "state"
    sector_map: dict[str, str] = {}
    for fname in ("holdings.json", "portfolio_snapshot.json"):
        p = state / fname
        if p.exists():
            try:
                data = json.loads(p.read_text())
                for h in (data.get("holdings") or data.get("positions") or []):
                    sym = (h.get("symbol") or "").upper()
                    sec = h.get("sector") or h.get("Sector") or "Unknown"
                    if sym:
                        sector_map[sym] = sec
            except Exception:
                pass

    params: list[Any] = [int(days)]
    acct = ""
    if account:
        acct = " AND account = %s"
        params.append(account)

    rows = _q(f"""
        SELECT symbol, SUM(pnl) net_pnl, COUNT(*) trades,
               COUNT(*) FILTER (WHERE pnl > 0) wins
        FROM trade_closed
        WHERE close_date > now() - (%s || ' days')::interval {acct}
        GROUP BY symbol
    """, params)

    by_sector: dict[str, list] = defaultdict(list)
    for r in rows:
        sec = sector_map.get((r.get("symbol") or "").upper(), "Unknown")
        by_sector[sec].append(r)

    out = []
    for sec, items in by_sector.items():
        out.append({"sector": sec, **_agg(items, "net_pnl"),
                    "symbols": len(items),
                    "net_pnl": round(sum(float(i.get("net_pnl") or 0) for i in items), 2)})
    out.sort(key=lambda x: x["net_pnl"], reverse=True)
    return {"ok": True, "sectors": out}


def _is_option_symbol(sym: str) -> bool:
    import re
    return bool(re.search(r"[0-9]{6}[CP][0-9]", sym or ""))


def _parse_occ(sym: str) -> dict:
    import re
    m = re.match(r"^([A-Z]+)(\d{6})([CP])(\d+)$", (sym or "").replace(" ", "").upper())
    if not m:
        return {}
    und, yymmdd, cp, strike = m.groups()
    return {"underlying": und, "option_type": "call" if cp == "C" else "put", "strike": float(strike) / 1000.0}


def options_journal_summary(account=None, days=365):
    """P5: closed option trades + open legs + book greeks."""
    params: list[Any] = [int(days)]
    acct = ""
    if account:
        acct = " AND account = %s"
        params.append(account)
    rows = _q(f"""
        SELECT symbol, trade_type, pnl, close_date::text, account, shares, buy_price, sell_price
        FROM trade_closed
        WHERE close_date > now() - (%s || ' days')::interval {acct}
          AND (trade_type ILIKE '%%option%%' OR symbol ~ '[0-9]{{6}}[CP][0-9]')
        ORDER BY close_date DESC LIMIT 200
    """, params)

    groups: dict[str, dict] = {}
    for r in rows:
        parsed = _parse_occ(r.get("symbol") or "")
        und = parsed.get("underlying") or (r.get("symbol") or "")[:6]
        gk = f"{und}:{r.get('close_date')}:{r.get('account')}"
        g = groups.setdefault(gk, {"underlying": und, "close_date": r.get("close_date"),
                                   "account": r.get("account"), "legs": [], "net_pnl": 0.0})
        g["legs"].append({**r, **parsed})
        g["net_pnl"] += float(r.get("pnl") or 0)

    open_legs = []
    book_greeks = {}
    try:
        import options_engine as oe
        open_legs = oe._fetch_schwab_option_positions()
        if account:
            open_legs = [p for p in open_legs if p.get("account_key") == account]
        try:
            import options_desk_enterprise as ode
            book_greeks = ode.aggregate_book_greeks(open_legs, {}) or {}
        except Exception:
            book_greeks = {}
    except Exception:
        pass

    by_moneyness: dict[str, list] = defaultdict(list)
    for p in open_legs:
        und = p.get("underlying") or ""
        spot = p.get("strike") or 0
        m = "ATM"
        if p.get("option_type") == "call":
            m = "ITM" if (p.get("side") == "long" and spot) else "OTM"
        by_moneyness[m].append(p)

    return {
        "ok": True,
        "options_trades": len(rows),
        "trades": rows,
        "multileg_groups": list(groups.values())[:50],
        "open_legs": open_legs[:40],
        "book_greeks": book_greeks,
        "by_moneyness_open": {k: len(v) for k, v in by_moneyness.items()},
        **_agg(rows),
    }


def monte_carlo(account=None, days=365, simulations=500, trades_per_path=0, include_curves=True):
    """Bootstrap equity paths from historical trade P&L."""
    import random
    params: list[Any] = [int(days)]
    acct = ""
    if account:
        acct = " AND account = %s"
        params.append(account)
    pnls = [float(r["pnl"]) for r in _q(f"""
        SELECT pnl FROM trade_closed
        WHERE close_date > now() - (%s || ' days')::interval {acct}
          AND pnl IS NOT NULL
    """, params)]
    if len(pnls) < 5:
        return {"ok": False, "error": "need at least 5 trades", "sample_size": len(pnls)}
    n_hist = len(pnls)
    path_len = int(trades_per_path) if int(trades_per_path or 0) > 0 else min(30, max(10, n_hist // 3))
    path_len = min(path_len, n_hist)
    n_sims = int(simulations)
    curves: list[list[float]] = []
    finals: list[float] = []
    for _ in range(n_sims):
        path = random.choices(pnls, k=path_len)
        cum = 0.0
        curve: list[float] = []
        for p in path:
            cum += p
            curve.append(round(cum, 2))
        curves.append(curve)
        finals.append(cum)
    finals.sort()
    n = len(finals)
    bands = []
    for i in range(path_len):
        step = sorted(c[i] for c in curves)
        bands.append({
            "trade": i + 1,
            "p10": round(step[int(n * 0.1)], 2),
            "p50": round(step[n // 2], 2),
            "p90": round(step[int(n * 0.9)], 2),
        })
    out = {
        "ok": True,
        "simulations": n_sims,
        "trades_per_path": path_len,
        "path_auto": int(trades_per_path or 0) <= 0,
        "median_pnl": round(finals[n // 2], 2),
        "p10": round(finals[int(n * 0.1)], 2),
        "p90": round(finals[int(n * 0.9)], 2),
        "prob_profit": round(sum(1 for s in finals if s > 0) / n * 100, 1),
        "sample_size": n_hist,
        "bands": bands,
    }
    if include_curves:
        import random as _rnd
        k = min(12, len(curves))
        out["sample_paths"] = _rnd.sample(curves, k)
    return out


def pivot_report(account=None, days=365, row_dim="setup_family", col_dim="market_regime"):
    """Cross-tab from journal reviews."""
    allowed = {"setup_family", "market_regime", "timeframe", "direction", "emotion_before"}
    if row_dim not in allowed:
        row_dim = "setup_family"
    if col_dim not in allowed:
        col_dim = "market_regime"
    params: list[Any] = [int(days)]
    acct = ""
    if account:
        acct = " AND tc.account = %s"
        params.append(account)
    rows = _q(f"""
        SELECT r.{row_dim} AS row_val, r.{col_dim} AS col_val, tc.pnl
        FROM journal_trade_reviews r
        JOIN trade_closed tc ON r.trade_key = (tc.symbol || ':' || tc.account || ':' || tc.close_date::text)
        WHERE tc.close_date > now() - (%s || ' days')::interval {acct}
    """, params)
    grid: dict[str, dict[str, list]] = defaultdict(lambda: defaultdict(list))
    for r in rows:
        rv = r.get("row_val") or "—"
        cv = r.get("col_val") or "—"
        grid[str(rv)][str(cv)].append(r)
    cells = []
    for rv, cols in grid.items():
        for cv, items in cols.items():
            cells.append({"row": rv, "col": cv, **_agg(items, "pnl")})
    return {"ok": True, "row_dim": row_dim, "col_dim": col_dim, "cells": cells}


def export_tax_csv(account=None, date_from=None, date_to=None):
    """Realized gains with wash-sale flags from schwab_cost_basis_lots."""
    where, params = ["kind = 'realized'"], []
    if account:
        where.append("account = %s")
        params.append(account)
    if date_from:
        where.append("closed_date >= %s::date")
        params.append(date_from)
    if date_to:
        where.append("closed_date <= %s::date")
        params.append(date_to)
    rows = _q(f"""
        SELECT account, symbol, closed_date::text, quantity, cost_basis, proceeds,
               realized_gain, term, wash_sale
        FROM schwab_cost_basis_lots
        WHERE {' AND '.join(where)}
        ORDER BY closed_date DESC
    """, params)
    buf = io.StringIO()
    if not rows:
        return ""
    fields = ["account", "symbol", "closed_date", "quantity", "cost_basis", "proceeds",
              "realized_gain", "term", "wash_sale"]
    w = csv.DictWriter(buf, fieldnames=fields)
    w.writeheader()
    for r in rows:
        w.writerow({k: r.get(k) for k in fields})
    return buf.getvalue()


def session_recap_get(session_date=None):
    sd = session_date or str(__import__("datetime").date.today())
    row = _q("SELECT * FROM journal_session_recaps WHERE session_date = %s::date", [sd], fetch="one")
    return {"ok": True, "recap": row}


def session_recap_save(body: dict):
    sd = body.get("session_date") or str(__import__("datetime").date.today())
    row = _q("""
        INSERT INTO journal_session_recaps
          (session_date, account, pre_market_plan, eod_reflection, planned_trades, actual_pnl, trades_count, tilt_detected, payload)
        VALUES (%s::date, %s, %s, %s, %s::jsonb, %s, %s, %s, %s::jsonb)
        ON CONFLICT (session_date) DO UPDATE SET
          account=EXCLUDED.account, pre_market_plan=EXCLUDED.pre_market_plan,
          eod_reflection=EXCLUDED.eod_reflection, planned_trades=EXCLUDED.planned_trades,
          actual_pnl=EXCLUDED.actual_pnl, trades_count=EXCLUDED.trades_count,
          tilt_detected=EXCLUDED.tilt_detected, payload=EXCLUDED.payload, updated_at=NOW()
        RETURNING id
    """, [
        sd, body.get("account"), body.get("pre_market_plan"), body.get("eod_reflection"),
        json.dumps(body.get("planned_trades") or []),
        body.get("actual_pnl"), body.get("trades_count"), bool(body.get("tilt_detected")),
        json.dumps(body.get("payload") or {}),
    ], fetch="one")
    return int(row["id"]) if row else None


def attachment_save(trade_key: str | None, session_date: str | None, filename: str,
                    content_b64: str, kind: str = "screenshot", mime: str = "image/png", notes: str = ""):
    import base64
    from pathlib import Path
    root = Path(__file__).resolve().parent.parent / "data" / "journal_attachments"
    root.mkdir(parents=True, exist_ok=True)
    safe = "".join(c if c.isalnum() or c in ".-_" else "_" for c in filename)[:120]
    path = root / safe
    raw = base64.b64decode(content_b64.split(",")[-1] if "," in content_b64 else content_b64)
    path.write_bytes(raw)
    row = _q("""
        INSERT INTO journal_attachments (trade_key, session_date, kind, filename, mime_type, storage_path, notes)
        VALUES (%s, %s::date, %s, %s, %s, %s, %s) RETURNING id
    """, [trade_key, session_date, kind, safe, mime, str(path), notes], fetch="one")
    return int(row["id"]) if row else None


def attachments_list(trade_key: str | None = None, session_date: str | None = None):
    parts, params = ["1=1"], []
    if trade_key:
        parts.append("trade_key = %s")
        params.append(trade_key)
    if session_date:
        parts.append("session_date = %s::date")
        params.append(session_date)
    return _q(f"SELECT id, trade_key, session_date::text, kind, filename, mime_type, notes, created_at::text FROM journal_attachments WHERE {' AND '.join(parts)} ORDER BY created_at DESC", params)


def export_csv(account=None, date_from=None, date_to=None, tax=False):
    if tax:
        return export_tax_csv(account, date_from, date_to)
    trades = fetch_closed_trades(account, date_from, date_to)
    buf = io.StringIO()
    if not trades:
        return ""
    fields = list(trades[0].keys())
    w = csv.DictWriter(buf, fieldnames=fields, extrasaction="ignore")
    w.writeheader()
    for t in trades:
        w.writerow({k: t.get(k) for k in fields})
    return buf.getvalue()


def saved_filters_list():
    return _q("SELECT id, name, payload, created_at::text, updated_at::text FROM journal_saved_filters ORDER BY updated_at DESC")


def saved_filter_upsert(name: str, payload: dict, fid=None):
    if fid:
        _q("UPDATE journal_saved_filters SET name=%s, payload=%s::jsonb, updated_at=NOW() WHERE id=%s RETURNING id",
           [name, json.dumps(payload), int(fid)], fetch="one")
        return int(fid)
    row = _q("INSERT INTO journal_saved_filters (name, payload) VALUES (%s, %s::jsonb) RETURNING id",
             [name, json.dumps(payload)], fetch="one")
    return int(row["id"]) if row else None


def saved_filter_delete(fid: int):
    _q("DELETE FROM journal_saved_filters WHERE id=%s", [int(fid)], fetch="none")
    return True


def tag_groups():
    return _q("SELECT group_key, label, tags, parent_group FROM journal_tag_groups ORDER BY group_key")


def _load_tagging_policy() -> dict:
    from pathlib import Path
    root = Path(__file__).resolve().parent.parent
    try:
        from config_db_loader import get_config
        cfg = get_config("trade_in_view_tagging_policy", fallback_path="config/trade_in_view_tagging_policy.json")
        if cfg:
            return cfg
    except Exception:
        pass
    try:
        return json.loads((root / "config/trade_in_view_tagging_policy.json").read_text())
    except Exception:
        return {"min_total_tags": 3, "required_categories": ["strategy", "setup"], "queue_page_size": 50}


def _review_payload(review: dict | None) -> dict:
    if not review:
        return {}
    p = review.get("payload") or {}
    if isinstance(p, str):
        try:
            p = json.loads(p)
        except Exception:
            p = {}
    return p if isinstance(p, dict) else {}


def score_trade_tags(review: dict | None, policy: dict | None = None) -> dict:
    """Return tagging completeness for one journal_trade_reviews row (or None)."""
    policy = policy or _load_tagging_policy()
    if not review:
        return {"complete": False, "tag_count": 0, "missing": ["review"], "score": 0, "summary": "—"}

    payload = _review_payload(review)
    pending_auto = bool(payload.get("auto_tagged") and not payload.get("operator_confirmed"))
    if payload.get("operator_reviewed_skip"):
        return {"complete": True, "tag_count": 99, "missing": [], "score": 100, "summary": "reviewed", "skipped": True}

    tagging_done = bool(payload.get("tagging_complete") and not pending_auto)
    operator_signed = bool(payload.get("operator_reviewed"))

    missing: list[str] = []
    setup_family = (review.get("setup_family") or "").strip()
    setup_types = review.get("setup_types") or []
    if isinstance(setup_types, str):
        setup_types = [setup_types] if setup_types else []
    setup_name = (review.get("setup_name") or "").strip()

    if not setup_family:
        missing.append("strategy")
    if not setup_types and not setup_name:
        missing.append("setup")
    if policy.get("require_market_regime") and not (review.get("market_regime") or "").strip():
        missing.append("market_regime")
    if policy.get("require_psychology") and not (review.get("emotion_before") or "").strip():
        missing.append("psychology")

    for cat in policy.get("high_priority_categories") or []:
        if cat == "market_regime" and not (review.get("market_regime") or "").strip():
            if "market_regime" not in missing:
                missing.append("market_regime")
        if cat == "psychology" and not (review.get("emotion_before") or "").strip():
            if "psychology" not in missing:
                missing.append("psychology")

    tag_count = 0
    if setup_family:
        tag_count += 1
    tag_count += len(setup_types)
    if setup_name and not setup_types:
        tag_count += 1
    if (review.get("market_regime") or "").strip():
        tag_count += 1
    if (review.get("emotion_before") or "").strip():
        tag_count += 1
    tag_count += len(review.get("mistake_tags") or [])
    tag_count += len(review.get("strength_tags") or [])

    auto_stub = False
    if policy.get("flag_auto_classified_stubs", True):
        lesson = review.get("lesson_learned") or ""
        notes = review.get("review_notes") or ""
        auto_stub = "Auto-classified" in lesson or "AI suggested" in notes
        if auto_stub and not operator_signed and (not setup_types or tag_count < int(policy.get("min_total_tags", 3))):
            if "operator_review" not in missing:
                missing.append("operator_review")

    if payload.get("auto_tagged") and not payload.get("operator_confirmed"):
        if not policy.get("auto_confirm_enriched_tags", True):
            if "operator_review" not in missing:
                missing.append("operator_review")

    if payload.get("operator_confirmed") or payload.get("operator_reviewed"):
        missing = [m for m in missing if m != "operator_review"]

    min_tags = int(policy.get("min_total_tags", 3))
    if tagging_done:
        incomplete = False
        score = 100
        tag_count = max(tag_count, 99)
    else:
        incomplete = bool(missing) or tag_count < min_tags
        score = 0 if incomplete else min(100, 40 + tag_count * 8)
        if not incomplete and tag_count >= min_tags:
            score = max(score, 75)
        if not missing and tag_count >= min_tags + 2:
            score = 100

    # AI trade critique readiness
    critique = payload.get("ai_critique") if isinstance(payload.get("ai_critique"), dict) else None
    crit_meta = payload.get("ai_critique_meta") or {}
    nar = (critique or {}).get("narrative") or {}
    has_critique = bool(critique) and crit_meta.get("status") != "error" and bool(
        nar.get("summary") or critique.get("trade_classification"))
    ai_stale = False
    if has_critique:
        try:
            import journal_ai_critique as jac
            ai_stale, _ = jac._stale_from_tags(review, crit_meta, critique)
        except Exception:
            ai_stale = bool(crit_meta.get("stale"))
    if policy.get("queue_requires_ai_critique", False):
        if not has_critique:
            if "ai_critique" not in missing:
                missing.append("ai_critique")
        elif ai_stale:
            if "ai_critique_stale" not in missing:
                missing.append("ai_critique_stale")

    if missing:
        incomplete = True
        score = min(score, 99) if score else 0

    parts = []
    if setup_family:
        parts.append(setup_family)
    if setup_types:
        parts.extend(setup_types[:2])
    summary = "reviewed" if tagging_done and not parts else (", ".join(parts)[:60] if parts else "—")

    takeaway = ""
    if has_critique and nar.get("takeaways"):
        takeaway = str(nar["takeaways"][0])[:100]

    return {
        "complete": not incomplete,
        "tag_count": tag_count,
        "missing": missing,
        "score": score,
        "summary": summary,
        "auto_stub": auto_stub,
        "auto_tagged": bool(payload.get("auto_tagged")),
        "auto_tagged_pending": bool(payload.get("auto_tagged") and not payload.get("operator_confirmed")),
        "ai_critique": {
            "has_critique": has_critique,
            "stale": ai_stale,
            "summary": (nar.get("summary") or "")[:160],
            "takeaway": takeaway,
            "generated_at": critique.get("generated_at") if critique else crit_meta.get("generated_at"),
        },
    }


def tagging_queue(account=None, days=365, missing_category=None, min_pnl=None,
                  page=1, limit=50, include_complete=False, symbol=None):
    """Trades needing operator tagging, oldest first."""
    policy = _load_tagging_policy()
    limit = min(int(limit or policy.get("queue_page_size", 50)), 200)
    page = max(1, int(page or 1))
    offset = (page - 1) * limit

    params: list[Any] = [int(days)]
    acct = ""
    if account:
        acct = " AND tc.account = %s"
        params.append(account)
    min_pnl_sql = ""
    if min_pnl is not None:
        min_pnl_sql = " AND ABS(tc.pnl) >= %s"
        params.append(abs(float(min_pnl)))

    rows = _q(f"""
        SELECT tc.symbol, tc.account, tc.open_date::text, tc.close_date::text, tc.trade_type,
               tc.shares, tc.buy_price, tc.sell_price, tc.pnl, tc.pnl_pct, tc.hold_days,
               (tc.symbol || ':' || tc.account || ':' || tc.close_date::text) AS trade_key,
               eq.entry_time::text AS entry_time, eq.exit_time::text AS exit_time,
               r.id AS review_id, r.setup_family, r.setup_name, r.setup_types, r.market_regime,
               r.emotion_before, r.mistake_tags, r.strength_tags, r.lesson_learned,
               r.review_notes, r.payload, r.updated_at::text
        FROM trade_closed tc
        LEFT JOIN journal_trade_reviews r
          ON r.trade_key = (tc.symbol || ':' || tc.account || ':' || tc.close_date::text)
        LEFT JOIN LATERAL (
            SELECT entry_time, exit_time FROM trade_execution_quality
            WHERE UPPER(symbol) = UPPER(tc.symbol)
              AND entry_time::date = tc.close_date
              AND ABS(entry_price - tc.buy_price) < 0.08
            ORDER BY ABS(entry_price - tc.buy_price), exit_time DESC LIMIT 1
        ) eq ON true
        WHERE (tc.buy_price > 0 OR tc.pnl != 0)
          AND tc.close_date > now() - (%s || ' days')::interval {acct} {min_pnl_sql}
        ORDER BY tc.close_date ASC, tc.open_date ASC NULLS LAST, tc.symbol
    """, params)

    complete_keys: set[str] = set()
    all_keys: set[str] = set()
    by_key: dict[str, dict] = {}
    raw_row_count = len(rows)

    for row in rows:
        tk = row["trade_key"]
        all_keys.add(tk)
        rev = {k: row[k] for k in (
            "setup_family", "setup_name", "setup_types", "market_regime", "emotion_before",
            "mistake_tags", "strength_tags", "lesson_learned", "review_notes", "payload",
        )} if row.get("review_id") else None
        score = score_trade_tags(rev, policy)
        payload = _review_payload(rev) if rev else {}
        if score.get("complete"):
            complete_keys.add(tk)

        pnl = float(row.get("pnl") or 0)
        sh = float(row.get("shares") or 0)
        direction = "short" if (row.get("trade_type") or "").upper() == "SHORT" else "long"

        if tk in by_key:
            item = by_key[tk]
            item["lot_count"] = int(item.get("lot_count") or 1) + 1
            item["net_pnl"] = float(item.get("net_pnl") or 0) + pnl
            item["gross_pnl"] = float(item.get("gross_pnl") or 0) + pnl
            item["shares"] = float(item.get("shares") or 0) + sh
            continue

        by_key[tk] = {
            "trade_key": tk,
            "symbol": row["symbol"],
            "account": row["account"],
            "open_date": row["open_date"],
            "close_date": row["close_date"],
            "entry_time": row.get("entry_time"),
            "exit_time": row.get("exit_time"),
            "execution_date": row["close_date"],
            "direction": direction,
            "shares": sh,
            "buy_price": row.get("buy_price"),
            "sell_price": row.get("sell_price"),
            "gross_pnl": pnl,
            "net_pnl": pnl,
            "pnl_pct": row.get("pnl_pct"),
            "lot_count": 1,
            "tag_count": score["tag_count"],
            "tag_summary": score["summary"],
            "missing": score["missing"],
            "tagging_score": score["score"],
            "has_review": bool(row.get("review_id")),
            "auto_stub": score.get("auto_stub", False),
            "auto_tagged": score.get("auto_tagged", False),
            "auto_tagged_pending": score.get("auto_tagged_pending", False),
            "market_regime": (rev.get("market_regime") or "").strip() or None if rev else None,
            "emotion_before": (rev.get("emotion_before") or "").strip() or None if rev else None,
            "industry": (payload.get("industry") or "").strip() or None,
            "sector": (payload.get("sector") or "").strip() or None,
            "market_regime_entry": payload.get("market_regime_entry"),
            "market_regime_exit": payload.get("market_regime_exit"),
            "market_regime_display": payload.get("market_regime_display"),
            "_complete": score.get("complete", False),
        }

    duplicate_audit_items = [
        {
            "symbol": item["symbol"],
            "trade_key": tk,
            "lot_count": int(item.get("lot_count") or 1),
            "account": item.get("account"),
            "close_date": item.get("close_date"),
            "net_pnl": item.get("net_pnl"),
        }
        for tk, item in by_key.items()
        if int(item.get("lot_count") or 1) > 1
    ]
    duplicate_audit_items.sort(key=lambda x: (-x["lot_count"], x["symbol"]))

    queue = []
    for item in by_key.values():
        if item.pop("_complete", False):
            if not include_complete:
                continue
        if missing_category == "auto_tagged":
            if not item.get("auto_tagged_pending"):
                continue
        elif missing_category and missing_category not in (item.get("missing") or []):
            continue
        queue.append(item)

    sym_groups: dict[str, set[str]] = {}
    sym_lots: dict[str, int] = {}
    for item in queue:
        sym = item.get("symbol") or "?"
        sym_groups.setdefault(sym, set()).add(item["trade_key"])
        sym_lots[sym] = sym_lots.get(sym, 0) + int(item.get("lot_count") or 1)
    symbol_groups = [
        {
            "symbol": sym,
            "count": len(keys),
            "lot_count": sym_lots.get(sym, len(keys)),
            "trade_keys": sorted(keys),
        }
        for sym, keys in sorted(sym_groups.items(), key=lambda x: (-len(x[1]), x[0]))
    ]

    complete_n = len(complete_keys)
    total_in_range = len(all_keys)

    queue_total_all = len(queue)
    auto_tagged_pending_n = sum(1 for item in queue if item.get("auto_tagged_pending"))

    if symbol:
        sym_filter = symbol.upper().strip()
        queue = [q for q in queue if (q.get("symbol") or "").upper() == sym_filter]

    need_tagging = queue_total_all if not include_complete else total_in_range - complete_n
    page_rows = queue[offset:offset + limit]
    oldest = queue[0]["execution_date"] if queue else None
    health = round(complete_n / total_in_range * 100, 1) if total_in_range else 100.0
    active_group = next((g for g in symbol_groups if g["symbol"].upper() == (symbol or "").upper()), None)

    return {
        "ok": True,
        "items": page_rows,
        "page": page,
        "limit": limit,
        "total_queue": len(queue),
        "queue_total_all": queue_total_all,
        "total_in_range": total_in_range,
        "complete_in_range": complete_n,
        "queue_health_pct": health,
        "need_tagging": need_tagging,
        "auto_tagged_pending": auto_tagged_pending_n,
        "need_tagging_pct": round(queue_total_all / total_in_range * 100, 1) if total_in_range else 0,
        "oldest_trade_date": oldest,
        "symbol_groups": symbol_groups,
        "filter_symbol": symbol or None,
        "filter_symbol_count": active_group["count"] if active_group else None,
        "filter_symbol_trade_keys": active_group["trade_keys"] if active_group else [],
        "duplicate_audit": {
            "multi_lot_trades": len(duplicate_audit_items),
            "raw_rows": raw_row_count,
            "unique_trades": total_in_range,
            "hidden_duplicate_rows": max(0, raw_row_count - total_in_range),
            "items": duplicate_audit_items[:30],
        },
        "policy": {k: policy.get(k) for k in ("min_total_tags", "required_categories", "high_priority_categories")},
    }


def ai_critique(trade_key: str, force: bool = False) -> dict:
    """Generate + persist AI trade critique in journal_trade_reviews.payload.ai_critique."""
    import journal_ai_critique as jac
    return jac.ai_critique_for_trade(trade_key, force=force, apply=True)


def ai_critique_search(q: str = "", setup_family: str = "", days: int = 365, limit: int = 50) -> dict:
    import journal_ai_critique as jac
    return jac.search_critiques(q=q, setup_family=setup_family, days=days, limit=limit)


def ai_critique_insights(days: int = 30) -> dict:
    import journal_ai_critique as jac
    return jac.coaching_insights(days=days)


def ai_critique_setups(days: int = 365, limit: int = 15) -> dict:
    import journal_ai_critique as jac
    return jac.aggregate_by_setup(days=days, limit=limit)


def ai_critique_meta(trade_key: str) -> dict:
    """Lightweight persisted critique summary for review/detail views."""
    import journal_ai_critique as jac
    jac.ensure_critique_schema()
    stored = jac.load_stored_critique(trade_key)
    if not stored:
        return {"has_critique": False, "trade_key": trade_key}
    meta = stored.get("_meta") or {}
    nar = stored.get("narrative") or {}
    return {
        "has_critique": True,
        "trade_key": trade_key,
        "generated_at": stored.get("generated_at") or meta.get("generated_at"),
        "stale": bool(meta.get("stale")),
        "status": meta.get("status", "ok"),
        "history_count": stored.get("_history_count", 0),
        "tag_fingerprint": meta.get("tag_fingerprint"),
        "summary": (nar.get("summary") or "")[:300],
        "takeaways": nar.get("takeaways") or [],
        "improvements": nar.get("improvements") or [],
    }


def mark_ai_critique_stale(trade_key: str) -> bool:
    import journal_ai_critique as jac
    return jac.mark_stale_on_tag_change(trade_key)


def ai_critique_summaries(account: str | None = None, days: int = 365, limit: int = 500) -> dict:
    import journal_ai_critique as jac
    return jac.critique_summaries_bulk(account=account, days=days, limit=limit)


def ai_critique_batch(
    account: str | None = None,
    date_from: str | None = None,
    days: int = 365,
    limit: int = 200,
    force: bool = False,
    use_llm: bool = False,
    skip_existing: bool = True,
) -> dict:
    import journal_ai_critique as jac
    return jac.batch_generate_critiques(
        account=account, date_from=date_from, days=days, limit=limit,
        force=force, use_llm=use_llm, skip_existing=skip_existing,
    )


def tagging_queue_skip(trade_key: str, reason: str = ""):
    """Mark trade as operator-reviewed without full tags."""
    existing = _q("SELECT id, payload FROM journal_trade_reviews WHERE trade_key = %s", [trade_key], fetch="one")
    payload = _review_payload(existing) if existing else {}
    payload["operator_reviewed_skip"] = True
    payload["skip_reason"] = (reason or "no tags needed")[:200]
    if existing:
        _q("UPDATE journal_trade_reviews SET payload = %s::jsonb, coach_notes = %s, updated_at = NOW() WHERE trade_key = %s",
           [json.dumps(payload), f"[tagging_skip] {reason}"[:300], trade_key], fetch="none")
    else:
        parts = trade_key.split(":")
        sym, acct, cd = parts[0], parts[1] if len(parts) > 2 else "", parts[-1]
        _q("""
            INSERT INTO journal_trade_reviews (trade_key, symbol, account, closed_date, payload, coach_notes, lesson_learned)
            VALUES (%s, %s, %s, %s::date, %s::jsonb, %s, %s)
        """, [trade_key, sym, acct, cd, json.dumps(payload), f"[tagging_skip] {reason}"[:300],
              "Operator marked reviewed — no tags needed."], fetch="none")
    return {"ok": True, "trade_key": trade_key}


REGIME_LABEL_MAP = {
    "risk_on_trend": "Risk-On",
    "risk_off": "Risk-Off",
    "choppy_range": "Choppy",
    "high_volatility": "High Volatility",
    "low_volatility_grind": "Low Volume",
    "broad_momentum": "Trending",
    "unknown": "Ranging",
}


def _map_regime_label(raw: str | None) -> str:
    if not raw:
        return "Ranging"
    key = str(raw).strip().lower().replace(" ", "_").replace("-", "_")
    if key in REGIME_LABEL_MAP:
        return REGIME_LABEL_MAP[key]
    titled = str(raw).replace("_", " ").strip()
    if not titled:
        return "Ranging"
    return " ".join(w[:1].upper() + w[1:].lower() for w in titled.split())[:80]


def _lookup_regime_for_date(trade_date: str | None) -> dict:
    """Best-effort market regime for a trade entry/exit calendar date."""
    if not trade_date or str(trade_date).upper() == "UNKNOWN":
        return {"regime": _default_market_regime(), "source": "default", "as_of": None}
    d = str(trade_date)[:10]
    row = _q(
        "SELECT regime_label, generated_at::text FROM market_regime_snapshots "
        "WHERE generated_at::date <= %s::date ORDER BY generated_at DESC LIMIT 1",
        [d], fetch="one",
    )
    if row and row.get("regime_label"):
        return {
            "regime": _map_regime_label(row["regime_label"]),
            "source": "market_regime_snapshots",
            "as_of": str(row.get("generated_at") or "")[:10],
        }
    try:
        row = _q(
            "SELECT market_regime, created_at::text FROM trade_ai_runs "
            "WHERE market_regime IS NOT NULL AND created_at::date <= %s::date "
            "ORDER BY created_at DESC LIMIT 1",
            [d], fetch="one",
        )
        if row and row.get("market_regime"):
            return {
                "regime": _map_regime_label(str(row["market_regime"])),
                "source": "trade_ai_runs",
                "as_of": str(row.get("created_at") or "")[:10],
            }
    except Exception:
        pass
    return {"regime": "Ranging", "source": "default_fallback", "as_of": d}


def _regime_fields_for_trade(tc_row: dict | None, item: dict | None = None) -> dict:
    src = tc_row or item or {}
    open_d = src.get("open_date") or src.get("entry_date")
    close_d = src.get("close_date") or src.get("execution_date")
    entry = _lookup_regime_for_date(open_d or close_d)
    exit_ = _lookup_regime_for_date(close_d or open_d)
    display = entry["regime"]
    if entry["regime"] != exit_["regime"]:
        display = f"{entry['regime']} → {exit_['regime']}"
    return {
        "market_regime": entry["regime"],
        "market_regime_entry": entry["regime"],
        "market_regime_exit": exit_["regime"],
        "market_regime_display": display,
        "market_regime_entry_source": entry["source"],
        "market_regime_exit_source": exit_["source"],
        "market_regime_entry_as_of": entry.get("as_of"),
        "market_regime_exit_as_of": exit_.get("as_of"),
    }


def _lookup_industry(symbol: str) -> dict:
    """Resolve industry/sector label from symbol_profiles (Finviz-backed)."""
    sym = (symbol or "").upper().strip()
    if not sym:
        return {"industry": "", "sector": "", "source": "none"}
    row = _q(
        "SELECT industry, sector FROM symbol_profiles WHERE UPPER(symbol) = %s LIMIT 1",
        [sym], fetch="one",
    )
    if row:
        ind = (row.get("industry") or "").strip()
        sec = (row.get("sector") or "").strip()
        label = ind or sec
        if label:
            return {"industry": label, "sector": sec, "source": "symbol_profiles"}
    return {"industry": "", "sector": "", "source": "none"}


def _default_market_regime() -> str:
    try:
        row = _q(
            "SELECT market_regime FROM trade_ai_runs WHERE market_regime IS NOT NULL "
            "ORDER BY created_at DESC LIMIT 1",
            fetch="one",
        )
        if row and row.get("market_regime"):
            return str(row["market_regime"]).replace("_", " ").title()[:80]
    except Exception:
        pass
    return "Ranging"


def _ensure_review_row(trade_key: str, trade_row: dict | None = None) -> dict | None:
    """Create AI-suggested review stub when missing."""
    existing = _q("SELECT * FROM journal_trade_reviews WHERE trade_key = %s", [trade_key], fetch="one")
    if existing:
        return existing
    parts = trade_key.split(":")
    sym, acct, cd = parts[0], parts[1] if len(parts) > 2 else "", parts[-1]
    item = trade_row or {"symbol": sym, "account": acct, "close_date": cd, "trade_key": trade_key}
    try:
        from api_v2 import _suggest_setup, _journal_timeframe_hint
        setup, family, rationale, tags = _suggest_setup(item)
        timeframe = _journal_timeframe_hint(item)
        direction = "short" if (item.get("trade_type") or "").upper() == "SHORT" else "long"
        rid = _q("""
            INSERT INTO journal_trade_reviews
              (trade_key, symbol, account, closed_date, setup_name, setup_family, timeframe,
               direction, setup_types, execution_quality_score, sizing_quality_score,
               followed_plan, well_executed, lesson_learned, review_notes, created_at)
            VALUES (%s,%s,%s,%s::date,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,NOW())
            ON CONFLICT (trade_key) DO NOTHING
            RETURNING id
        """, [
            trade_key, sym, acct, cd, setup, family, timeframe, direction, tags,
            3, 3, False, False,
            "Auto-classified. Please review and update.",
            f"AI suggested: {setup} — {rationale}",
        ], fetch="one")
        if rid:
            return _q("SELECT * FROM journal_trade_reviews WHERE trade_key = %s", [trade_key], fetch="one")
    except Exception:
        _q("""
            INSERT INTO journal_trade_reviews (trade_key, symbol, account, closed_date, lesson_learned)
            VALUES (%s,%s,%s,%s::date,%s)
            ON CONFLICT (trade_key) DO NOTHING
        """, [trade_key, sym, acct, cd, "Auto-tagged — please verify."], fetch="none")
    return _q("SELECT * FROM journal_trade_reviews WHERE trade_key = %s", [trade_key], fetch="one")


def _patch_review(trade_key: str, field_updates: dict, payload_patch: dict | None = None) -> bool:
    existing = _q("SELECT * FROM journal_trade_reviews WHERE trade_key = %s", [trade_key], fetch="one")
    if not existing:
        return False
    payload = _review_payload(existing)
    if payload_patch:
        payload.update(payload_patch)
    sets, vals = ["payload = %s::jsonb", "updated_at = NOW()"], [json.dumps(payload)]
    for k, v in field_updates.items():
        if v is not None and v != "":
            sets.append(f"{k} = %s")
            vals.append(v)
    vals.append(trade_key)
    _q(f"UPDATE journal_trade_reviews SET {', '.join(sets)} WHERE trade_key = %s", vals, fetch="none")
    rev = _q("SELECT * FROM journal_trade_reviews WHERE trade_key = %s", [trade_key], fetch="one")
    if rev:
        p = _review_payload(rev)
        if score_trade_tags(rev).get("complete") and not (p.get("auto_tagged") and not p.get("operator_confirmed")):
            p["tagging_complete"] = True
            _q("UPDATE journal_trade_reviews SET payload = %s::jsonb WHERE trade_key = %s",
               [json.dumps(p), trade_key], fetch="none")
        elif p.get("tagging_complete") and p.get("auto_tagged") and not p.get("operator_confirmed"):
            p["tagging_complete"] = False
            _q("UPDATE journal_trade_reviews SET payload = %s::jsonb WHERE trade_key = %s",
               [json.dumps(p), trade_key], fetch="none")
    return True


def tagging_queue_bulk_tag(trade_keys: list, tags: dict):
    """Apply shared tags to multiple trades."""
    applied = 0
    for tk in trade_keys[:200]:
        existing = _q("SELECT * FROM journal_trade_reviews WHERE trade_key = %s", [tk], fetch="one")
        parts = tk.split(":")
        sym, acct, cd = parts[0], parts[1] if len(parts) > 2 else "", parts[-1]
        if not existing:
            existing = _ensure_review_row(tk)
        payload = _review_payload(existing) if existing else {}
        industry = tags.get("industry")
        if industry:
            payload["industry"] = industry
            payload["sector"] = tags.get("sector") or payload.get("sector")
        for pk in ("trade_plan", "trade_rating", "what_went_well", "what_to_improve"):
            if tags.get(pk) is not None and tags.get(pk) != "":
                payload[pk] = tags[pk]
        fields = {
            "setup_family": tags.get("setup_family"),
            "setup_types": tags.get("setup_types"),
            "market_regime": tags.get("market_regime"),
            "emotion_before": tags.get("emotion_before"),
            "mistake_tags": tags.get("mistake_tags"),
            "strength_tags": tags.get("strength_tags"),
            "planned_r": tags.get("planned_r"),
            "realized_r": tags.get("realized_r"),
            "lesson_learned": tags.get("lesson_learned"),
            "followed_plan": tags.get("followed_plan"),
        }
        if industry:
            fields["catalyst_type"] = industry
        has_tag = any(
            v is not None and v != "" and v != []
            for v in list(fields.values()) + [industry, tags.get("trade_plan")]
        )
        if has_tag:
            payload["operator_reviewed"] = True
            payload["operator_confirmed"] = True
            payload["bulk_tagged_at"] = datetime.utcnow().isoformat() + "Z"
        patch_fields = {k: v for k, v in fields.items() if v is not None}
        if existing:
            _patch_review(tk, patch_fields, payload)
        else:
            payload["tagging_complete"] = False
            _q("""
                INSERT INTO journal_trade_reviews
                  (trade_key, symbol, account, closed_date, setup_family, setup_types, market_regime,
                   emotion_before, mistake_tags, strength_tags, catalyst_type, planned_r, realized_r,
                   followed_plan, payload, lesson_learned)
                VALUES (%s,%s,%s,%s::date,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s)
            """, [tk, sym, acct, cd,
                  fields.get("setup_family"), fields.get("setup_types"), fields.get("market_regime"),
                  fields.get("emotion_before"), fields.get("mistake_tags"), fields.get("strength_tags"),
                  industry, fields.get("planned_r"), fields.get("realized_r"), fields.get("followed_plan"),
                  json.dumps(payload), fields.get("lesson_learned") or "Bulk tagged from Tagging Queue."], fetch="none")
        applied += 1
    return {"ok": True, "applied": applied}


def _enrich_one_trade_review(
    tk: str,
    sym: str,
    tc_row: dict | None,
    item: dict | None,
    rev: dict,
    *,
    psych_default: str = "Calm",
    refresh_regime: bool = True,
    auto_confirm: bool = True,
) -> dict[str, Any] | None:
    """Apply auto-tags to one review row; returns patch summary or None if skipped."""
    payload = _review_payload(rev)
    updates: dict[str, Any] = {}
    src = tc_row or item or {}

    if not (rev.get("setup_family") or "").strip():
        fam = ""
        if item and item.get("tag_summary"):
            fam = (item.get("tag_summary") or "").split(",")[0].strip()
        if not fam or fam == "—":
            try:
                from api_v2 import _suggest_setup
                setup, family, _rat, tags = _suggest_setup(src)
                fam = family or setup or ""
                if tags and not (rev.get("setup_types") or []):
                    updates["setup_types"] = tags if isinstance(tags, list) else [tags]
            except Exception:
                fam = fam if fam and fam != "—" else ""
        if fam and fam != "—":
            updates["setup_family"] = fam

    regime_fields = _regime_fields_for_trade(tc_row, item)
    cur_regime = (rev.get("market_regime") or "").strip()
    stale_regime = (
        not cur_regime
        or cur_regime == "Ranging"
        or payload.get("auto_tag_defaults", {}).get("market_regime") == "Ranging"
        or payload.get("market_regime_entry_source") in (None, "default", "default_fallback")
    )
    if refresh_regime or stale_regime or not cur_regime:
        updates["market_regime"] = regime_fields["market_regime"]
        payload.update({
            "market_regime_entry": regime_fields["market_regime_entry"],
            "market_regime_exit": regime_fields["market_regime_exit"],
            "market_regime_display": regime_fields["market_regime_display"],
            "market_regime_entry_source": regime_fields["market_regime_entry_source"],
            "market_regime_exit_source": regime_fields["market_regime_exit_source"],
            "market_regime_entry_as_of": regime_fields.get("market_regime_entry_as_of"),
            "market_regime_exit_as_of": regime_fields.get("market_regime_exit_as_of"),
        })

    if not (rev.get("emotion_before") or "").strip():
        updates["emotion_before"] = psych_default
    else:
        eb = str(rev.get("emotion_before") or "").strip()
        if eb.lower() != eb:
            updates["emotion_before"] = eb[0].upper() + eb[1:].lower()

    setup_types = rev.get("setup_types") or []
    if isinstance(setup_types, str):
        setup_types = [setup_types] if setup_types else []
    if not setup_types and not (rev.get("setup_name") or "").strip():
        fam = (updates.get("setup_family") or rev.get("setup_family") or "").strip()
        if fam:
            updates["setup_types"] = [fam]

    ind_info = _lookup_industry(sym)
    if (not (payload.get("industry") or "").strip() or payload.get("industry_source") == "none") and ind_info.get("industry"):
        payload["industry"] = ind_info["industry"]
        payload["sector"] = ind_info.get("sector") or ""
        payload["industry_source"] = ind_info.get("source")
        updates["catalyst_type"] = ind_info["industry"]

    payload["auto_tagged"] = True
    payload["auto_tagged_at"] = datetime.utcnow().isoformat() + "Z"
    payload["auto_tag_defaults"] = {
        "market_regime": updates.get("market_regime") or cur_regime or regime_fields["market_regime"],
        "emotion_before": updates.get("emotion_before") or (rev.get("emotion_before") or "").strip() or psych_default,
    }

    confirmed = False
    if auto_confirm:
        has_strategy = bool((updates.get("setup_family") or rev.get("setup_family") or "").strip())
        has_setup = bool(updates.get("setup_types") or setup_types or (rev.get("setup_name") or "").strip())
        has_regime = bool((updates.get("market_regime") or cur_regime or "").strip())
        has_psych = bool((updates.get("emotion_before") or rev.get("emotion_before") or "").strip())
        ind_ok = bool((payload.get("industry") or "").strip()) or not _lookup_industry(sym).get("industry")
        if has_strategy and has_setup and has_regime and has_psych and ind_ok:
            payload["operator_confirmed"] = True
            payload["operator_reviewed"] = True
            payload["tagging_complete"] = True
            payload["auto_confirmed_at"] = datetime.utcnow().isoformat() + "Z"
            confirmed = True

    if _patch_review(tk, updates, payload):
        return {"trade_key": tk, "updates": list(updates.keys()), "regime": regime_fields, "confirmed": confirmed}
    return None


def tagging_queue_auto_tag(days=365, account=None, trade_keys: list | None = None, defaults: dict | None = None):
    """Fill missing tags on incomplete reviews (industry, entry/exit regime, psychology, setup)."""
    defaults = defaults or {}
    psych_default = defaults.get("emotion_before") or "Calm"
    auto_confirm = defaults.get("auto_confirm", True)
    refresh_regime = defaults.get("refresh_regime", True)
    include_complete = bool(defaults.get("include_complete"))

    q = tagging_queue(days=days, account=account, limit=10000, include_complete=include_complete)
    items = q.get("items") or []
    if not items and include_complete:
        q = tagging_queue(days=days, account=account, limit=10000, include_complete=True)
        items = q.get("items") or []

    if trade_keys:
        keyset = set(trade_keys)
        items = [i for i in items if i.get("trade_key") in keyset]
    elif not include_complete:
        # Also scan trades with no review row yet (0% ready in queue UI)
        params: list[Any] = [int(days)]
        acct_sql = ""
        if account:
            acct_sql = " AND tc.account = %s"
            params.append(account)
        extra = _q(f"""
            SELECT tc.symbol, tc.account, tc.open_date::text, tc.close_date::text,
                   (tc.symbol || ':' || tc.account || ':' || tc.close_date::text) AS trade_key
            FROM trade_closed tc
            LEFT JOIN journal_trade_reviews r
              ON r.trade_key = (tc.symbol || ':' || tc.account || ':' || tc.close_date::text)
            WHERE (tc.buy_price > 0 OR tc.pnl != 0)
              AND tc.close_date > now() - (%s || ' days')::interval {acct_sql}
              AND r.id IS NULL
        """, params)
        seen = {i["trade_key"] for i in items}
        for row in extra:
            if row["trade_key"] not in seen:
                items.append({
                    "trade_key": row["trade_key"],
                    "symbol": row["symbol"],
                    "account": row["account"],
                    "open_date": row["open_date"],
                    "close_date": row["close_date"],
                    "tag_summary": "—",
                })

    applied = 0
    skipped = 0
    confirmed = 0
    for item in items:
        tk = item["trade_key"]
        sym = item.get("symbol") or tk.split(":")[0]
        parts = tk.split(":")
        tc_row = _q(
            "SELECT *, (symbol || ':' || account || ':' || close_date::text) AS trade_key "
            "FROM trade_closed WHERE symbol=%s AND account=%s AND close_date=%s::date LIMIT 1",
            [parts[0], parts[1] if len(parts) > 2 else "", parts[-1]],
            fetch="one",
        )
        rev = _ensure_review_row(tk, tc_row or item)
        if not rev:
            skipped += 1
            continue
        result = _enrich_one_trade_review(
            tk, sym, tc_row, item, rev,
            psych_default=psych_default,
            refresh_regime=refresh_regime,
            auto_confirm=auto_confirm,
        )
        if result:
            applied += 1
            if result.get("confirmed"):
                confirmed += 1
        else:
            skipped += 1

    return {
        "ok": True,
        "applied": applied,
        "skipped": skipped,
        "auto_confirmed": confirmed,
        "defaults_used": {"emotion_before": psych_default, "auto_confirm": auto_confirm},
    }


def tagging_queue_auto_enrich(days=365, account=None, trade_keys: list | None = None, defaults: dict | None = None):
    """Auto-tag + industry backfill + optional auto-confirm in one operator pass."""
    defaults = {**(defaults or {}), "auto_confirm": defaults.get("auto_confirm", True) if defaults else True,
                "refresh_regime": True, "include_complete": True}
    tag = tagging_queue_auto_tag(days=days, account=account, trade_keys=trade_keys, defaults=defaults)
    ind = tagging_queue_backfill_industry(
        days=days, account=account, trade_keys=trade_keys, overwrite=False,
    )
    # Second pass picks up industry from backfill + confirms
    tag2 = tagging_queue_auto_tag(
        days=days, account=account, trade_keys=trade_keys,
        defaults={**defaults, "include_complete": True},
    )
    return {
        "ok": True,
        "auto_tag": tag,
        "industry_backfill": ind,
        "auto_tag_pass2": tag2,
        "applied": (tag.get("applied") or 0) + (tag2.get("applied") or 0),
        "auto_confirmed": (tag.get("auto_confirmed") or 0) + (tag2.get("auto_confirmed") or 0),
        "industry_applied": ind.get("applied") or 0,
    }


def tagging_queue_backfill_industry(
    days=365, account=None, trade_keys: list | None = None,
    overwrite: bool = False, industry_override: str | None = None,
):
    """Backfill payload.industry + catalyst_type from symbol_profiles (or manual override)."""
    params: list[Any] = [int(days)]
    acct_sql = ""
    if account:
        acct_sql = " AND tc.account = %s"
        params.append(account)
    rows = _q(f"""
        SELECT tc.symbol, (tc.symbol || ':' || tc.account || ':' || tc.close_date::text) AS trade_key,
               r.id AS review_id, r.payload, r.catalyst_type
        FROM trade_closed tc
        LEFT JOIN journal_trade_reviews r
          ON r.trade_key = (tc.symbol || ':' || tc.account || ':' || tc.close_date::text)
        WHERE (tc.buy_price > 0 OR tc.pnl != 0)
          AND tc.close_date > now() - (%s || ' days')::interval {acct_sql}
    """, params)
    if trade_keys:
        keyset = set(trade_keys)
        rows = [r for r in rows if r.get("trade_key") in keyset]

    applied = 0
    missing_profile = 0
    for row in rows:
        tk = row["trade_key"]
        sym = row.get("symbol") or ""
        payload = _review_payload({"payload": row.get("payload")}) if row.get("review_id") else {}
        has_ind = bool((payload.get("industry") or "").strip() or (row.get("catalyst_type") or "").strip())
        if has_ind and not overwrite and not industry_override:
            continue
        if industry_override:
            info = {"industry": industry_override.strip(), "sector": "", "source": "manual_override"}
        else:
            info = _lookup_industry(sym)
            if not info.get("industry"):
                missing_profile += 1
                continue
        if not row.get("review_id"):
            _ensure_review_row(tk, {"symbol": sym, "trade_key": tk})
        payload["industry"] = info["industry"]
        payload["sector"] = info.get("sector") or ""
        payload["industry_source"] = info.get("source")
        payload["industry_backfilled_at"] = datetime.utcnow().isoformat() + "Z"
        _patch_review(tk, {"catalyst_type": info["industry"]}, payload)
        applied += 1

    return {"ok": True, "applied": applied, "missing_profile": missing_profile, "scanned": len(rows)}


def tagging_queue_confirm_auto_tagged(days=365, account=None, trade_keys: list | None = None):
    """Mark auto-tagged trades as operator-confirmed (clears review queue)."""
    q = tagging_queue(days=days, account=account, limit=10000, include_complete=False)
    items = [i for i in (q.get("items") or []) if i.get("auto_tagged_pending")]
    if trade_keys:
        keyset = set(trade_keys)
        items = [i for i in items if i.get("trade_key") in keyset]
    applied = 0
    for item in items:
        tk = item["trade_key"]
        existing = _q("SELECT payload FROM journal_trade_reviews WHERE trade_key = %s", [tk], fetch="one")
        if not existing:
            continue
        payload = _review_payload(existing)
        payload["operator_confirmed"] = True
        payload["operator_reviewed"] = True
        payload["operator_confirmed_at"] = datetime.utcnow().isoformat() + "Z"
        _patch_review(tk, {}, payload)
        applied += 1
    return {"ok": True, "applied": applied}


def reporting_audit(days=365):
    """Self-audit: TradeInView report coverage vs spec + tagging impact."""
    policy = _load_tagging_policy()
    q = tagging_queue(days=days, limit=10000, include_complete=False)
    total = q.get("total_in_range") or 0
    health = q.get("queue_health_pct") or 0
    need = q.get("need_tagging") or 0
    auto_pending = q.get("auto_tagged_pending") or 0

    def _status(impl: str, degraded: str = "") -> str:
        if degraded and need > total * 0.2:
            return "degraded"
        return impl

    reports = [
        {"id": "trade_log", "name": "Trade Log + KPIs", "status": "implemented", "tab": "Trades"},
        {"id": "equity_curve", "name": "Equity curve & daily P&L", "status": "implemented", "tab": "Trades"},
        {"id": "zella_score", "name": "Zella composite score", "status": _status("implemented", "tagging"), "tab": "Analytics", "note": "Discipline/psychology need tags"},
        {"id": "monte_carlo", "name": "Monte Carlo bootstrap", "status": "implemented", "tab": "Analytics"},
        {"id": "exit_intel", "name": "MAE/MFE + exit intelligence", "status": "implemented", "tab": "Exit Intel"},
        {"id": "behavioral", "name": "Behavioral / tilt / mistakes $", "status": _status("implemented", "tagging"), "tab": "Behavioral"},
        {"id": "pivot_grid", "name": "Pivot grid cross-tabs", "status": _status("partial", "tagging"), "tab": "Advanced", "note": "Needs setup_family × market_regime tags"},
        {"id": "session_recap", "name": "Session recap", "status": "implemented", "tab": "Session"},
        {"id": "options_summary", "name": "Options multi-leg summary", "status": "partial", "tab": "Import", "note": "Limited option trade history"},
        {"id": "compare_replay", "name": "Win/loss compare replay", "status": "implemented", "tab": "Trades"},
        {"id": "tagging_queue", "name": "Tagging Queue", "status": "implemented", "tab": "Tagging Queue"},
        {"id": "calendar_heatmap", "name": "Calendar heatmap", "status": "partial", "tab": "Trades", "note": "Daily P&L bars, not full calendar"},
        {"id": "tick_replay", "name": "Tick-by-tick replay", "status": "missing", "tab": "—"},
        {"id": "voice_attachments", "name": "Voice memo attachments", "status": "missing", "tab": "—"},
        {"id": "per_leg_greeks", "name": "Per-leg greeks P&L attribution", "status": "missing", "tab": "Import"},
        {"id": "prop_drawdown", "name": "Prop firm drawdown tracking", "status": "missing", "tab": "—"},
    ]
    impl = sum(1 for r in reports if r["status"] == "implemented")
    partial = sum(1 for r in reports if r["status"] in ("partial", "degraded"))
    missing = sum(1 for r in reports if r["status"] == "missing")

    recs = []
    if need > 0:
        recs.append(f"Clear {need} trades in Tagging Queue ({100 - health:.0f}% incomplete) — unlocks pivot, behavioral, Zella.")
        if auto_pending:
            recs.append(f"Run Auto-enrich or confirm {auto_pending} auto-tagged trades still awaiting review.")
    elif health >= 99:
        recs.append("Tagging queue clear — reports should reflect regime + psychology on all trades.")
    if partial > 0 and need > 0:
        recs.append("Use Auto-enrich to backfill entry/exit regime + industry; bulk-tag same-symbol legs if needed.")

    return {
        "ok": True,
        "summary": {
            "implemented": impl,
            "partial_or_degraded": partial,
            "missing": missing,
            "coverage_pct": round(impl / len(reports) * 100, 1),
            "tagging_health_pct": health,
            "trades_need_tagging": need,
            "auto_tagged_pending": auto_pending,
            "trades_in_range": total,
        },
        "reports": reports,
        "recommendations": recs,
        "vs_tradezella": "On par for MAE/MFE, tagging, multi-account; ahead on AI agents + portfolio integration.",
        "vs_tradesviz": "Pivot/Monte Carlo partial; tagging completeness is primary gap.",
    }


def manual_entry_create(body: dict):
    cols = ["symbol", "account", "open_date", "close_date", "trade_type", "shares",
            "buy_price", "sell_price", "pnl", "pnl_pct", "notes", "template_id"]
    vals = [body.get(c) for c in cols]
    row = _q(f"""
        INSERT INTO journal_manual_entries ({','.join(cols)})
        VALUES ({','.join(['%s'] * len(cols))}) RETURNING id
    """, vals, fetch="one")
    return int(row["id"]) if row else None


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--exit", action="store_true")
    ap.add_argument("--zella", action="store_true")
    ap.add_argument("--behavioral", action="store_true")
    ap.add_argument("--auto-enrich", action="store_true", help="Auto-tag + industry backfill + confirm")
    ap.add_argument("--auto-tag", action="store_true", help="Auto-tag queue trades only")
    ap.add_argument("--backfill-industry", action="store_true", help="Industry backfill from symbol_profiles")
    ap.add_argument("--account")
    ap.add_argument("--days", type=int, default=365)
    args = ap.parse_args()
    if args.exit:
        print(json.dumps(exit_intelligence(args.account, args.days), indent=2, default=str))
    if args.zella:
        print(json.dumps(zella_score(args.account, args.days), indent=2))
    if args.behavioral:
        print(json.dumps(behavioral_analytics(args.account, args.days), indent=2, default=str))
    if args.auto_enrich:
        print(json.dumps(tagging_queue_auto_enrich(args.days, args.account), indent=2, default=str))
    if args.auto_tag:
        print(json.dumps(tagging_queue_auto_tag(args.days, args.account), indent=2, default=str))
    if args.backfill_industry:
        print(json.dumps(tagging_queue_backfill_industry(args.days, args.account), indent=2, default=str))