#!/usr/bin/env python3
"""compute_intraday_vwap.py — session VWAP for active broker-proposal symbols.

VWAP is an intraday indicator (it resets each session and needs intraday bars), so Finviz daily data
can't provide it. This pulls today's 5-minute bars via yfinance and computes the volume-weighted
average price = Σ(typical_price × volume) / Σ(volume), then caches {vwap, above_vwap, dist_pct} per
symbol. The proposals API (_ma_context) reads this cache and the card's Entry-helper strip shows it.

Only meaningful during / right after a trading session; thin ETFs may have few bars (still valid).

Cron (every 20m on weekdays during market hours, flock-guarded):
    /usr/bin/flock -n /tmp/intraday_vwap.lock .venv/bin/python scripts/compute_intraday_vwap.py
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
CACHE = ROOT / "data" / "state" / "intraday_vwap_cache.json"


def _active_symbols() -> list[str]:
    from db_adapter import _execute
    rows = _execute(
        """SELECT DISTINCT symbol FROM paper_trade_proposals
           WHERE status IN ('PENDING','APPROVED_FOR_PAPER_TEST')
              OR (status='EXPIRED' AND created_at > now() - interval '3 days')""",
        None, fetch="all") or []
    return sorted({(r["symbol"] or "").upper() for r in rows if r.get("symbol")})


def main():
    import yfinance as yf

    syms = _active_symbols()
    if not syms:
        print("[intraday_vwap] no active proposal symbols")
        return
    out: dict = {}
    try:
        out = json.loads(CACHE.read_text()) if CACHE.exists() else {}
    except Exception:
        out = {}

    now = datetime.now(timezone.utc).isoformat()
    done = 0
    # Batch through yfinance to keep each request light.
    for i in range(0, len(syms), 40):
        batch = syms[i:i + 40]
        try:
            df = yf.download(batch, period="1d", interval="5m", group_by="ticker",
                             threads=True, progress=False, auto_adjust=False)
        except Exception as e:
            print(f"  [intraday_vwap] batch {i} error: {str(e)[:80]}")
            continue
        for s in batch:
            try:
                sub = df[s] if len(batch) > 1 else df
                sub = sub.dropna(subset=["Close", "Volume"])
                vol = sub["Volume"].astype(float)
                if vol.sum() <= 0 or len(sub) == 0:
                    continue
                typ = (sub["High"].astype(float) + sub["Low"].astype(float) + sub["Close"].astype(float)) / 3.0
                vwap = float((typ * vol).sum() / vol.sum())
                last = float(sub["Close"].astype(float).iloc[-1])
                if vwap <= 0:
                    continue
                out[s] = {
                    "vwap": round(vwap, 2),
                    "last": round(last, 2),
                    "above_vwap": last >= vwap,
                    "dist_pct": round((last - vwap) / vwap * 100, 2),
                    "bars": int(len(sub)),
                    "computed_at": now,
                }
                done += 1
            except Exception:
                continue

    out["_meta"] = {"computed_at": now, "symbols": done}
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    CACHE.write_text(json.dumps(out, indent=2))
    print(f"[intraday_vwap] computed VWAP for {done}/{len(syms)} symbol(s) → {CACHE.name}")


if __name__ == "__main__":
    main()
