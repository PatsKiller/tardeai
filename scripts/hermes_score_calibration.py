#!/usr/bin/env python3
"""hermes_score_calibration.py — H-4: learn which factors actually predicted forward returns and
propose weight adjustments (the feedback loop). ADVISORY — writes hermes_weight_calibration; the
operator applies changes to config/hermes_score_weights.yaml (never auto-edits live weights).

Method (transparent, no heavy deps):
  * pair each score snapshot with a LATER snapshot of the same symbol (>= MIN_HOURS later) → forward return
  * per factor, predictiveness = mean(fwd_return | factor>=60) - mean(fwd_return | factor<=40)
  * suggest new weights ∝ current_weight * (1 + K*normalized_predictiveness), renormalized
  * needs accumulated history — reports 'insufficient data' gracefully until enough snapshots exist

  python3 scripts/hermes_score_calibration.py [--apply]   # --apply writes suggestions to the DB table
"""
from __future__ import annotations
import argparse, json, sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
WEIGHTS_FILE = PROJECT_ROOT / "config" / "hermes_score_weights.yaml"
MIN_HOURS = 6
MIN_SAMPLES = 20
K = 0.5
FACTORS = ["technical_momentum", "setup_quality", "analyst", "social_sentiment",
           "sector_strength", "news_catalyst", "risk_reward"]


def _conn():
    from db_adapter import _get_conn
    return _get_conn()


def _weights():
    try:
        import yaml
        return {k: float(v) for k, v in (yaml.safe_load(WEIGHTS_FILE.read_text()) or {}).get("weights", {}).items()}
    except Exception:
        return {f: 1.0 / len(FACTORS) for f in FACTORS}


def run(apply=False):
    conn = _conn(); cur = conn.cursor()
    # forward-return pairs: each snapshot → the earliest later snapshot >= MIN_HOURS later (same symbol)
    cur.execute(f"""
        WITH s AS (SELECT symbol, price, components, scored_at FROM hermes_score_history WHERE price IS NOT NULL)
        SELECT a.components, (b.price - a.price)/a.price AS fwd_return
        FROM s a JOIN LATERAL (
            SELECT price FROM s b WHERE b.symbol=a.symbol AND b.scored_at >= a.scored_at + interval '{MIN_HOURS} hours'
            ORDER BY b.scored_at ASC LIMIT 1
        ) b ON true
        WHERE a.price > 0""")
    pairs = cur.fetchall()
    # OUTCOME pairs (2026-06-11): realized trade P&L joined to the latest Hermes snapshot BEFORE entry —
    # the missing live-edge signal. Weighted 2x vs price-pairs (realized money > mark-to-market drift).
    cur.execute("""
        SELECT h.components,
               CASE WHEN pt.entry_price > 0 AND pt.pnl IS NOT NULL AND pt.shares > 0
                    THEN pt.pnl / NULLIF(pt.entry_price * pt.shares, 0) ELSE NULL END AS fwd_return
        FROM paper_trades pt
        JOIN LATERAL (
            SELECT components FROM hermes_score_history h
            WHERE h.symbol = pt.symbol AND h.scored_at <= COALESCE(pt.entry_time, pt.created_at)
            ORDER BY h.scored_at DESC LIMIT 1
        ) h ON true
        WHERE pt.status = 'closed' AND pt.pnl IS NOT NULL AND pt.pnl <> 0
    """)
    outcome_pairs = [r for r in cur.fetchall() if r[1] is not None]
    if outcome_pairs:
        pairs = list(pairs) + outcome_pairs * 2   # 2x weight for realized outcomes
        print(f"  [calibration] including {len(outcome_pairs)} realized-trade outcome pairs (2x weight)")
    if len(pairs) < MIN_SAMPLES:
        print(json.dumps({"status": "insufficient_data", "pairs": len(pairs),
                          "note": f"need >= {MIN_SAMPLES} score→forward-return pairs (>= {MIN_HOURS}h apart). "
                                  "History is still accumulating from the */30 scorer cron."}, indent=2))
        return {"status": "insufficient_data", "pairs": len(pairs)}

    weights = _weights()
    pred = {}
    for f in FACTORS:
        hi, lo = [], []
        for comp, ret in pairs:
            sc = (comp or {}).get(f, {}).get("score")
            if sc is None:
                continue
            (hi if float(sc) >= 60 else lo if float(sc) <= 40 else []).append(float(ret))
        if len(hi) >= 5 and len(lo) >= 5:
            pred[f] = (sum(hi) / len(hi)) - (sum(lo) / len(lo))   # forward-return edge of a high vs low factor
    if not pred:
        print(json.dumps({"status": "insufficient_factor_spread", "pairs": len(pairs)}, indent=2)); return {"status": "insufficient_factor_spread"}

    mx = max(abs(v) for v in pred.values()) or 1.0
    suggestions = []
    for f in FACTORS:
        cw = weights.get(f, 0)
        if f in pred:
            sw = max(0.0, cw * (1 + K * (pred[f] / mx)))
        else:
            sw = cw
        suggestions.append((f, cw, sw, pred.get(f)))
    tot = sum(s[2] for s in suggestions) or 1.0
    suggestions = [(f, cw, round(sw / tot, 4), p) for f, cw, sw, p in suggestions]

    if apply:
        for f, cw, sw, p in suggestions:
            cur.execute("""INSERT INTO hermes_weight_calibration (factor, current_weight, suggested_weight, predictiveness, sample_n, rationale)
                           VALUES (%s, %s, %s, %s, %s, %s)""",
                        (f, cw, sw, p, len(pairs),
                         f"high-{f} forward-return edge = {p:+.4f}" if p is not None else "insufficient spread — weight held"))
        conn.commit()
    print(json.dumps({"status": "ok", "pairs": len(pairs), "applied": apply,
                      "suggestions": [{"factor": f, "current": round(cw, 3), "suggested": sw,
                                       "predictiveness": (round(p, 4) if p is not None else None)} for f, cw, sw, p in suggestions]}, indent=2))
    return {"status": "ok", "pairs": len(pairs)}


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--apply", action="store_true")
    run(apply=ap.parse_args().apply)


if __name__ == "__main__":
    main()
