#!/usr/bin/env python3
"""Generate dual opinions for journal entries and backtest results."""
import json, os, sys
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

env_path = PROJECT_ROOT / ".env"
if env_path.exists():
    for line in env_path.read_text().splitlines():
        if "=" in line and not line.strip().startswith("#"):
            k, v = line.split("=", 1)
            k, v = k.strip(), v.strip().strip("'\"")
            if k and k not in os.environ:
                os.environ[k] = v

def get_conn():
    import psycopg2
    return psycopg2.connect(
        host=os.getenv("DB_HOST", "localhost"), port=os.getenv("DB_PORT", "5432"),
        dbname=os.getenv("DB_NAME", "trade_ai"), user=os.getenv("DB_USER", "trade_ai"),
        password=os.getenv("DB_PASSWORD", ""),
    )

def generate_journal_opinions(max_items=10):
    """Generate Hermes opinions for closed trades."""
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        SELECT id, symbol, strategy_id, entry_price, exit_price, stop_loss, target_1,
               pnl, exit_reason, hold_time_min, r_multiple, closed_via,
               max_favorable_excursion, max_adverse_excursion, closed_at
        FROM paper_trades WHERE status = 'closed'
        ORDER BY closed_at DESC LIMIT %s
    """, [max_items])
    cols = [d[0] for d in cur.description]
    trades = [dict(zip(cols, r)) for r in cur.fetchall()]
    conn.close()

    opinions = []
    for t in trades:
        entry = float(t["entry_price"] or 0)
        stop = float(t["stop_loss"] or 0)
        exit_p = float(t["exit_price"] or 0)
        pnl = float(t["pnl"] or 0)
        mfe = float(t["max_favorable_excursion"] or 0)
        mae = float(t["max_adverse_excursion"] or 0)
        hold = t["hold_time_min"]
        exit_reason = t["exit_reason"] or "unknown"

        # TradeAI original
        tradeai = {
            "trade_id": t["id"], "score": None, "decision": exit_reason,
            "summary": f"{t['symbol']} closed via {t['closed_via'] or 'unknown'}: {exit_reason}. P&L: {'${:.2f}'.format(pnl) if pnl else 'N/A'}.",
        }

        # Hermes audit
        risk_flags = []
        missing = []
        if not hold: missing.append("hold_time missing — cannot evaluate timing")
        if not exit_p: missing.append("exit_price missing")
        if stop > 0 and entry > 0 and stop >= entry:
            risk_flags.append("Stop >= entry — defective stop placement")
        if exit_reason in ("phantom_no_alpaca_position", "duplicate_submit_race", "orphan_duplicate_from_partial_fill_race"):
            risk_flags.append(f"System close ({exit_reason}) — not a planned exit")
        if mfe > 5 and exit_reason in ("stop_hit", "stop_hit_instant"):
            risk_flags.append(f"Premature exit — MFE was +{mfe:.1f}% but trade hit stop")

        # Agreement
        if not risk_flags and not missing:
            agreement = "AGREE"
            hermes_summary = f"Hermes agrees. Exit {exit_reason} appears valid. P&L: {'${:.2f}'.format(pnl) if pnl else 'N/A'}."
        elif risk_flags:
            agreement = "DISAGREE"
            hermes_summary = f"Hermes flags {len(risk_flags)} issue(s): {risk_flags[0]}"
        else:
            agreement = "NEEDS_MORE_EVIDENCE"
            hermes_summary = f"Hermes needs more data: {missing[0]}"

        opinions.append({
            "object_type": "closed_trade",
            "object_id": str(t["id"]),
            "symbol": t["symbol"],
            "strategy": t["strategy_id"],
            "tradeai_original": tradeai,
            "hermes_audit": {"missing_context": missing, "risk_flags": risk_flags, "learning_links": 0},
            "hermes_enhancement": {
                "shadow_score": None, "delta": 0,
                "lesson_types": ["stop_quality" if any("stop" in f.lower() for f in risk_flags) else "exit_review"],
                "summary": hermes_summary,
            },
            "hermes_agreement_status": agreement,
            "hermes_confidence": 0.6 if risk_flags else 0.4,
            "recommended_operator_choice": "REVIEW_BOTH" if agreement != "AGREE" else "KEEP_TRADEAI_ORIGINAL",
            "no_overwrite": True, "advisory_only": True,
            "created_at": datetime.now().isoformat(),
        })

    return opinions

def generate_backtest_opinions(max_items=10):
    """Generate Hermes opinions for backtest strategy results."""
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        SELECT strategy_id,
               COUNT(*) as trades,
               ROUND(AVG(CASE WHEN pnl > 0 THEN 1.0 ELSE 0.0 END) * 100, 1) as win_rate,
               ROUND(AVG(r_multiple)::numeric, 2) as avg_r,
               ROUND(SUM(pnl)::numeric, 2) as total_pnl
        FROM strategy_backtest_trades
        WHERE strategy_id IS NOT NULL AND strategy_id != '' AND strategy_id != 'unknown'
        GROUP BY strategy_id
        HAVING COUNT(*) >= 5
        ORDER BY COUNT(*) DESC LIMIT %s
    """, [max_items])
    results = [{"strategy": r[0], "trades": r[1], "win_rate": float(r[2] or 0), "avg_r": float(r[3] or 0), "total_pnl": float(r[4] or 0)} for r in cur.fetchall()]
    conn.close()

    opinions = []
    for r in results:
        tradeai = {
            "score": None, "decision": "backtest_result",
            "summary": f"{r['strategy']}: {r['win_rate']}% WR, avg R {r['avg_r']}, {r['trades']} trades, total P&L ${r['total_pnl']}.",
        }

        risk_flags = []
        if r["trades"] < 20: risk_flags.append(f"Small sample ({r['trades']} trades) — not statistically reliable")
        if r["win_rate"] < 35: risk_flags.append(f"Win rate {r['win_rate']}% below 35% viability threshold")
        if r["avg_r"] < 0: risk_flags.append(f"Negative avg R ({r['avg_r']}) — expected value is negative")

        if not risk_flags:
            agreement = "AGREE"
            hermes_summary = f"Hermes agrees: {r['strategy']} backtest looks viable ({r['win_rate']}% WR, n={r['trades']})."
        elif r["win_rate"] < 35:
            agreement = "DISAGREE"
            hermes_summary = f"Hermes recommends review: {r['strategy']} has {r['win_rate']}% WR. {risk_flags[0]}."
        else:
            agreement = "AGREE_WITH_CAUTION"
            hermes_summary = f"Hermes flags caution: {risk_flags[0]}."

        opinions.append({
            "object_type": "backtest_strategy",
            "object_id": r["strategy"],
            "symbol": None,
            "strategy": r["strategy"],
            "tradeai_original": tradeai,
            "hermes_audit": {"missing_context": [], "risk_flags": risk_flags, "learning_links": 0},
            "hermes_enhancement": {
                "shadow_score": None, "delta": 0,
                "lesson_types": ["weak_backtest" if r["win_rate"] < 35 else "backtest_review"],
                "summary": hermes_summary,
            },
            "hermes_agreement_status": agreement,
            "hermes_confidence": 0.5,
            "recommended_operator_choice": "REVIEW_BOTH" if agreement != "AGREE" else "KEEP_TRADEAI_ORIGINAL",
            "no_overwrite": True, "advisory_only": True,
            "created_at": datetime.now().isoformat(),
        })

    return opinions

if __name__ == "__main__":
    j_opinions = generate_journal_opinions(10)
    b_opinions = generate_backtest_opinions(10)
    all_opinions = j_opinions + b_opinions

    out_dir = PROJECT_ROOT / "data" / "advisory"
    (out_dir / "journal_dual_opinions").mkdir(parents=True, exist_ok=True)
    (out_dir / "backtest_dual_opinions").mkdir(parents=True, exist_ok=True)

    today = datetime.now().strftime("%Y-%m-%d")
    (out_dir / "journal_dual_opinions" / f"{today}_journal_opinions.json").write_text(json.dumps({"opinions": j_opinions, "total": len(j_opinions)}, indent=2, default=str))
    (out_dir / "backtest_dual_opinions" / f"{today}_backtest_opinions.json").write_text(json.dumps({"opinions": b_opinions, "total": len(b_opinions)}, indent=2, default=str))

    print(f"Journal opinions: {len(j_opinions)}")
    for o in j_opinions[:3]:
        print(f"  {o['symbol']:8s} {o['hermes_agreement_status']:25s} {o['hermes_enhancement']['summary'][:60]}")
    print(f"\nBacktest opinions: {len(b_opinions)}")
    for o in b_opinions[:3]:
        print(f"  {o['strategy']:25s} {o['hermes_agreement_status']:25s} {o['hermes_enhancement']['summary'][:60]}")
