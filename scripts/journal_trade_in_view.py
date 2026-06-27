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
               (tc.symbol || ':' || tc.account || ':' || tc.close_date::text) AS trade_key
        FROM trade_closed tc
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


def options_journal_summary(account=None, days=365):
    params: list[Any] = [int(days)]
    acct = ""
    if account:
        acct = " AND account = %s"
        params.append(account)
    rows = _q(f"""
        SELECT symbol, trade_type, pnl, close_date::text
        FROM trade_closed
        WHERE close_date > now() - (%s || ' days')::interval {acct}
          AND (trade_type ILIKE '%%option%%' OR symbol ~ '[0-9]{{6}}[CP][0-9]')
        ORDER BY close_date DESC LIMIT 200
    """, params)
    return {"ok": True, "options_trades": len(rows), "trades": rows, **_agg(rows)}


def export_csv(account=None, date_from=None, date_to=None):
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
    ap.add_argument("--account")
    ap.add_argument("--days", type=int, default=365)
    args = ap.parse_args()
    if args.exit:
        print(json.dumps(exit_intelligence(args.account, args.days), indent=2, default=str))
    if args.zella:
        print(json.dumps(zella_score(args.account, args.days), indent=2))
    if args.behavioral:
        print(json.dumps(behavioral_analytics(args.account, args.days), indent=2, default=str))