#!/usr/bin/env python3
"""market_regime_classifier.py — Classify current market regime from indicators.

Usage:
    .venv/bin/python scripts/market_regime_classifier.py --dry-run --json
    .venv/bin/python scripts/market_regime_classifier.py --apply --json
    .venv/bin/python scripts/market_regime_classifier.py --latest --json
"""
import argparse, json, os, sys, uuid
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / ".env")

def _f(v): return float(v) if isinstance(v, Decimal) else v
def _uid(p="RS_"): return f"{p}{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}_{uuid.uuid4().hex[:8]}"

def _get_conn():
    from session13_db import get_conn
    return get_conn()


def classify(conn, snapshot_id=None):
    """Classify market regime from available indicators."""
    from market_session import current_market_session
    session = current_market_session()

    # Collect latest indicators
    cur = conn.cursor()
    if snapshot_id:
        cur.execute("SELECT indicator_key, signal, value, value_text FROM market_regime_indicators WHERE snapshot_id=%s", [snapshot_id])
    else:
        cur.execute("SELECT indicator_key, signal, value, value_text FROM market_regime_indicators ORDER BY created_at DESC LIMIT 20")

    indicators = {}
    for row in cur.fetchall():
        indicators[row[0]] = {"signal": row[1], "value": _f(row[2]), "text": row[3]}

    # Scoring model
    scores = {"risk_on_trend": 0, "risk_off": 0, "choppy_range": 0,
              "high_volatility": 0, "low_volatility_grind": 0,
              "broad_momentum": 0, "unknown": 0}
    missing = []

    # Breadth
    breadth = indicators.get("scan_breadth_24h", {})
    if breadth.get("signal") == "broad":
        scores["broad_momentum"] += 2; scores["risk_on_trend"] += 1
    elif breadth.get("signal") == "narrow":
        scores["choppy_range"] += 1
    elif breadth.get("signal") == "missing":
        missing.append("scan_breadth")

    # Score momentum
    score_avg = indicators.get("scan_score_avg", {})
    if score_avg.get("signal") == "bullish":
        scores["risk_on_trend"] += 2; scores["broad_momentum"] += 1
    elif score_avg.get("signal") == "bearish":
        scores["risk_off"] += 2

    # Volatility
    gap_vol = indicators.get("gap_volatility_proxy", {})
    if gap_vol.get("signal") == "high_vol":
        scores["high_volatility"] += 3
    elif gap_vol.get("signal") == "low_vol":
        scores["low_volatility_grind"] += 2

    # VIX
    vix = indicators.get("vix_close", {})
    if vix.get("signal") == "extreme":
        scores["high_volatility"] += 3; scores["risk_off"] += 2
    elif vix.get("signal") == "high":
        scores["high_volatility"] += 2; scores["risk_off"] += 1
    elif vix.get("signal") == "low":
        scores["low_volatility_grind"] += 2; scores["risk_on_trend"] += 1
    elif vix.get("signal") == "normal":
        scores["risk_on_trend"] += 1
    elif not vix:
        missing.append("no_vix_data")

    # Source health
    finviz = indicators.get("finviz_health", {})
    if finviz.get("signal") == "risk_off":
        scores["risk_off"] += 1; missing.append("finviz_degraded")

    # Session
    if session in ("weekend", "holiday", "closed"):
        scores["unknown"] += 2; missing.append(f"market_{session}")

    # If too little data
    if len(indicators) < 3:
        scores["unknown"] += 5; missing.append("insufficient_indicators")

    # Pick regime
    regime = max(scores, key=scores.get)
    total = sum(scores.values()) or 1
    confidence = round(scores[regime] / total, 2) if total > 0 else 0
    stale = len(missing) > 2 or "insufficient_indicators" in missing

    # States
    vol_state = gap_vol.get("signal", "unknown")
    trend_state = score_avg.get("signal", "unknown")
    breadth_state = breadth.get("signal", "unknown")

    summary = f"Regime: {regime} (conf={confidence:.0%})"
    if missing:
        summary += f", missing: {', '.join(missing[:3])}"

    snapshot = {
        "snapshot_id": _uid(), "market_session": session,
        "regime_label": regime, "regime_score": scores[regime],
        "confidence": confidence,
        "volatility_state": vol_state, "trend_state": trend_state,
        "breadth_state": breadth_state, "liquidity_state": "unknown",
        "leadership_state": "unknown", "risk_appetite_state": trend_state,
        "macro_state": "unknown", "data_freshness_state": "stale" if stale else "fresh",
        "stale_data": stale, "missing_data": missing,
        "inputs": {k: v.get("signal") for k, v in indicators.items()},
        "summary": summary,
    }
    return snapshot


def save_snapshot(conn, snapshot, dry_run=True):
    if dry_run: return
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO market_regime_snapshots
            (snapshot_id, generated_at, market_session, regime_label, regime_score, confidence,
             volatility_state, trend_state, breadth_state, liquidity_state,
             leadership_state, risk_appetite_state, macro_state, data_freshness_state,
             stale_data, missing_data, inputs, summary)
        VALUES (%s, NOW(), %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        ON CONFLICT (snapshot_id) DO NOTHING
    """, [snapshot["snapshot_id"], snapshot["market_session"], snapshot["regime_label"],
          snapshot["regime_score"], snapshot["confidence"],
          snapshot["volatility_state"], snapshot["trend_state"], snapshot["breadth_state"],
          snapshot["liquidity_state"], snapshot["leadership_state"],
          snapshot["risk_appetite_state"], snapshot["macro_state"],
          snapshot["data_freshness_state"], snapshot["stale_data"],
          json.dumps(snapshot["missing_data"]), json.dumps(snapshot["inputs"]),
          snapshot["summary"]])
    conn.commit()


def _get_previous_regime(conn):
    """Get the most recent regime label before the current run."""
    cur = conn.cursor()
    cur.execute("SELECT regime_label FROM market_regime_snapshots ORDER BY created_at DESC LIMIT 1")
    row = cur.fetchone()
    return row[0] if row else None


def _alert_regime_change(old_regime, snapshot):
    """Send Telegram alert when regime changes."""
    try:
        from alert_dispatcher import dispatch_alert
        new = snapshot["regime_label"]
        vol = snapshot.get("volatility_state", "?")
        trend = snapshot.get("trend_state", "?")
        breadth = snapshot.get("breadth_state", "?")
        conf = snapshot.get("confidence", 0)
        vix_input = snapshot.get("inputs", {}).get("vix_close", "--")

        message = (
            f"*Market Regime Changed*\n\n"
            f"{old_regime} → *{new}* (conf={conf:.0%})\n\n"
            f"Volatility: {vol}\n"
            f"Trend: {trend}\n"
            f"Breadth: {breadth}\n"
            f"VIX signal: {vix_input}\n\n"
            f"Review open positions for regime alignment."
        )
        dispatch_alert(
            "regime_change", f"Regime: {old_regime} → {new}",
            message, tier="ALERT", source="market_regime_classifier",
            dedupe_scope="global",
        )
    except Exception:
        pass


def main():
    parser = argparse.ArgumentParser(description="Market Regime Classifier")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--latest", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    dry_run = not args.apply
    conn = _get_conn()
    try:
        if args.latest:
            cur = conn.cursor()
            cur.execute("SELECT snapshot_id, regime_label, confidence, stale_data, summary FROM market_regime_snapshots ORDER BY created_at DESC LIMIT 1")
            row = cur.fetchone()
            if row:
                out = {"snapshot_id": row[0], "regime": row[1], "confidence": _f(row[2]),
                       "stale": row[3], "summary": row[4]}
            else:
                out = {"message": "No regime snapshots yet"}
            print(json.dumps(out, indent=2, default=str) if args.json else str(out))
            return

        snapshot = classify(conn)
        if not dry_run:
            # Check for regime change before saving
            prev = _get_previous_regime(conn)
            save_snapshot(conn, snapshot)
            if prev and prev != snapshot["regime_label"]:
                _alert_regime_change(prev, snapshot)

        out = {"mode": "dry_run" if dry_run else "applied", **snapshot}
        if args.json:
            print(json.dumps(out, indent=2, default=str))
        else:
            print(f"Regime: {snapshot['regime_label']} (conf={snapshot['confidence']:.0%}, stale={snapshot['stale_data']})")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
