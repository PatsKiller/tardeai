#!/usr/bin/env python3
"""stop_policy_migration_report — one-shot divergence report for the tier migration.

Classifies every current holding under config/stop_policy.yaml, computes each
holding's effective stop distance (live software/broker stop vs current price)
and flags stops sitting OUTSIDE the new tier band. Advisory output only — this
script never modifies a stop; every change goes through the existing advisory →
operator → (Schwab 2FA / Fidelity manual / Alpaca paper) path.

Usage: .venv/bin/python scripts/stop_policy_migration_report.py [--json]
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))


def main() -> int:
    import holding_family as hf
    from dotenv import load_dotenv
    load_dotenv(str(ROOT / ".env"))

    holdings = json.loads((ROOT / "data" / "portfolios" / "state" / "holdings.json")
                          .read_text()).get("holdings", [])

    # live stops keyed by symbol — the same canonical read stop_drift_alert uses
    # (manual_broker_stops + fidelity_monitored_stops + synthetic_stops)
    stops_by_sym: dict[str, dict] = {}
    try:
        from db_adapter import _get_conn
        conn = _get_conn()
        cur = conn.cursor()
        for sql in (
            """SELECT UPPER(symbol), stop_price, account FROM manual_broker_stops
               WHERE active=TRUE AND stop_price IS NOT NULL
                 AND lower(COALESCE(status,'open')) NOT IN
                     ('filled','canceled','cancelled','expired','rejected','replaced')""",
            """SELECT UPPER(symbol), COALESCE(effective_stop, stop_price), account
               FROM fidelity_monitored_stops
               WHERE active=TRUE AND COALESCE(effective_stop, stop_price) IS NOT NULL""",
            """SELECT UPPER(symbol), stop_price, account FROM synthetic_stops
               WHERE lower(COALESCE(status,'active'))='active'
                 AND stop_price IS NOT NULL""",
        ):
            try:
                cur.execute(sql)
                for sym, sp, acct in cur.fetchall():
                    sp = float(sp or 0)
                    prev = stops_by_sym.get(sym)
                    if sp > 0 and (prev is None or sp > prev["stop_price"]):
                        stops_by_sym[sym] = {"account": str(acct or ""),
                                             "stop_price": sp}
            except Exception:
                conn.rollback()
        conn.rollback()
    except Exception as e:
        print(f"note: live stop read unavailable ({e}) — classification only",
              file=sys.stderr)

    rows, diverged = [], []
    for h in holdings:
        sym = str(h.get("symbol") or "").upper()
        price = float(h.get("current_price") or h.get("price") or 0)
        value = float(h.get("market_value") or 0)
        if not sym or value < 100:
            continue
        fam, src = hf.classify_family(sym, atr_pct=None)
        b = hf.protection_bounds(fam)
        row = {"symbol": sym, "account": h.get("account"), "value_usd": round(value),
               "tier": fam, "tier_label": b["label"], "tier_source": src,
               "band_pct": [b["stop_min_pct"], b["stop_max_pct"]],
               "trail_band_pct": [b["trail_min_pct"], b["trail_max_pct"]]}
        st = stops_by_sym.get(sym)
        if st and price > 0 and st["stop_price"] > 0:
            dist = (price - st["stop_price"]) / price * 100
            row["stop_price"] = st["stop_price"]
            row["stop_distance_pct"] = round(dist, 1)
            if dist < b["stop_min_pct"]:
                row["divergence"] = f"TIGHTER than band (min {b['stop_min_pct']}%)"
            elif dist > b["stop_max_pct"]:
                row["divergence"] = f"WIDER than band (max {b['stop_max_pct']}%)"
            if row.get("divergence"):
                diverged.append(row)
        else:
            row["stop_price"] = None
            if hf.is_unstoppable_fund(sym):
                row["note"] = "fund — no stop by design"
            else:
                row["note"] = "no live stop"
        rows.append(row)

    rows.sort(key=lambda r: -r["value_usd"])
    report = {"policy_version": hf._policy().get("version"),
              "holdings": len(rows), "with_live_stop": len(stops_by_sym),
              "diverged": len(diverged), "divergences": diverged, "rows": rows}

    if "--json" in sys.argv:
        print(json.dumps(report, indent=2))
        return 0
    print(f"stop-policy migration report · policy {report['policy_version']} · "
          f"{report['holdings']} holdings · {report['diverged']} outside new bands\n")
    print(f"{'SYM':6} {'VALUE':>9} {'TIER':17} {'BAND':9} {'STOP':>8} {'DIST':>6}  SOURCE/NOTE")
    for r in rows:
        band = f"{r['band_pct'][0]:.0f}-{r['band_pct'][1]:.0f}%"
        stop = f"${r['stop_price']:.2f}" if r.get("stop_price") else "—"
        dist = f"{r['stop_distance_pct']}%" if r.get("stop_distance_pct") is not None else "—"
        flag = " ← " + r["divergence"] if r.get("divergence") else (
            "  (" + r["note"] + ")" if r.get("note") else "")
        print(f"{r['symbol']:6} {r['value_usd']:>9,} {r['tier']:17} {band:9} "
              f"{stop:>8} {dist:>6}  {r['tier_source']}{flag}")
    if diverged:
        print(f"\n{len(diverged)} stop(s) outside the new tier band — advisory only. "
              "Apply changes via the Stop Management tab (Schwab = per-order 2FA; "
              "Fidelity = manual ticket; Alpaca = paper auto).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
