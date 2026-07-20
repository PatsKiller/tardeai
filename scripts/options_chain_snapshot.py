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

_FULL_CFG = json.loads((ROOT / "config" / "defense_recommendations.json").read_text())
CFG = _FULL_CFG["chain_snapshot"]
_CC_VAL = _FULL_CFG["cc_validation"]
_PP = _FULL_CFG.get("protective_put")  # R1: absent block = no put picks, never a crash
SNAP = ROOT / "data" / "runtime" / "hedging_radar_latest.json"



def _next_earnings(symbol: str):
    """Next earnings date for the underlying, or None if genuinely unknown.

    The covered-call picker was earnings-BLIND: it scored purely on DTE and
    delta, so it happily recommended an expiry that straddles an earnings
    report, and the downstream risk gate then refused the desk's own suggestion
    (CSCO 2026-08-21 proposed while CSCO reports 2026-08-12 — operator hit this
    2026-07-20). Selecting the contract is the right place to know this.
    """
    try:
        from earnings_provider import get_one, SCHEDULED
        info = get_one(symbol)
        return info.date if info.state == SCHEDULED else None
    except Exception:
        return None


def universe() -> list:
    syms = list(CFG["priority_universe"])
    try:
        h = json.loads((ROOT / "data" / "portfolios" / "state" / "holdings.json").read_text())
        rows = [r for r in h.get("holdings", []) if not r.get("is_cash") and r.get("symbol")]
        rows.sort(key=lambda r: -(r.get("market_value") or 0))
        added = 0
        for r in rows:  # count UNIQUE additions — dup rows (V, SCHD in two accounts) must not eat slots
            if added >= CFG["top_holdings_n"]:
                break
            if r["symbol"] not in syms:
                syms.append(r["symbol"])
                added += 1
    except Exception as e:
        print(f"[radar] holdings unavailable ({e}) — priority universe only")
    return syms


def aggregate(chain: dict) -> dict | None:
    """One underlying's chain → radar aggregates."""
    if not chain or chain.get("status") != "ok":
        return None
    # Resolved ONCE per underlying: the covered-call picker needs to know whether
    # an expiry straddles earnings, and a per-strike lookup would hammer the
    # provider for every candidate contract.
    _earn = _next_earnings(chain.get("symbol") or "")
    put_oi = call_oi = put_vol = call_vol = 0
    atm_ivs, put25, call25 = [], [], []
    tgt = CFG["skew_delta_target"]
    cc_call = None  # WS-CARD: concrete covered-call pick — ~0.25-0.30Δ, 21-45 DTE
    prot_put = None  # R1: protective-put pick — ~0.25-0.30Δ, 45-120 DTE, same liquidity rails
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
            dte = s.get("dte") or exp.get("dte") or 0
            if (s["side"] == "call" and 18 <= dte <= 50 and 0.15 <= ad <= 0.38
                    and s.get("bid") is not None and s.get("ask") is not None):
                # v6.1 operator ask: VALIDATE greeks + liquidity before a strike
                # ever reaches a card — OI, volume, spread, delta band from config
                vc = _CC_VAL
                mid = (s["bid"] + s["ask"]) / 2
                spread_pct = round((s["ask"] - s["bid"]) / mid * 100, 1) if mid else 999
                oi = s.get("oi") or 0
                vol = s.get("volume") or 0
                valid = (oi >= vc["min_open_interest"]
                         and max(oi, vol) >= vc["min_volume_or_oi"]
                         and spread_pct <= vc["max_spread_pct_of_mid"]
                         and vc["delta_band"][0] <= ad <= vc["delta_band"][1])
                # Earnings inside the contract is a first-class selection
                # criterion, not just a downstream refusal. An expiry that
                # straddles the report is heavily penalised so an earnings-SAFE
                # expiry wins whenever one exists; if none does we still pick,
                # but the card carries the flag instead of silently proposing a
                # trade the risk gate will reject.
                _spans = bool(_earn and s["exp"] and str(s["exp"])[:10] >= _earn.isoformat())
                fit = abs(ad - 0.28) + (0 if valid else 10) + (5 if _spans else 0)
                if cc_call is None or fit < cc_call["_fit"]:
                    cc_call = {"exp": s["exp"], "dte": dte, "strike": s["strike"],
                               "delta": round(ad, 2), "iv": round(float(iv), 1),
                               "mid": round(mid, 2), "bid": s["bid"], "ask": s["ask"],
                               "oi": oi, "volume": vol, "spread_pct": spread_pct,
                               "validated": valid,
                               "spans_earnings": _spans,
                               "earnings_date": _earn.isoformat() if _earn else None,
                               "validation": (f"OI {oi} · vol {vol} · spread {spread_pct}% · Δ{round(ad, 2)} · IV {round(float(iv), 1)}"
                                              + ("" if valid else f" — FAILED rails (need OI≥{vc['min_open_interest']}, spread≤{vc['max_spread_pct_of_mid']}%)")
                                              + (f" — ⚠ EARNINGS {_earn.isoformat()} INSIDE this contract" if _spans else "")),
                               "_fit": fit}
            if (_PP and s["side"] == "put"
                    and _PP["tenor_dte"][0] <= dte <= _PP["tenor_dte"][1]
                    and _PP["delta_band"][0] <= ad <= _PP["delta_band"][1]
                    and s.get("bid") is not None and s.get("ask") is not None):
                vc = _CC_VAL  # same liquidity rails as CC picks — one standard, one config
                mid = (s["bid"] + s["ask"]) / 2
                spread_pct = round((s["ask"] - s["bid"]) / mid * 100, 1) if mid else 999
                oi = s.get("oi") or 0
                vol = s.get("volume") or 0
                valid = (oi >= vc["min_open_interest"]
                         and max(oi, vol) >= vc["min_volume_or_oi"]
                         and spread_pct <= vc["max_spread_pct_of_mid"])
                fit = abs(ad - 0.28) + (0 if valid else 10)
                if prot_put is None or fit < prot_put["_fit"]:
                    prot_put = {"exp": s["exp"], "dte": dte, "strike": s["strike"],
                                "delta": round(ad, 2), "iv": round(float(iv), 1),
                                "mid": round(mid, 2), "bid": s["bid"], "ask": s["ask"],
                                "oi": oi, "volume": vol, "spread_pct": spread_pct,
                                "validated": valid,
                                "validation": (f"OI {oi} · vol {vol} · spread {spread_pct}% · Δ{round(ad, 2)} · IV {round(float(iv), 1)}"
                                               + ("" if valid else f" — FAILED rails (need OI≥{vc['min_open_interest']}, spread≤{vc['max_spread_pct_of_mid']}%)")),
                                "_fit": fit}
    if cc_call:
        cc_call.pop("_fit", None)
    if prot_put:
        prot_put.pop("_fit", None)
    mean = lambda xs: round(sum(xs) / len(xs), 2) if xs else None
    return {
        "put_oi": put_oi, "call_oi": call_oi, "put_vol": put_vol, "call_vol": call_vol,
        "pc_oi_ratio": round(put_oi / call_oi, 3) if call_oi else None,
        "pc_vol_ratio": round(put_vol / call_vol, 3) if call_vol else None,
        "atm_iv": mean(atm_ivs),
        "skew25": round(mean(put25) - mean(call25), 2) if put25 and call25 else None,
        "underlying_price": chain.get("underlying_price"),
        "cc_call": cc_call,
        "prot_put": prot_put,
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
