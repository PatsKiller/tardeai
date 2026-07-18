#!/usr/bin/env python3
"""sector_momentum_engine.py — Defense Desk v1 WS-A: detect the CHANGE, not the level.

Nightly over the 11 sector ETFs vs SPY (ticker_prices, 5y depth — no warm-up):
  RS(w)   = sector w-day return − SPY w-day return   (w = 5/20/60)
  slope   = RS20 today − RS20 slope_lookback_days ago
  breadth = % of sector screener-membership names above their own 20DMA (fail-soft)
  state   = LEADING (RS20>0, slope>=0) · WEAKENING (RS20>0, slope<0)
          · LAGGING (RS20<0, slope<0) · IMPROVING (RS20<0, slope>=0)
  + Hermes sector pulse (mean composite + 5d delta) and news pressure (guarded negative
    catalysts, 5d) — intelligence CONFIRMS and colors; price/RS alone triggers.

Transition alerts fire ONLY on state changes held debounce_days consecutive closes,
capped max_alert_lines_per_day, severity scaled by YOUR book weight. Advisory only.

Usage: sector_momentum_engine.py [--date YYYY-MM-DD] [--backfill N] [--dry-run]
       --backfill runs the state machine over the last N sessions WITHOUT alerts
       (feeds the would-have-fired fold — hypothetical, labeled, never a backtest claim).
"""
import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

CFG = json.loads((ROOT / "config" / "sector_momentum.json").read_text())
STATES = ("LEADING", "WEAKENING", "LAGGING", "IMPROVING")


def _closes(cur, symbols, days=90):
    cur.execute(
        """SELECT symbol, price_date, close_price FROM ticker_prices
           WHERE symbol = ANY(%s) AND price_date > CURRENT_DATE - %s
           ORDER BY symbol, price_date""", (list(symbols), days + 40))
    out = {}
    for sym, d, px in cur.fetchall():
        out.setdefault(sym, []).append((d, float(px)))
    return out


def _ret(series, idx, w):
    """w-day return ending at index idx (series of (date, px))."""
    if idx - w < 0 or idx >= len(series):
        return None
    a, b = series[idx - w][1], series[idx][1]
    return (b - a) / a * 100 if a else None


def classify(rs20, slope):
    if rs20 is None or slope is None:
        return None
    if rs20 >= 0:
        return "LEADING" if slope >= 0 else "WEAKENING"
    return "IMPROVING" if slope >= 0 else "LAGGING"


def compute_states(cur, as_of_idx_offset=0):
    """One day's full sector table. offset 0 = latest close, 1 = prior close, ...
    Series are DATE-ALIGNED with SPY (held ETFs get extra repricer rows; XLI/XLB had 112
    closes vs SPY's window and index math misaligned — intersect on common dates)."""
    syms = list(CFG["sectors"].keys()) + [CFG["benchmark"], CFG["tech_crosscheck"]]
    px = _closes(cur, syms, days=max(CFG["rs_windows"].values()) + CFG["slope_lookback_days"] + 30)
    spy_raw = px.get(CFG["benchmark"], [])
    spy_by_date = dict(spy_raw)
    rows = []
    for etf, name in CFG["sectors"].items():
        s_raw = px.get(etf, [])
        common = [(d, p) for d, p in s_raw if d in spy_by_date]
        # dedupe by date (repricer can write >1 row/day), keep last
        seen = {}
        for d, p in common:
            seen[d] = p
        s = sorted(seen.items())
        spy = [(d, spy_by_date[d]) for d, _ in s]
        need = CFG["rs_windows"]["long"] + CFG["slope_lookback_days"] + 1
        if len(s) < need:
            rows.append({"etf": etf, "sector": name, "state": None,
                         "note": f"warming up — {len(s)}/{need} aligned closes"})
            continue
        i = len(s) - 1 - as_of_idx_offset
        j = len(spy) - 1 - as_of_idx_offset
        rs = {}
        for k, w in CFG["rs_windows"].items():
            a, b = _ret(s, i, w), _ret(spy, j, w)
            rs[k] = round(a - b, 2) if a is not None and b is not None else None
        lb = CFG["slope_lookback_days"]
        rs20_then = None
        a, b = _ret(s, i - lb, CFG["rs_windows"]["mid"]), _ret(spy, j - lb, CFG["rs_windows"]["mid"])
        if a is not None and b is not None:
            rs20_then = a - b
        slope = round(rs["mid"] - rs20_then, 2) if rs["mid"] is not None and rs20_then is not None else None
        rows.append({"etf": etf, "sector": name, "as_of": str(s[i][0]),
                     "rs5": rs["short"], "rs20": rs["mid"], "rs60": rs["long"],
                     "slope": slope, "state": classify(rs["mid"], slope)})
    return rows


def _breadth(cur, etf_sector_name):
    """% of sector members above their own 20DMA — fail-soft when membership thin."""
    try:
        cur.execute(
            """SELECT DISTINCT m.symbol FROM screener_symbol_membership m
               JOIN trade_ai_scans t ON upper(t.symbol) = upper(m.symbol)
               WHERE t.sector = %s LIMIT 60""", (etf_sector_name,))
        members = [r[0] for r in cur.fetchall()]
        if len(members) < CFG["breadth_min_members"]:
            return None, len(members)
        cur.execute(
            """SELECT symbol,
                      (array_agg(close_price ORDER BY price_date DESC))[1] AS last,
                      avg(close_price) FILTER (WHERE price_date > CURRENT_DATE - 30) AS dma
               FROM ticker_prices WHERE symbol = ANY(%s)
                 AND price_date > CURRENT_DATE - 45
               GROUP BY symbol HAVING count(*) >= 15""", (members,))
        above = total = 0
        for _s, last, dma in cur.fetchall():
            if last is None or dma is None:
                continue
            total += 1
            if float(last) > float(dma):
                above += 1
        return (round(above / total * 100) if total >= CFG["breadth_min_members"] else None), total
    except Exception:
        try: cur.connection.rollback()
        except Exception: pass
        return None, 0


def _hermes_pulse(cur, sector_name):
    try:
        cur.execute(
            """SELECT avg(h.composite_score),
                      avg(h.composite_score) FILTER (WHERE h.scored_at > now() - interval '5 days')
                    - avg(h.composite_score) FILTER (WHERE h.scored_at <= now() - interval '5 days'
                                                       AND h.scored_at > now() - interval '10 days')
               FROM hermes_score_history h
               JOIN trade_ai_scans t ON upper(t.symbol) = upper(h.symbol)
               WHERE t.sector = %s AND h.scored_at > now() - interval '10 days'""", (sector_name,))
        r = cur.fetchone()
        if r and r[0] is not None:
            return round(float(r[0]), 1), (round(float(r[1]), 1) if r[1] is not None else None)
    except Exception:
        try: cur.connection.rollback()
        except Exception: pass
    return None, None


def _news_pressure(cur, sector_name):
    try:
        cur.execute(
            """SELECT count(*), min(n.title)
               FROM news_articles n JOIN trade_ai_scans t ON upper(t.symbol) = upper(n.symbol)
               WHERE t.sector = %s AND n.published_at > now() - make_interval(days => %s)
                 AND (lower(coalesce(n.sentiment,'')) IN ('negative','bearish')
                      OR n.sentiment_score < -0.2)""",
            (sector_name, int(CFG["news_pressure_days"])))
        r = cur.fetchone()
        return (int(r[0]) if r else 0), (r[1] if r and r[1] else None)
    except Exception:
        try: cur.connection.rollback()
        except Exception: pass
        return 0, None


def _book_weights():
    try:
        import api_v2
        bm = api_v2._portfolio_book_map() or {}
        tot = float(bm.get("total_value") or 0) or 1.0
        agg = {}
        for r in bm.get("rows", []):
            agg.setdefault(r["sector"], [0.0, 0.0])
            agg[r["sector"]][0] += float(r["value"] or 0)
        return {k: {"dollars": round(v[0]), "pct": round(v[0] / tot * 100, 1)} for k, v in agg.items()}
    except Exception:
        return {}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--backfill", type=int, default=0)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    from db_adapter import _get_conn
    conn = _get_conn()
    cur = conn.cursor()
    cur.execute("""CREATE TABLE IF NOT EXISTS sector_momentum_state (
        as_of date NOT NULL, etf text NOT NULL, sector text, state text,
        rs5 numeric, rs20 numeric, rs60 numeric, slope numeric, breadth_pct numeric,
        breadth_n int, hermes_pulse numeric, hermes_delta numeric,
        news_negatives int, top_negative text, book_pct numeric, book_dollars numeric,
        created_at timestamptz DEFAULT now(), PRIMARY KEY (as_of, etf))""")
    conn.commit()

    if args.backfill:
        # hypothetical would-have-fired ledger (states only, NO alerts, labeled by consumers)
        fired = []
        prev = {}
        for off in range(args.backfill, -1, -1):
            for row in compute_states(cur, as_of_idx_offset=off):
                if not row.get("state"):
                    continue
                key = row["etf"]
                if prev.get(key) and prev[key] != row["state"]:
                    fired.append({"as_of": row["as_of"], "etf": key, "sector": row["sector"],
                                  "from": prev[key], "to": row["state"], "rs20": row["rs20"]})
                prev[key] = row["state"]
        out = ROOT / "data" / "runtime" / "sector_momentum_wouldhavefired.json"
        out.write_text(json.dumps({"generated_at": datetime.now(timezone.utc).isoformat(),
                                   "hypothetical": True, "sessions": args.backfill,
                                   "transitions": fired[-40:]}, default=str))
        print(f"[momentum] backfill: {len(fired)} hypothetical transitions over {args.backfill} sessions → {out.name}")
        return 0

    weights = _book_weights()
    rows = compute_states(cur)
    alerts = []
    for row in rows:
        if not row.get("state"):
            continue
        name = row["sector"]
        b_pct, b_n = _breadth(cur, name)
        hp, hd = _hermes_pulse(cur, name)
        nn, top_neg = _news_pressure(cur, name)
        w = weights.get(name) or {}
        row.update({"breadth_pct": b_pct, "breadth_n": b_n, "hermes_pulse": hp,
                    "hermes_delta": hd, "news_negatives": nn, "top_negative": top_neg,
                    "book_pct": w.get("pct"), "book_dollars": w.get("dollars")})
        # debounce: prior 2 persisted states
        cur.execute("""SELECT state FROM sector_momentum_state WHERE etf=%s
                       ORDER BY as_of DESC LIMIT %s""", (row["etf"], CFG["debounce_days"]))
        prior = [r[0] for r in cur.fetchall()]
        if not args.dry_run:
            cur.execute("""INSERT INTO sector_momentum_state
                (as_of, etf, sector, state, rs5, rs20, rs60, slope, breadth_pct, breadth_n,
                 hermes_pulse, hermes_delta, news_negatives, top_negative, book_pct, book_dollars)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (as_of, etf) DO UPDATE SET state=EXCLUDED.state, rs5=EXCLUDED.rs5,
                  rs20=EXCLUDED.rs20, rs60=EXCLUDED.rs60, slope=EXCLUDED.slope,
                  breadth_pct=EXCLUDED.breadth_pct, breadth_n=EXCLUDED.breadth_n,
                  hermes_pulse=EXCLUDED.hermes_pulse, hermes_delta=EXCLUDED.hermes_delta,
                  news_negatives=EXCLUDED.news_negatives, top_negative=EXCLUDED.top_negative,
                  book_pct=EXCLUDED.book_pct, book_dollars=EXCLUDED.book_dollars""",
                (row["as_of"], row["etf"], name, row["state"], row["rs5"], row["rs20"],
                 row["rs60"], row["slope"], b_pct, b_n, hp, hd, nn, top_neg,
                 w.get("pct"), w.get("dollars")))
        # transition = new state differs from ALL debounce-window prior states AND prior
        # window was itself uniform (state held then changed and held debounce today+prior?)
        # v1 rule: fire when today's state != yesterday's state AND today's state == the
        # state persisted for today-1 runs? Simplest faithful 2-close confirm: today's
        # state equals the last persisted state (yesterday, same new state = day-2 confirm)
        # and differs from the one before it.
        if len(prior) >= CFG["debounce_days"] and prior[0] == row["state"] and prior[-1] != row["state"]:
            sev = "info"
            if (w.get("pct") or 0) >= CFG["severity_book_weight_pct"]["urgent"]:
                sev = "urgent"
            elif (w.get("pct") or 0) >= CFG["severity_book_weight_pct"]["warning"]:
                sev = "warning"
            if nn >= CFG["news_pressure_upgrade_min_negatives"] and sev == "warning":
                sev = "urgent"
            alerts.append({
                "sector": name, "etf": row["etf"], "from": prior[-1], "to": row["state"],
                "severity": sev,
                "line": (f"⚠ {name}: {prior[-1]}→{row['state']} (day {CFG['debounce_days']} confirm) · "
                         f"RS {row['rs5']:+.1f}% (5d) · breadth {b_pct if b_pct is not None else '—'}% above 20DMA · "
                         f"your exposure {w.get('pct', 0)}% (${(w.get('dollars') or 0):,})"),
            })
    conn.commit()

    alerts = alerts[:CFG["max_alert_lines_per_day"]]
    snap = {"generated_at": datetime.now(timezone.utc).isoformat(),
            "rows": rows, "transitions_today": alerts}
    out = ROOT / "data" / "runtime" / "sector_momentum_latest.json"
    out.write_text(json.dumps(snap, default=str))
    for a in alerts:
        print(f"[momentum] TRANSITION {a['severity']}: {a['line']}")
    if alerts and not args.dry_run:
        try:
            from telegram_alert import send_telegram
            send_telegram("SECTOR MOMENTUM\n" + "\n".join(a["line"] for a in alerts), bypass_router=True)
        except Exception as e:
            print(f"[momentum] telegram failed: {e}")
    print(f"[momentum] {sum(1 for r in rows if r.get('state'))}/11 sectors classified, "
          f"{len(alerts)} confirmed transitions")
    return 0


if __name__ == "__main__":
    sys.exit(main())
