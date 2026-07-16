#!/usr/bin/env python3
"""Watch Desk v3 (WS-A2): candidate-source outcome reconciler.

Every anchored watch_candidate_events row ≥21 trading-ish days old gets +21d
(and +63d when available) symbol return vs SPY and a verdict:
OUTPERFORM (α>+3%) / MARKET (−3..+3) / UNDERPERFORM (α<−3%) / NOT_EVALUABLE.
Unanchored events stay NOT_EVALUABLE — attribution is never guessed.
Weekly cron (Sunday); per-run cap keeps bar fetches bounded.
"""
from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
try:
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
except Exception:
    pass

CAP_EVENTS = 400


def _closes(symbol: str, bars_cache: dict) -> list[tuple[dt.date, float]]:
    if symbol in bars_cache:
        return bars_cache[symbol]
    from holdings_gain_guardian import _bars_with_volume
    seq = []
    for b in _bars_with_volume(symbol, days=160):
        ts = b.get("datetime") or b.get("t") or b.get("date") or ""
        try:
            when = (dt.datetime.fromtimestamp(ts / 1000, dt.timezone.utc).date()
                    if isinstance(ts, (int, float)) else dt.date.fromisoformat(str(ts)[:10]))
        except Exception:
            continue
        c = float(b.get("close") or 0)
        if c > 0:
            seq.append((when, c))
    bars_cache[symbol] = seq
    return seq


def _ret_after(seq, start: dt.date, anchor: float, tdays: int):
    after = [c for (d, c) in seq if d > start]
    if len(after) <= tdays or anchor <= 0:
        return None
    return round(100.0 * (after[tdays] / anchor - 1), 2)


def main() -> int:
    from db_adapter import _execute as ex, USE_DB
    if not USE_DB:
        print("DB unavailable", file=sys.stderr)
        return 2
    rows = ex("""SELECT id, symbol, emitted_on, anchor_price FROM watch_candidate_events
                 WHERE verdict IS NULL AND anchor_price IS NOT NULL
                   AND emitted_on <= CURRENT_DATE - 30
                 ORDER BY emitted_on ASC LIMIT %s""", (CAP_EVENTS,), fetch="all") or []
    # unanchored past-due events settle as NOT_EVALUABLE immediately (honest, cheap)
    ex("""UPDATE watch_candidate_events SET verdict='NOT_EVALUABLE', evaluated_at=NOW()
          WHERE verdict IS NULL AND anchor_price IS NULL AND emitted_on <= CURRENT_DATE - 30""", fetch=None)
    if not rows:
        print("[watch-outcomes] no anchored events due — clean run")
        return 0
    cache: dict = {}
    spy = _closes("SPY", cache)
    done = 0
    for r in rows:
        seq = _closes(r["symbol"], cache)
        a = float(r["anchor_price"])
        ret21 = _ret_after(seq, r["emitted_on"], a, 21)
        spy_anchor = next((c for (d, c) in spy if d >= r["emitted_on"]), None)
        spy21 = _ret_after(spy, r["emitted_on"], spy_anchor, 21) if spy_anchor else None
        ret63 = _ret_after(seq, r["emitted_on"], a, 63)
        spy63 = _ret_after(spy, r["emitted_on"], spy_anchor, 63) if spy_anchor else None
        if ret21 is None or spy21 is None:
            verdict, a21 = "NOT_EVALUABLE", None
        else:
            a21 = round(ret21 - spy21, 2)
            verdict = "OUTPERFORM" if a21 > 3 else "UNDERPERFORM" if a21 < -3 else "MARKET"
        a63 = round(ret63 - spy63, 2) if (ret63 is not None and spy63 is not None) else None
        ex("""UPDATE watch_candidate_events
              SET ret_21d=%s, spy_21d=%s, alpha_21d=%s, ret_63d=%s, spy_63d=%s, alpha_63d=%s,
                  verdict=%s, evaluated_at=NOW() WHERE id=%s""",
           (ret21, spy21, a21, ret63, spy63, a63, verdict, r["id"]), fetch=None)
        done += 1
    lg = ex("""SELECT source_type, count(*) FILTER (WHERE verdict NOT IN ('NOT_EVALUABLE')) AS n,
                      round(percentile_cont(0.5) WITHIN GROUP (ORDER BY alpha_21d)::numeric, 2) AS median_a21
               FROM watch_candidate_events WHERE alpha_21d IS NOT NULL GROUP BY 1 ORDER BY 1""", fetch="all") or []
    print(f"[watch-outcomes] evaluated {done} events · league:",
          " / ".join(f"{r['source_type']} α{r['median_a21']:+} (n={r['n']})" for r in lg))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
