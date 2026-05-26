#!/usr/bin/env python3
"""strategy_rotation_engine.py — Generate strategy rotation signals based on regime.

No auto-enable/disable. Signals are read-only/proposal-only.

Usage:
    .venv/bin/python scripts/strategy_rotation_engine.py --dry-run --json
    .venv/bin/python scripts/strategy_rotation_engine.py --apply --json
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
def _uid(p="SIG_"): return f"{p}{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}_{uuid.uuid4().hex[:8]}"
def _get_conn():
    from session13_db import get_conn
    return get_conn()


def generate_signals(conn):
    cur = conn.cursor()
    cur.execute("SELECT snapshot_id, regime_label, confidence, stale_data FROM market_regime_snapshots ORDER BY created_at DESC LIMIT 1")
    regime_row = cur.fetchone()
    if not regime_row:
        return [], None, "no_regime_snapshot"

    snap_id, regime, confidence, stale = regime_row

    cur.execute("SELECT strategy_id, strategy_name, favored_regimes, disfavored_regimes FROM strategy_regime_profiles WHERE active=true")
    profiles = cur.fetchall()

    signals = []
    for p in profiles:
        sid, sname, favored, disfavored = p[0], p[1], p[2] or [], p[3] or []

        if regime in favored:
            signal = "favor"; strength = 0.7; reason = f"{regime} is favored for {sid}"
            action = "monitor"
        elif regime in disfavored:
            signal = "de_emphasize"; strength = 0.6; reason = f"{regime} is disfavored for {sid}"
            action = "review"
        elif regime == "unknown" or stale:
            signal = "review_required"; strength = 0.3; reason = f"regime unknown/stale"
            action = "no_action"
        else:
            signal = "neutral"; strength = 0.5; reason = f"{regime} is neutral for {sid}"
            action = "no_action"

        if confidence and confidence < 0.3:
            signal = "review_required"; action = "no_action"
            reason += " (low confidence)"

        signals.append({
            "signal_id": _uid(), "snapshot_id": snap_id,
            "strategy_id": sid, "strategy_name": sname,
            "signal": signal, "signal_strength": round(strength * float(confidence or 0.5), 2),
            "confidence": confidence, "reason": reason,
            "supporting_indicators": [regime], "conflicting_indicators": [],
            "recommended_action": action, "requires_admin_approval": True,
        })
    return signals, snap_id, regime


def check_alignments(conn, snap_id, regime):
    cur = conn.cursor()
    alignments = []

    cur.execute("SELECT id, symbol, strategy_id FROM paper_trades WHERE status='open'")
    for row in cur.fetchall():
        tid, sym, strat = row
        cur.execute("SELECT favored_regimes, disfavored_regimes FROM strategy_regime_profiles WHERE strategy_id=%s", [strat])
        profile = cur.fetchone()
        if profile:
            favored, disfavored = profile[0] or [], profile[1] or []
            if regime in disfavored:
                label = "misaligned"; score = 30; reason = f"{sym} ({strat}) disfavored in {regime}"
            elif regime in favored:
                label = "aligned"; score = 80; reason = f"{sym} aligned"
            else:
                label = "partially_aligned"; score = 60; reason = f"{sym} neutral"
        else:
            label = "unknown"; score = 50; reason = f"No profile for {strat}"
        alignments.append({
            "alignment_id": _uid("ALN_"), "snapshot_id": snap_id,
            "symbol": sym, "strategy_id": strat, "paper_trade_id": tid,
            "alignment_type": "open_trade", "alignment_score": score,
            "alignment_label": label, "regime_label": regime, "reason": reason,
        })

    cur.execute("SELECT id, symbol, strategy_id FROM paper_trade_proposals WHERE status IN ('APPROVED','APPROVED_FOR_PAPER_TEST','PENDING') LIMIT 20")
    for row in cur.fetchall():
        pid, sym, strat = row
        cur.execute("SELECT favored_regimes, disfavored_regimes FROM strategy_regime_profiles WHERE strategy_id=%s", [strat])
        profile = cur.fetchone()
        label = "unknown"; score = 50; reason = f"Proposal {sym}"
        if profile:
            favored, disfavored = profile[0] or [], profile[1] or []
            if regime in disfavored:
                label = "misaligned"; score = 30; reason = f"Proposal {sym} ({strat}) disfavored"
            elif regime in favored:
                label = "aligned"; score = 80; reason = f"Proposal {sym} aligned"
        alignments.append({
            "alignment_id": _uid("ALN_"), "snapshot_id": snap_id,
            "symbol": sym, "strategy_id": strat, "proposal_id": pid,
            "alignment_type": "proposal", "alignment_score": score,
            "alignment_label": label, "regime_label": regime, "reason": reason,
        })
    return alignments


def save_signals(conn, signals, alignments, dry_run=True):
    if dry_run: return
    cur = conn.cursor()
    for s in signals:
        cur.execute("""
            INSERT INTO strategy_rotation_signals
                (signal_id, snapshot_id, strategy_id, strategy_name, signal,
                 signal_strength, confidence, reason, supporting_indicators,
                 conflicting_indicators, recommended_action, requires_admin_approval)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (signal_id) DO NOTHING
        """, [s["signal_id"], s["snapshot_id"], s["strategy_id"], s["strategy_name"],
              s["signal"], s["signal_strength"], s["confidence"], s["reason"],
              json.dumps(s["supporting_indicators"]), json.dumps(s["conflicting_indicators"]),
              s["recommended_action"], s["requires_admin_approval"]])
    for a in alignments:
        cur.execute("""
            INSERT INTO regime_trade_alignment
                (alignment_id, snapshot_id, symbol, strategy_id, paper_trade_id,
                 proposal_id, alignment_type, alignment_score, alignment_label,
                 regime_label, reason)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (alignment_id) DO NOTHING
        """, [a["alignment_id"], a["snapshot_id"], a["symbol"], a["strategy_id"],
              a.get("paper_trade_id"), a.get("proposal_id"), a["alignment_type"],
              a["alignment_score"], a["alignment_label"], a["regime_label"], a["reason"]])
    conn.commit()


def main():
    parser = argparse.ArgumentParser(description="Strategy Rotation Engine")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--latest", action="store_true")
    parser.add_argument("--strategy")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    dry_run = not args.apply
    conn = _get_conn()
    try:
        signals, snap_id, regime = generate_signals(conn)
        if args.strategy:
            signals = [s for s in signals if s["strategy_id"] == args.strategy]
        alignments = check_alignments(conn, snap_id, regime) if snap_id and regime != "no_regime_snapshot" else []
        if not dry_run:
            save_signals(conn, signals, alignments, dry_run=False)

        by_signal = {}
        for s in signals:
            by_signal[s["signal"]] = by_signal.get(s["signal"], 0) + 1
        out = {
            "mode": "dry_run" if dry_run else "applied",
            "regime": regime, "signals": len(signals), "alignments": len(alignments),
            "by_signal": by_signal,
            "misaligned": sum(1 for a in alignments if a["alignment_label"] == "misaligned"),
        }
        if args.json:
            out["rotation_signals"] = [{k: v for k, v in s.items() if k not in ("supporting_indicators","conflicting_indicators")} for s in signals]
            print(json.dumps(out, indent=2, default=str))
        else:
            print(f"Rotation: regime={regime}, {len(signals)} signals, {len(alignments)} alignments ({out['mode']})")
    finally:
        conn.close()

if __name__ == "__main__":
    main()
