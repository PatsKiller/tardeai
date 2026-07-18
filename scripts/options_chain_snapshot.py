#!/usr/bin/env python3
"""options_chain_snapshot.py — Defense Desk v3 R1: nightly chain snapshots → hedging radar.

Read-only: schwab_transport.get_option_chain (near-ATM, strike_count from config) over the
priority universe (sector ETFs + SPY/QQQ) then top-N holdings by value. Per underlying we
persist AGGREGATES ONLY (full chains are huge): put/call OI + volume, ATM IV, ~25-delta
skew. Deltas vs the prior snapshot and P/C-vs-20d-mean accrue as history builds — n is
always stated, never implied. This is POSITIONING INFERENCE, never "order flow".

Coverage is stated in the output: if the window can't complete every underlying, priority
universe first, then holdings, and the snapshot says exactly what was covered.

Usage: options_chain_snapshot.py [--dry-run] [--limit N]
"""
import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

CFG = json.loads((ROOT / "config" / "defense_recommendations.json").read_text())["chain_snapshot"]
SNAP = ROOT / "data" / "runtime" / "hedging_radar_latest.json"


def universe() -> list:
    syms = list(CFG["priority_universe"])
    try:
        h = json.loads((ROOT / "data" / "portfolios" / "state" / "holdings.json").read_text())
        rows = [r for r in h.get("holdings", []) if not r.get("is_cash") and r.get("symbol")]
        rows.sort(key=lambda r: -(r.get("market_value") or 0))
        for r in rows[:CFG["top_holdings_n"]]:
            if r["symbol"] not in syms:
                syms.append(r["symbol"])
    except Exception as e:
        print(f"[radar] holdings unavailable ({e}) — priority universe only")
    return syms


def aggregate(chain: dict) -> dict | None:
    """One underlying's chain → radar aggregates."""
    if not chain or chain.get("status") != "ok":
        return None
    put_oi = call_oi = put_vol = call_vol = 0
    atm_ivs, put25, call25 = [], [], []
    tgt = CFG["skew_delta_target"]
    for exp in chain.get("expirations", []):
        put_oi += exp.get("total_put_oi") or 0
        call_oi += exp.get("total_call_oi") or 0
        for s in exp.get("strikes", []):
            v, d, iv = s.get("volume") or 0, s.get("delta"), s.get("iv")
            if s["side"] == "put":
                put_vol += v
            else:
                call_vol += v
            if d is None or iv is None or iv <= 0:
                continue
            ad = abs(float(d))
            if 0.45 <= ad <= 0.55:
                atm_ivs.append(float(iv))
            if s["side"] == "put" and abs(ad - tgt) <= 0.08:
                put25.append(float(iv))
            if s["side"] == "call" and abs(ad - tgt) <= 0.08:
                call25.append(float(iv))
    mean = lambda xs: round(sum(xs) / len(xs), 2) if xs else None
    return {
        "put_oi": put_oi, "call_oi": call_oi, "put_vol": put_vol, "call_vol": call_vol,
        "pc_oi_ratio": round(put_oi / call_oi, 3) if call_oi else None,
        "pc_vol_ratio": round(put_vol / call_vol, 3) if call_vol else None,
        "atm_iv": mean(atm_ivs),
        "skew25": round(mean(put25) - mean(call25), 2) if put25 and call25 else None,
        "underlying_price": chain.get("underlying_price"),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    from db_adapter import _get_conn
    from schwab_transport import get_option_chain
    conn = _get_conn()
    cur = conn.cursor()
    cur.execute("""CREATE TABLE IF NOT EXISTS option_chain_snapshots (
        as_of date NOT NULL, symbol text NOT NULL, put_oi bigint, call_oi bigint,
        put_vol bigint, call_vol bigint, pc_oi_ratio numeric, pc_vol_ratio numeric,
        atm_iv numeric, skew25 numeric, underlying_price numeric,
        created_at timestamptz DEFAULT now(), PRIMARY KEY (as_of, symbol))""")
    conn.commit()

    syms = universe()
    if args.limit:
        syms = syms[:args.limit]
    covered, failed = [], []
    rows = {}
    for sym in syms:
        try:
            agg = aggregate(get_option_chain(sym, strike_count=CFG["strike_count"]))
        except Exception as e:
            agg = None
            print(f"[radar] {sym} chain error: {e}")
        if not agg or (not agg["put_oi"] and not agg["call_oi"]):
            failed.append(sym)
            continue
        covered.append(sym)
        rows[sym] = agg
        if not args.dry_run:
            cur.execute("""INSERT INTO option_chain_snapshots
                (as_of, symbol, put_oi, call_oi, put_vol, call_vol, pc_oi_ratio,
                 pc_vol_ratio, atm_iv, skew25, underlying_price)
                VALUES (CURRENT_DATE,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (as_of, symbol) DO UPDATE SET put_oi=EXCLUDED.put_oi,
                  call_oi=EXCLUDED.call_oi, put_vol=EXCLUDED.put_vol,
                  call_vol=EXCLUDED.call_vol, pc_oi_ratio=EXCLUDED.pc_oi_ratio,
                  pc_vol_ratio=EXCLUDED.pc_vol_ratio, atm_iv=EXCLUDED.atm_iv,
                  skew25=EXCLUDED.skew25, underlying_price=EXCLUDED.underlying_price""",
                (sym, agg["put_oi"], agg["call_oi"], agg["put_vol"], agg["call_vol"],
                 agg["pc_oi_ratio"], agg["pc_vol_ratio"], agg["atm_iv"], agg["skew25"],
                 agg["underlying_price"]))
    if not args.dry_run:
        conn.commit()

    # deltas vs prior snapshot date + P/C vol vs mean over available history (n stated)
    radar = []
    for sym, agg in rows.items():
        cur.execute("""SELECT put_oi, call_oi, skew25 FROM option_chain_snapshots
                       WHERE symbol=%s AND as_of < CURRENT_DATE
                       ORDER BY as_of DESC LIMIT 1""", (sym,))
        prior = cur.fetchone()
        cur.execute("""SELECT avg(pc_vol_ratio), count(*) FROM option_chain_snapshots
                       WHERE symbol=%s AND as_of >= CURRENT_DATE - %s AND pc_vol_ratio IS NOT NULL""",
                    (sym, CFG["pc_mean_window_days"]))
        pc_mean, pc_n = cur.fetchone()
        d = dict(agg)
        d["symbol"] = sym
        d["put_oi_delta_pct"] = round((agg["put_oi"] - prior[0]) / prior[0] * 100, 1) if prior and prior[0] else None
        d["skew25_delta"] = round(agg["skew25"] - float(prior[2]), 2) if prior and prior[2] is not None and agg["skew25"] is not None else None
        d["pc_vol_vs_mean"] = round(agg["pc_vol_ratio"] / float(pc_mean), 2) if pc_mean and agg["pc_vol_ratio"] else None
        d["pc_mean_n"] = int(pc_n or 0)
        # one plain sentence per row — inference language only
        bits = []
        if d["put_oi_delta_pct"] is not None:
            bits.append(f"put OI {d['put_oi_delta_pct']:+.0f}% vs prior snapshot")
        if d["skew25_delta"] is not None:
            bits.append(f"skew {d['skew25_delta']:+.1f}")
        if d["pc_oi_ratio"] is not None:
            bits.append(f"P/C OI {d['pc_oi_ratio']}")
        verdict = "hedging demand building" if ((d["put_oi_delta_pct"] or 0) > 5 or (d["skew25_delta"] or 0) > 1) else \
                  "no unusual hedging read" if bits else "baseline captured — deltas start next snapshot"
        d["line"] = f"{sym}: {' · '.join(bits) if bits else 'first capture'} — {verdict}"
        radar.append(d)
    radar.sort(key=lambda r: -(r.get("put_oi_delta_pct") or -999))

    snap = {
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "coverage": {"covered": covered, "failed": failed,
                     "note": f"{len(covered)}/{len(syms)} underlyings (priority universe first, then top holdings)"},
        "history_note": f"OI deltas vs prior snapshot; P/C-vs-mean over {CFG['pc_mean_window_days']}d as history accrues (n per row)",
        "inference_label": "positioning INFERENCE from OI/volume/skew — never order-flow claims",
        "radar": radar,
    }
    if not args.dry_run:
        SNAP.write_text(json.dumps(snap, default=str))
    print(f"[radar] covered {len(covered)}/{len(syms)} ({', '.join(failed) or 'no failures'}) → {SNAP.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
