#!/usr/bin/env python3
"""M3-S4 — shadow outcome backfill (Momentum Scalp Signal Engine).

Separate T+1 job. For each logged scalp_ignition_events row that has a hypothetical entry/stop and no
outcome yet, it fetches the post-fire minute bars and fills MFE/MAE at +5/+15/+30m, hit_1r_first
(reached +1R before −1R), r_multiple_30m, and time_to_1r_sec.

STRUCTURAL ISOLATION (design §11 / Step 6): this module imports NEITHER the ignition scorer NOR the
shadow logger — and they must not import it. It reads bars + the events table and writes outcome
columns only. No proposals, no orders, no order path. Self-contained Alpaca market-data fetch.

Usage:
  python scripts/scalp_shadow_outcome_backfill.py --apply
  python scripts/scalp_shadow_outcome_backfill.py --session 2026-07-24 --apply --limit 500
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timedelta, timezone, date as _date
from pathlib import Path
from zoneinfo import ZoneInfo

import requests
import yaml

_REPO = Path(__file__).resolve().parent.parent
_CONFIG = _REPO / "config" / "scalp_signal_engine.yaml"
HORIZONS = (5, 15, 30)  # minutes


# ─────────────────────────── pure outcome math (unit-tested) ───────────────────────────

def compute_outcomes(entry: float, stop: float, post_bars: list[dict]) -> dict:
    """post_bars: ordered list of {off:int minutes-after-fire, h, l, c}. Returns MFE/MAE at each
    horizon (in price), r_multiple_30m, hit_1r_first, time_to_1r_sec. Conservative on same-bar
    target+stop touches (assumes stop first). Pure."""
    R = entry - stop
    out = {f"mfe_{h}m": None for h in HORIZONS}
    out.update({f"mae_{h}m": None for h in HORIZONS})
    out.update({"r_multiple_30m": None, "hit_1r_first": None, "time_to_1r_sec": None})
    if R is None or R <= 0 or not post_bars:
        return out
    target, stop_level = entry + R, entry - R
    # MFE/MAE by horizon
    for h in HORIZONS:
        window = [b for b in post_bars if b["off"] <= h]
        if not window:
            continue
        hi = max(b["h"] for b in window)
        lo = min(b["l"] for b in window)
        # MFE/MAE floored at 0 (TCA convention): no favorable/adverse move → 0, never negative.
        out[f"mfe_{h}m"] = round(max(0.0, hi - entry), 6)
        out[f"mae_{h}m"] = round(max(0.0, entry - lo), 6)
    # r_multiple at ~30m (last bar within 30m)
    w30 = [b for b in post_bars if b["off"] <= 30]
    if w30:
        out["r_multiple_30m"] = round((w30[-1]["c"] - entry) / R, 4)
    # hit_1r_first: walk bars in order
    for b in post_bars:
        if b["off"] > 30:
            break
        hits_target = b["h"] >= target
        hits_stop = b["l"] <= stop_level
        if hits_target and hits_stop:
            out["hit_1r_first"] = False          # conservative: stop assumed first
            out["time_to_1r_sec"] = None
            return out
        if hits_target:
            out["hit_1r_first"] = True
            out["time_to_1r_sec"] = int(b["off"] * 60)
            return out
        if hits_stop:
            out["hit_1r_first"] = False
            out["time_to_1r_sec"] = None
            return out
    # neither within 30m → unresolved (leave hit_1r_first None)
    return out


# ─────────────────────────── self-contained I/O (no engine imports) ───────────────────────────

def _cfg() -> dict:
    return yaml.safe_load(_CONFIG.read_text(encoding="utf-8"))


def _conn():
    try:
        from db_adapter import get_connection
    except ModuleNotFoundError:
        from scripts.db_adapter import get_connection
    return get_connection()


def _alpaca_keys() -> tuple[str, str]:
    try:
        from dotenv import load_dotenv
        load_dotenv(str(_REPO / ".env"))
    except Exception:
        pass
    key = os.environ.get("ALPACA_PAPER_API_KEY") or os.environ.get("ALPACA_API_KEY") or ""
    sec = os.environ.get("ALPACA_PAPER_SECRET_KEY") or os.environ.get("ALPACA_SECRET_KEY") or ""
    if not key or not sec:
        raise RuntimeError("Alpaca market-data keys not found in env")
    return key, sec


def fetch_bars(symbol: str, cfg: dict, session_day: str) -> list[dict]:
    """Fetch the symbol's 1-minute bars covering session_day (self-contained; no engine import)."""
    key, sec = _alpaca_keys()
    h = {"APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": sec}
    d = cfg["data"]
    end = datetime.now(timezone.utc).date()
    days = (end - _date.fromisoformat(session_day)).days + 3
    params = {"timeframe": d.get("timeframe", "1Min"), "start": (end - timedelta(days=days)).isoformat(),
              "end": end.isoformat(), "limit": 10000, "feed": d.get("feed", "iex"), "adjustment": "raw"}
    url = d["bars_endpoint"].format(symbol=symbol)
    out, token = [], None
    for _ in range(200):
        p = dict(params)
        if token:
            p["page_token"] = token
        r = requests.get(url, headers=h, params=p, timeout=45)
        if r.status_code != 200:
            raise RuntimeError(f"bars {symbol}: HTTP {r.status_code}")
        j = r.json()
        out.extend(j.get("bars") or [])
        token = j.get("next_page_token")
        if not token:
            break
    return out


def post_fire_bars(all_bars: list[dict], fire_dt: datetime, tz: ZoneInfo, horizon_min: int = 30) -> list[dict]:
    """Bars strictly after the fire minute, up to horizon_min later, as {off, h, l, c}."""
    out = []
    for b in all_bars:
        bt = datetime.fromisoformat(b["t"].replace("Z", "+00:00")).astimezone(tz)
        off = (bt - fire_dt).total_seconds() / 60.0
        if 0 < off <= horizon_min:
            out.append({"off": off, "h": float(b["h"]), "l": float(b["l"]), "c": float(b["c"])})
    out.sort(key=lambda x: x["off"])
    return out


def run(args) -> int:
    cfg = _cfg()
    tz = ZoneInfo(cfg["session"]["tz"])
    conn = _conn()
    where = ["outcome_filled_at IS NULL", "entry_ref IS NOT NULL", "stop_ref IS NOT NULL"]
    params: list = []
    if args.session:
        where.append("session_date = %s"); params.append(args.session)
    else:
        # only sessions that have had >=30 min to resolve
        where.append("fired_at < now() - interval '31 minutes'")
    sql = f"""SELECT id, symbol, fired_at, session_date, entry_ref, stop_ref
              FROM scalp_ignition_events WHERE {' AND '.join(where)}
              ORDER BY session_date, symbol LIMIT %s"""
    params.append(int(args.limit))
    with conn.cursor() as cur:
        cur.execute(sql, params)
        rows = cur.fetchall()
    print(f"backfill: {len(rows)} events pending  apply={args.apply}")

    bar_cache: dict[tuple, list] = {}
    filled = resolved = 0
    for eid, symbol, fired_at, sday, entry, stop in rows:
        sday_s = sday.isoformat()
        ckey = (symbol, sday_s)
        if ckey not in bar_cache:
            try:
                bar_cache[ckey] = fetch_bars(symbol, cfg, sday_s)
            except Exception as e:
                print(f"  {symbol} {sday_s}: fetch ERR {e}"); bar_cache[ckey] = []
        pb = post_fire_bars(bar_cache[ckey], fired_at.astimezone(tz), tz, 30)
        oc = compute_outcomes(float(entry), float(stop), pb)
        if oc["hit_1r_first"] is not None:
            resolved += 1
        if args.apply:
            with conn.cursor() as cur:
                cur.execute(
                    """UPDATE scalp_ignition_events SET
                         mfe_5m=%s, mae_5m=%s, mfe_15m=%s, mae_15m=%s, mfe_30m=%s, mae_30m=%s,
                         r_multiple_30m=%s, hit_1r_first=%s, time_to_1r_sec=%s, outcome_filled_at=now()
                       WHERE id=%s""",
                    [oc["mfe_5m"], oc["mae_5m"], oc["mfe_15m"], oc["mae_15m"], oc["mfe_30m"], oc["mae_30m"],
                     oc["r_multiple_30m"], oc["hit_1r_first"], oc["time_to_1r_sec"], eid])
            filled += 1
    if args.apply:
        conn.commit()
    print(f"  filled={filled} resolved(hit_1r not null)={resolved}")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="M3-S4 shadow outcome backfill (isolated; no engine import)")
    ap.add_argument("--session", help="YYYY-MM-DD (default: all resolvable pending)")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--limit", default=2000)
    return run(ap.parse_args(argv))


if __name__ == "__main__":
    sys.exit(main())
