#!/usr/bin/env python3
"""finviz_industry_groups.py — Defense Desk v2 WS-B2: the industry rotation layer.

One Finviz Elite groups export (grp_export.ashx?g=industry&v=141 — 144 industries ×
Perf W/M/Q/H/Y/YTD) per run, through the shared finviz_throttle. Quadrant mapping
(documented): level = perf_month − SPY 21-session return, direction = perf_week −
SPY 5-session return, fed into the SAME classify() as sectors:
  LEADING (rel1m>=0, rel1w>=0) · WEAKENING (rel1m>=0, rel1w<0)
  · LAGGING (rel1m<0, rel1w<0) · IMPROVING (rel1m<0, rel1w>=0)

States persist ONLY on --close runs (one state-observation per session → the sector
debounce rule applies unchanged: 2nd consecutive close in a new state = confirmed).
Midday runs refresh display numbers, never states. Alerts fire ONLY for confirmed
transitions in industries intersecting the BOOK or WATCH universe, capped.

Candidate feeds (advisory pools, source_type=industry_momentum — never auto-trade):
  confirmed LAGGING (worst rel1w) → defensive_short pool · confirmed IMPROVING → watch rail

Budget: 1 export/run, 2 runs/day (12:30 refresh + 16:18 close) per the v2 cadence note.

Usage: finviz_industry_groups.py [--close] [--dry-run]
"""
import argparse
import csv
import io
import json
import os
import re
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "scripts" / "lib"))

from sector_momentum_engine import CFG, classify, _closes, _ret  # noqa: E402

try:
    from finviz_throttle import acquire as _fv_acquire, cooldown as _fv_cooldown
except Exception:
    def _fv_acquire(*a, **k): return 0.0
    def _fv_cooldown(*a, **k): pass

SNAP = ROOT / "data" / "runtime" / "industry_momentum_latest.json"
URL = "https://elite.finviz.com/grp_export.ashx?g=industry&v=141"
MAX_ALERTS = 3
POOL_N = 10
_CLOSE_LOCK_FD = None


def _acquire_close_lock() -> None:
    """Process-level singleton for --close. Cron already flocks; health remediations did not."""
    global _CLOSE_LOCK_FD
    try:
        import fcntl
        p = Path("/tmp/industry_momentum_close.lock")
        _CLOSE_LOCK_FD = open(p, "w")
        fcntl.flock(_CLOSE_LOCK_FD.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        _CLOSE_LOCK_FD.write(str(os.getpid()))
        _CLOSE_LOCK_FD.flush()
    except BlockingIOError:
        print("[industry] another --close is running — refusing duplicate close persist")
        raise SystemExit(0)
    except Exception:
        pass  # lock is best-effort; semantic dedupe is the real backstop


def _cookie() -> str:
    import os
    import sys
    try:
        _sec = ROOT / "scripts" / "secrets"
        if str(_sec) not in sys.path:
            sys.path.insert(0, str(_sec))
        from resolve_secret import resolve_secret
        return resolve_secret("FINVIZ_COOKIE", "")
    except Exception:
        try:
            for line in (ROOT / ".env").read_text().splitlines():
                if line.startswith("FINVIZ_COOKIE="):
                    return line.split("=", 1)[1].strip().strip('"\'')
        except Exception:
            pass
        return os.environ.get("FINVIZ_COOKIE", "").strip().strip('"\'')


def _pct(v):
    try:
        return float(str(v).replace("%", "").strip())
    except (ValueError, TypeError):
        return None


def fetch_groups() -> list[dict]:
    _fv_acquire()
    req = urllib.request.Request(URL, headers={
        "User-Agent": "Mozilla/5.0", "Cookie": _cookie(),
        "Referer": "https://elite.finviz.com/groups.ashx"})
    try:
        with urllib.request.urlopen(req, timeout=25) as r:
            content = r.read().decode("utf-8", "ignore")
    except urllib.error.HTTPError as e:
        if e.code == 429:
            _fv_cooldown()
        raise
    rows = []
    for rec in csv.DictReader(io.StringIO(content)):
        name = (rec.get("Name") or "").strip()
        if not name:
            continue
        rows.append({
            "industry": name,
            "perf_week": _pct(rec.get("Performance (Week)")),
            "perf_month": _pct(rec.get("Performance (Month)")),
            "perf_quarter": _pct(rec.get("Performance (Quarter)")),
            "perf_half": _pct(rec.get("Performance (Half Year)")),
            "perf_year": _pct(rec.get("Performance (Year)")),
            "perf_ytd": _pct(rec.get("Performance (Year To Date)")),
            "change_1d": _pct(rec.get("Change")),
            "stocks": int(float(rec.get("Stocks") or 0)) or None,
        })
    return rows


def sector_map(cur) -> dict:
    """industry → modal sector, from finviz-enriched scans (names match groups export)."""
    cur.execute("""SELECT industry, sector FROM (
                     SELECT industry, sector, count(*) n,
                            row_number() OVER (PARTITION BY industry ORDER BY count(*) DESC) rk
                     FROM trade_ai_scans
                     WHERE industry IS NOT NULL AND sector IS NOT NULL AND sector <> ''
                     GROUP BY industry, sector) x WHERE rk = 1""")
    return dict(cur.fetchall())


def book_watch_industries(cur) -> tuple[dict, dict]:
    """{industry: [symbols]} for the held book and operator-starred watch names.

    Watch = operator_starred_symbols (operator conviction), NOT watchlist_items —
    5,200+ active items would mark every industry 'watched' and kill alert gating."""
    try:
        holdings = json.loads(
            (ROOT / "data" / "portfolios" / "state" / "holdings.json").read_text())
        held = sorted({h.get("symbol") for h in holdings.get("holdings", []) if h.get("symbol")})
    except Exception:
        held = []
    cur.execute("""SELECT DISTINCT ON (symbol) symbol, industry FROM trade_ai_scans
                   WHERE symbol = ANY(%s) AND industry IS NOT NULL
                   ORDER BY symbol, scanned_at DESC""", (held,))
    book = {}
    for sym, industry in cur.fetchall():
        book.setdefault(industry, []).append(sym)
    watch = {}
    try:
        cur.execute("""SELECT DISTINCT ON (s.symbol) s.symbol, t.industry
                       FROM operator_starred_symbols s
                       JOIN trade_ai_scans t ON t.symbol = s.symbol
                       WHERE t.industry IS NOT NULL
                       ORDER BY s.symbol, t.scanned_at DESC""")
        for sym, industry in cur.fetchall():
            watch.setdefault(industry, []).append(sym)
    except Exception:
        cur.connection.rollback()
    return book, watch


def spy_baseline(cur):
    """SPY 5- and 21-session returns from ticker_prices (matches Finviz W/M windows)."""
    series = _closes(cur, ["SPY"], days=60).get("SPY", [])
    dates = sorted({d for d, _ in series})
    dedup = []
    seen = set()
    for d, px in sorted(series):
        if d not in seen:
            seen.add(d)
            dedup.append((d, px))
    i = len(dedup) - 1
    return _ret(dedup, i, 5), _ret(dedup, i, 21)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--close", action="store_true",
                    help="close capture: persist states + run debounce/alerts")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    from db_adapter import _get_conn
    conn = _get_conn()
    cur = conn.cursor()
    cur.execute("""CREATE TABLE IF NOT EXISTS industry_momentum_state (
        as_of date NOT NULL, industry text NOT NULL, sector text, state text,
        rel1w numeric, rel1m numeric, perf_week numeric, perf_month numeric,
        perf_quarter numeric, perf_ytd numeric, change_1d numeric, stocks int,
        created_at timestamptz DEFAULT now(), PRIMARY KEY (as_of, industry))""")
    conn.commit()

    groups = fetch_groups()
    if len(groups) < 100:  # fail-closed: partial export never overwrites state/snapshot
        print(f"[industry] FAIL-CLOSED: only {len(groups)} groups parsed — aborting")
        return 1

    spy1w, spy1m = spy_baseline(cur)
    if spy1w is None or spy1m is None:
        print("[industry] FAIL-CLOSED: SPY baseline unavailable")
        return 1

    smap = sector_map(cur)
    book, watch = book_watch_industries(cur)

    for g in groups:
        g["sector"] = smap.get(g["industry"])
        g["rel1w"] = round(g["perf_week"] - spy1w, 2) if g["perf_week"] is not None else None
        g["rel1m"] = round(g["perf_month"] - spy1m, 2) if g["perf_month"] is not None else None
        g["state"] = classify(g["rel1m"], g["rel1w"])
        g["held"] = book.get(g["industry"], [])
        g["watched"] = watch.get(g["industry"], [])

    alerts, confirmed = [], []
    notify_plan = {"send": [], "suppressed": [], "observations": []}
    if args.close:
        # Singleton: one close-state process at a time. Health-inspector remediations
        # used to invoke --close every ~2 minutes without the cron flock.
        _acquire_close_lock()
        from industry_momentum import build_alerts, decide_notifications, emit_telegram, is_confirmed
        d = CFG["debounce_days"]
        for g in groups:
            if not g["state"]:
                continue
            # Prior SESSIONS only. Including today's already-persisted row made every
            # same-day --close replay look like a fresh confirmation.
            cur.execute("""SELECT state FROM industry_momentum_state
                           WHERE industry=%s AND as_of < CURRENT_DATE
                           ORDER BY as_of DESC LIMIT %s""", (g["industry"], d))
            prior = [r[0] for r in cur.fetchall()]
            if is_confirmed(prior, g["state"], d):
                confirmed.append({"industry": g["industry"], "sector": g["sector"],
                                  "from": prior[-1], "to": g["state"],
                                  "rel1w": g["rel1w"], "rel1m": g["rel1m"],
                                  "held": g["held"], "watched": g["watched"]})
            if not args.dry_run:
                cur.execute("""INSERT INTO industry_momentum_state
                    (as_of, industry, sector, state, rel1w, rel1m, perf_week, perf_month,
                     perf_quarter, perf_ytd, change_1d, stocks)
                    VALUES (CURRENT_DATE,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    ON CONFLICT (as_of, industry) DO UPDATE SET state=EXCLUDED.state,
                      rel1w=EXCLUDED.rel1w, rel1m=EXCLUDED.rel1m,
                      perf_week=EXCLUDED.perf_week, perf_month=EXCLUDED.perf_month,
                      perf_quarter=EXCLUDED.perf_quarter, perf_ytd=EXCLUDED.perf_ytd,
                      change_1d=EXCLUDED.change_1d, stocks=EXCLUDED.stocks""",
                    (g["industry"], g["sector"], g["state"], g["rel1w"], g["rel1m"],
                     g["perf_week"], g["perf_month"], g["perf_quarter"], g["perf_ytd"],
                     g["change_1d"], g["stocks"]))
        conn.commit()
        alerts = build_alerts(confirmed, max_alerts=MAX_ALERTS)
        session = datetime.now().date().isoformat()
        notify_plan = decide_notifications(alerts, session=session)

    ranked = sorted((g for g in groups if g["rel1w"] is not None),
                    key=lambda g: g["rel1w"], reverse=True)
    lagging = [g for g in groups if g["state"] == "LAGGING"]
    improving = [g for g in groups if g["state"] == "IMPROVING"]
    by_sector = {}
    for g in groups:
        by_sector.setdefault(g["sector"] or "Other", []).append(g["industry"])

    snap = {
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "capture_kind": "close" if args.close else "refresh",
        "spy_baseline": {"w1": round(spy1w, 2), "m1": round(spy1m, 2)},
        "quadrant_mapping": "level=perf_month−SPY21d, direction=perf_week−SPY5d (same classify as sectors)",
        "industries": groups,
        "by_sector": by_sector,
        "top10": [g["industry"] for g in ranked[:10]],
        "bottom10": [g["industry"] for g in ranked[-10:]][::-1],
        "candidates": {
            "source_type": "industry_momentum",
            "defensive_short_pool": [
                {"industry": g["industry"], "sector": g["sector"], "rel1w": g["rel1w"]}
                for g in sorted(lagging, key=lambda x: x["rel1w"] or 0)[:POOL_N]],
            "watch_rail": [
                {"industry": g["industry"], "sector": g["sector"], "rel1w": g["rel1w"]}
                for g in sorted(improving, key=lambda x: x["rel1w"] or 0, reverse=True)[:POOL_N]],
        },
        "transitions_confirmed": confirmed,
        "alerts": notify_plan.get("send") or [],
        "alerts_suppressed": [a.get("line") for a in (notify_plan.get("suppressed") or [])],
        "counts": {s: sum(1 for g in groups if g["state"] == s) for s in
                   ("LEADING", "WEAKENING", "LAGGING", "IMPROVING")},
    }
    if not args.dry_run:
        SNAP.parent.mkdir(parents=True, exist_ok=True)
        SNAP.write_text(json.dumps(snap, default=str))
    for a in notify_plan.get("send") or []:
        print("[industry ALERT]", a["line"])
    for a in notify_plan.get("suppressed") or []:
        print("[industry SUPPRESSED]", a.get("line"))
    if (notify_plan.get("send") or []) and not args.dry_run:
        try:
            from industry_momentum import emit_telegram
            from telegram_alert import send_telegram
            # Governed path: Signal-over-Spam router. Never bypass_router.
            emit_telegram(notify_plan, send_telegram)
        except Exception as e:
            print(f"[industry] telegram failed: {e}")
    print(f"[industry] {len(groups)} groups · counts {snap['counts']} · "
          f"{len(confirmed)} confirmed transitions · {len(notify_plan.get('send') or [])} alerts · "
          f"{len(notify_plan.get('suppressed') or [])} suppressed · "
          f"snapshot {SNAP.stat().st_size if SNAP.exists() and not args.dry_run else 0}B")
    return 0


if __name__ == "__main__":
    sys.exit(main())
