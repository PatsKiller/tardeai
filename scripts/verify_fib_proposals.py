#!/usr/bin/env python3
"""verify_fib_proposals.py — one-shot check (scheduled Mon 2026-06-22 AM) that the tilt-aware dedup
tie-break (commit 3b212d5d) produced fib_retracement_bounce proposals, after weeks of zero. Reports the
result to Telegram and removes its own cron line so it runs exactly once. Safe to run manually anytime.
"""
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from db_adapter import _get_conn


def build_report() -> str:
    cur = _get_conn().cursor()
    cur.execute("""SELECT symbol, status, created_at::time, origin
                     FROM paper_trade_proposals
                    WHERE strategy_id='fib_retracement_bounce' AND created_at::date=CURRENT_DATE
                    ORDER BY created_at""")
    props = cur.fetchall()
    cur.execute("""SELECT decision, count(*) FROM auto_proposal_decisions
                    WHERE strategy_id='fib_retracement_bounce' AND created_at::date=CURRENT_DATE
                    GROUP BY decision ORDER BY 2 DESC""")
    decisions = cur.fetchall()
    cur.execute("""SELECT count(*), round(avg(signal_score),1)
                     FROM strategy_signals
                    WHERE strategy_id='fib_retracement_bounce' AND fired_at::date=CURRENT_DATE""")
    sig_n, sig_avg = cur.fetchone()
    try:
        import strategy_tilt as st
        tilt = st.get_tilt("fib_retracement_bounce")
    except Exception:
        tilt = "?"

    lines = ["\U0001f9ea FIB PROPOSAL VERIFICATION (tilt-aware dedup fix)"]
    if props:
        lines.append(f"✅ FIX WORKED — {len(props)} fib proposal(s) created today (was 0/week):")
        for sym, status, t, origin in props[:10]:
            lines.append(f"  • {sym} {status} @ {str(t)[:5]} ({origin})")
    else:
        lines.append(f"⚠️ STILL ZERO fib proposals today.")
        lines.append(f"  fib signals fired today: {sig_n or 0} (avg score {sig_avg})")
        lines.append(f"  fib tilt: {tilt} (expect ~1.5)")
        if decisions:
            lines.append("  decisions: " + ", ".join(f"{d}={n}" for d, n in decisions))
        lines.append("  → likely the symbols were pre-claimed, or signals didn't fire/grade. Needs review.")
    if props and decisions:
        lines.append("decisions: " + ", ".join(f"{d}={n}" for d, n in decisions))
    return "\n".join(lines)


def _self_remove_cron():
    try:
        cur = subprocess.run(["crontab", "-l"], capture_output=True, text=True)
        if cur.returncode != 0:
            return
        kept = [ln for ln in cur.stdout.splitlines() if "verify_fib_proposals.py" not in ln]
        subprocess.run(["crontab", "-"], input="\n".join(kept) + "\n", text=True)
    except Exception:
        pass


def main():
    report = build_report()
    print(report)
    try:
        from telegram_alert import send_telegram
        send_telegram(report, bypass_router=True)
    except Exception as e:
        print(f"(telegram send failed: {e})")
    if "--keep-cron" not in sys.argv:
        _self_remove_cron()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
